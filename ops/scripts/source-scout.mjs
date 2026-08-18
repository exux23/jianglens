#!/usr/bin/env node
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function parseArgs(argv) {
  const args = new Map();
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) throw new Error(`Unexpected positional argument: ${arg}`);
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args.set(key, true);
    } else {
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

function normalizeDate(value) {
  if (!value) return null;
  const raw = String(value);
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  return null;
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

async function collectRawIds(root, depth = 0, maxDepth = 5, ids = new Set()) {
  let entries;
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return ids;
    throw error;
  }

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const candidate = path.join(root, entry.name);
    if (/^[A-Za-z0-9_-]{11}$/.test(entry.name) && await exists(path.join(candidate, "transcription.json"))) {
      ids.add(entry.name.toLowerCase());
    }
    if (depth < maxDepth) await collectRawIds(candidate, depth + 1, maxDepth, ids);
  }
  return ids;
}

async function collectCanonicalIds(root) {
  const ids = new Set();
  let entries = [];
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return ids;
    throw error;
  }

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const match = entry.name.match(/([a-z0-9_-]{11})$/i);
    if (match) ids.add(match[1].toLowerCase());
  }
  return ids;
}

function ytDlpArgs(channelUrl, limit, cookiesFile) {
  const args = [
    "--flat-playlist",
    "--playlist-end", String(limit),
    "--dump-single-json",
    "--no-warnings",
  ];
  if (cookiesFile) args.push("--cookies", cookiesFile);
  args.push(channelUrl);
  return args;
}

function equivalentItem(a, b) {
  return JSON.stringify({
    video_id: a?.video_id ?? null,
    title: a?.title ?? null,
    url: a?.url ?? null,
    published_at: a?.published_at ?? null,
    status: a?.status ?? null,
  }) === JSON.stringify({
    video_id: b?.video_id ?? null,
    title: b?.title ?? null,
    url: b?.url ?? null,
    published_at: b?.published_at ?? null,
    status: b?.status ?? null,
  });
}

function ageHours(item, nowMs) {
  const anchor = item.published_at ? `${item.published_at}T00:00:00Z` : item.discovered_at;
  const parsed = Date.parse(anchor || "");
  return Number.isFinite(parsed) ? (nowMs - parsed) / 3_600_000 : 0;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const channelUrl = option(args, "channel-url", "https://www.youtube.com/@PredictiveHistory/videos");
  const channelPath = option(args, "channel-path", "@PredictiveHistory");
  const outputPath = path.resolve(repoRoot, option(args, "output", "content/workflow/tasks/source-discovery.json"));
  const limit = Math.max(1, Number(option(args, "limit", "100")) || 100);
  const staleHours = Math.max(1, Number(option(args, "stale-hours", "24")) || 24);
  const cookiesFile = process.env.JIANGLENS_YOUTUBE_COOKIES_FILE || process.env.YOUTUBE_COOKIES_FILE || process.env.YTDLP_COOKIES_FILE || null;

  const { stdout } = await execFileAsync("yt-dlp", ytDlpArgs(channelUrl, limit, cookiesFile), {
    cwd: repoRoot,
    maxBuffer: 64 * 1024 * 1024,
  });
  const playlist = JSON.parse(stdout);
  const entries = Array.isArray(playlist.entries) ? playlist.entries.filter((entry) => entry?.id) : [];
  const rawIds = await collectRawIds(path.join(repoRoot, "content/sources/raw/youtube"));
  const canonicalIds = await collectCanonicalIds(path.join(repoRoot, "content/sources/videos"));
  const existing = await readJson(outputPath, {
    version: 1,
    channel: { path: channelPath, url: channelUrl },
    sources: [],
  });
  const previousById = new Map((existing.sources || []).map((item) => [String(item.video_id), item]));
  const now = new Date();
  const nowIso = now.toISOString();
  const nextSources = [];
  const newIds = [];
  let changed = false;

  for (const entry of entries) {
    const videoId = String(entry.id);
    const key = videoId.toLowerCase();
    const previous = previousById.get(videoId);
    let status = canonicalIds.has(key) ? "imported" : rawIds.has(key) ? "artifacts-ready" : "discovered";
    if (status === "discovered" && ["needs-transcript", "blocked-policy", "manual-review"].includes(previous?.status)) status = previous.status;

    const item = {
      video_id: videoId,
      title: entry.title || previous?.title || null,
      url: entry.webpage_url || (typeof entry.url === "string" && entry.url.startsWith("http") ? entry.url : `https://www.youtube.com/watch?v=${videoId}`),
      published_at: normalizeDate(entry.upload_date) || previous?.published_at || null,
      discovered_at: previous?.discovered_at || nowIso,
      status,
    };

    if (!previous) newIds.push(videoId);
    if (!previous || !equivalentItem(previous, item)) changed = true;
    nextSources.push(item);
    previousById.delete(videoId);
  }

  for (const orphaned of previousById.values()) nextSources.push(orphaned);

  nextSources.sort((a, b) => {
    const aDate = a.published_at || a.discovered_at || "";
    const bDate = b.published_at || b.discovered_at || "";
    return bDate.localeCompare(aDate);
  });

  const stale = nextSources.filter((item) => ["discovered", "needs-transcript"].includes(item.status) && ageHours(item, now.getTime()) >= staleHours);
  const result = {
    version: 1,
    channel: { path: channelPath, url: channelUrl },
    last_discovery_change_at: changed ? nowIso : existing.last_discovery_change_at || null,
    sources: nextSources,
  };

  if (changed || !await exists(outputPath)) {
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  }

  const counts = nextSources.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] || 0) + 1;
    return acc;
  }, {});

  console.log(JSON.stringify({
    changed,
    discovered_new: newIds,
    stale: stale.map((item) => item.video_id),
    counts,
    output: path.relative(repoRoot, outputPath),
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
