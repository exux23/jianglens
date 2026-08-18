#!/usr/bin/env node
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { compactYoutubeMetadata, youtubeUrl } from "./lib/youtube-metadata.mjs";

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function parseArgs(argv) {
  const args = new Map();
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) throw new Error(`Unexpected positional argument: ${arg}`);
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) args.set(key, true);
    else {
      args.set(key, next);
      i += 1;
    }
  }
  return args;
}

function option(args, key, fallback) {
  const value = args.get(key);
  return value === undefined || value === true ? fallback : value;
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function eventText(event) {
  return cleanText((event?.segs || []).map((seg) => seg?.utf8 || "").join(""));
}

function json3ToTurns(data) {
  const events = Array.isArray(data?.events) ? data.events : [];
  const turns = [];
  let current = null;
  let previousText = null;

  function flush() {
    if (!current || !cleanText(current.text)) {
      current = null;
      return;
    }
    turns.push({
      start: Number(current.start.toFixed(3)),
      end: Number(Math.max(current.start, current.end).toFixed(3)),
      speaker: "UNKNOWN",
      text: cleanText(current.text),
    });
    current = null;
  }

  for (const event of events) {
    const text = eventText(event);
    if (!text || text === previousText) continue;
    previousText = text;
    const start = Number(event.tStartMs || 0) / 1000;
    const duration = Number(event.dDurationMs || 0) / 1000;
    const end = start + Math.max(0, duration);

    if (!current) current = { start, end, text };
    else {
      const candidate = `${current.text} ${text}`;
      const wordCount = cleanText(candidate).split(/\s+/).filter(Boolean).length;
      if (start - current.start > 55 || wordCount > 130) {
        flush();
        current = { start, end, text };
      } else {
        current.end = Math.max(current.end, end);
        current.text = candidate;
      }
    }
  }
  flush();
  return turns;
}

function cookiesArgs() {
  const cookies = process.env.JIANGLENS_YOUTUBE_COOKIES_FILE || process.env.YOUTUBE_COOKIES_FILE || process.env.YTDLP_COOKIES_FILE;
  return cookies ? ["--cookies", cookies] : [];
}

async function runYtDlp(args, options = {}) {
  return execFileAsync("yt-dlp", [...cookiesArgs(), ...args], {
    cwd: repoRoot,
    maxBuffer: 64 * 1024 * 1024,
    ...options,
  });
}

async function fetchMetadata(videoId) {
  const { stdout } = await runYtDlp([
    "--dump-single-json",
    "--skip-download",
    "--ignore-no-formats-error",
    "--no-warnings",
    youtubeUrl(videoId),
  ]);
  return JSON.parse(stdout);
}

async function fetchCaptions(videoId, tmpDir) {
  await fs.rm(tmpDir, { recursive: true, force: true });
  await fs.mkdir(tmpDir, { recursive: true });
  try {
    await runYtDlp([
      "--skip-download",
      "--write-subs",
      "--write-auto-subs",
      "--sub-langs", "en.*,en",
      "--sub-format", "json3",
      "--output", path.join(tmpDir, "%(id)s.%(ext)s"),
      "--no-warnings",
      youtubeUrl(videoId),
    ]);
  } catch (error) {
    const stderr = String(error.stderr || "");
    if (!/subtitles|subtitle|captions/i.test(stderr)) throw error;
  }

  const files = (await fs.readdir(tmpDir)).filter((name) => name.endsWith(".json3"));
  const preferred = files.find((name) => name.endsWith(".en.json3"))
    || files.find((name) => /\.en[-_.]/i.test(name))
    || files[0];
  return preferred ? path.join(tmpDir, preferred) : null;
}

async function runNode(script, args) {
  const { stdout } = await execFileAsync("node", [script, ...args], {
    cwd: repoRoot,
    maxBuffer: 64 * 1024 * 1024,
  });
  return stdout.trim();
}

function lastJson(stdout) {
  const start = stdout.lastIndexOf("\n{");
  const text = start === -1 ? stdout : stdout.slice(start + 1);
  return JSON.parse(text);
}

async function processVideo(item, channelPath) {
  const videoId = item.video_id;
  const rawDir = path.join(repoRoot, "content/sources/raw/youtube", channelPath, videoId);
  const transcriptionPath = path.join(rawDir, "transcription.json");
  const metadataPath = path.join(rawDir, "metadata.youtube.json");

  if (!await exists(transcriptionPath)) {
    const metadataRaw = await fetchMetadata(videoId);
    const metadata = compactYoutubeMetadata(metadataRaw, "source-scout/yt-dlp");
    const tmpDir = path.join(repoRoot, "ops/staging/source-scout", videoId);
    const captionsPath = await fetchCaptions(videoId, tmpDir);
    if (!captionsPath) return { status: "needs-transcript", video_id: videoId, reason: "No English YouTube captions were available." };

    const captions = await readJson(captionsPath);
    const turns = json3ToTurns(captions);
    if (!turns.length) return { status: "needs-transcript", video_id: videoId, reason: "Caption file contained no usable text turns." };

    await writeJson(metadataPath, metadata);
    await writeJson(transcriptionPath, {
      schema_version: 1,
      source: "youtube-captions",
      language: "en",
      speaker_mode: "unresolved-youtube-captions",
      generated_at: new Date().toISOString(),
      turns,
    });
  }

  const importStdout = await runNode("ops/scripts/import-colab-video.mjs", [
    "--video-id", videoId,
    "--channel", channelPath,
    "--no-fetch-youtube-metadata",
  ]);
  const imported = lastJson(importStdout);
  await runNode("ops/scripts/prepare-agent-transcript-packets.mjs", ["--source", imported.output_dir]);
  return { status: "imported", video_id: videoId, source_id: imported.source_id, output_dir: imported.output_dir };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const queuePath = path.resolve(repoRoot, option(args, "queue", "content/workflow/tasks/source-discovery.json"));
  const channelPath = option(args, "channel-path", "@PredictiveHistory");
  const max = Math.max(0, Number(option(args, "max", "2")) || 0);
  const retryNeedsTranscript = args.get("retry-needs-transcript") === true;
  const queue = await readJson(queuePath);
  const eligible = (queue.sources || []).filter((item) => item.status === "discovered" || (retryNeedsTranscript && item.status === "needs-transcript"));
  eligible.sort((a, b) => (a.published_at || a.discovered_at || "").localeCompare(b.published_at || b.discovered_at || ""));
  const selected = eligible.slice(0, max);
  const results = [];

  for (const item of selected) {
    try {
      const result = await processVideo(item, channelPath);
      item.status = result.status;
      item.last_attempt_at = new Date().toISOString();
      if (result.reason) item.last_error = result.reason;
      else delete item.last_error;
      results.push(result);
    } catch (error) {
      const message = String(error.stderr || error.message || error).slice(0, 800);
      item.status = /not processable by policy/i.test(message) ? "blocked-policy" : "needs-transcript";
      item.last_attempt_at = new Date().toISOString();
      item.last_error = message;
      results.push({ status: item.status, video_id: item.video_id, reason: item.last_error });
    }
  }

  await writeJson(queuePath, queue);
  console.log(JSON.stringify({ selected: selected.map((item) => item.video_id), results }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
