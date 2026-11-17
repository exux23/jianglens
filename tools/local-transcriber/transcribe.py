#!/usr/bin/env python3
"""Local, resumable YouTube -> JiangLens transcript artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_PART = re.compile(r"^@?[A-Za-z0-9_.-]+$")


def channel_path(value):
    parts = value.split("/")
    if not value or not all(CHANNEL_PART.fullmatch(part) and part not in (".", "..") for part in parts):
        raise ValueError("Invalid channel folder (use @PredictiveHistory or Interviews/channel-id)")
    return Path(*parts)


def validate_source(source):
    p = Path(source).expanduser()
    if p.is_file():
        return p.resolve()
    u = urlparse(source)
    if u.scheme not in ("https", "http") or (u.hostname or "").lower() not in (
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"
    ):
        raise ValueError("Provide an existing local media file or a YouTube URL")
    return source


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def compact_metadata(info):
    raw_date = info.get("upload_date")
    published = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        if isinstance(raw_date, str) and re.fullmatch(r"\d{8}", raw_date)
        else None
    )
    if not published and info.get("timestamp"):
        published = datetime.fromtimestamp(int(info["timestamp"]), tz=timezone.utc).date().isoformat()
    return {
        "id": info.get("id"), "title": info.get("title"),
        "source_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info['id']}",
        "published_at": published, "duration_seconds": info.get("duration"),
        "channel": {
            "id": info.get("channel_id") or info.get("uploader_id"),
            "title": info.get("channel") or info.get("uploader"),
            "url": info.get("channel_url") or info.get("uploader_url"),
        },
        "metadata_source": "yt-dlp", "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def video_ids(url, limit, cookies):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "ignoreerrors": False}
    if limit:
        opts["playlistend"] = limit
    if cookies:
        opts["cookiefile"] = str(cookies)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("No videos found")
    entries = info.get("entries") if isinstance(info, dict) else None
    rows = list(entries) if entries is not None else [info]
    ids = []
    for item in rows:
        if not item:
            continue
        vid = item.get("id")
        if isinstance(vid, str) and VIDEO_ID.fullmatch(vid) and vid not in ids:
            ids.append(vid)
        else:
            print(f"Skipping unrecognized playlist entry: {str(vid)[:100]}", flush=True)
        if limit and len(ids) >= limit:
            break
    if not ids:
        raise RuntimeError("No valid YouTube video IDs found")
    return ids


def download(video_id, dest, cookies):
    import yt_dlp
    dest.mkdir(parents=True, exist_ok=True)
    audio = dest / "audio.wav"
    if audio.is_file() and (dest / "metadata.youtube.json").is_file():
        return
    opts = {
        "format": "bestaudio/best", "outtmpl": str(dest / "original.%(ext)s"),
        "noplaylist": True, "quiet": True, "no_warnings": True, "overwrites": True,
    }
    if cookies:
        opts["cookiefile"] = str(cookies)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        source = Path(ydl.prepare_filename(info))
    try:
        if not audio.is_file():
            temp = dest / "audio.tmp.wav"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temp)
            ], check=True)
            os.replace(temp, audio)
        atomic_json(dest / "metadata.youtube.json", compact_metadata(info))
    finally:
        source.unlink(missing_ok=True)
        (dest / "audio.tmp.wav").unlink(missing_ok=True)


def as_rows(annotation):
    if hasattr(annotation, "speaker_diarization"):
        annotation = annotation.speaker_diarization
    elif hasattr(annotation, "annotation"):
        annotation = annotation.annotation
    return [
        {"speaker": speaker, "start": round(seg.start, 3), "end": round(seg.end, 3), "track": str(track)}
        for seg, track, speaker in annotation.itertracks(yield_label=True)
    ]


def group_rows(rows, max_gap=3.0):
    # Keep overlap speaker segments separate, since a single speaker turn cannot represent overlap.
    ordered = sorted(rows, key=lambda r: (r["start"], r["end"]))
    grouped = []
    for r in ordered:
        if grouped and grouped[-1]["speaker"] == r["speaker"] and r["start"] - grouped[-1]["end"] <= max_gap:
            grouped[-1]["end"] = max(grouped[-1]["end"], r["end"])
        else:
            grouped.append({"speaker": r["speaker"], "start": r["start"], "end": r["end"], "track": str(len(grouped))})
    return grouped


def diarize(audio, dest, token, device):
    if not token:
        raise RuntimeError("Speaker identification requires HF_TOKEN and acceptance of both pyannote Hugging Face model conditions")
    import torch
    from pyannote.audio import Pipeline
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
    if pipe is None:
        raise RuntimeError("Could not load pyannote model. Accept model terms in Hugging Face and check HF_TOKEN")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but PyTorch cannot see the NVIDIA GPU")
    pipe.to(torch.device("cuda" if device == "cuda" or (device == "auto" and torch.cuda.is_available()) else "cpu"))
    output = pipe(str(audio))
    rows = as_rows(output)
    atomic_json(dest / "dump.json", {"diarization": rows, "embeddings": {}})
    atomic_json(dest / "grouped.json", {"diarization": group_rows(rows), "embeddings": {}})
    del output, pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def speaker_for(start, end, rows):
    overlaps = {}
    for r in rows:
        overlap = max(0.0, min(end, r["end"]) - max(start, r["start"]))
        overlaps[r["speaker"]] = overlaps.get(r["speaker"], 0.0) + overlap
    if not overlaps:
        return "UNKNOWN"
    winner = max(overlaps, key=overlaps.get)
    return winner if overlaps[winner] > 0 else "UNKNOWN"


def build_transcript(segments, info, speaker_rows=()):
    raw = []
    for s in segments:
        words = [
            {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
             "probability": round(w.probability, 3)}
            for w in (s.words or ())
        ]
        raw.append({"start": round(s.start, 3), "end": round(s.end, 3),
                    "text": s.text.strip(), "speaker": speaker_for(s.start, s.end, speaker_rows), "words": words})
    turns = []
    for seg in raw:
        basic = {k: seg[k] for k in ("start", "end", "text")}
        if turns and turns[-1]["speaker"] == seg["speaker"]:
            turns[-1]["end"] = seg["end"]
            turns[-1]["text"] += " " + seg["text"]
            turns[-1]["words"].extend(seg["words"])
            turns[-1]["segments"].append(basic)
        else:
            turns.append({**seg, "words": list(seg["words"]), "segments": [basic]})
    return {"language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 3), "turns": turns,
            "text": " ".join(t["text"] for t in turns)}


def transcribe(audio, dest, model_name, device, speaker_rows):
    from faster_whisper import WhisperModel
    from ctranslate2 import get_cuda_device_count
    if device == "cuda" and get_cuda_device_count() <= 0:
        raise RuntimeError("CUDA requested but CTranslate2 cannot see a supported NVIDIA GPU")
    chosen = ("cuda" if get_cuda_device_count() > 0 else "cpu") if device == "auto" else device
    # INT8 cuts VRAM use on 8 GB GPUs while retaining the large-v3 weights.
    compute_type = "int8_float16" if chosen == "cuda" else "int8"
    model = WhisperModel(model_name, device=chosen, compute_type=compute_type)
    segments, info = model.transcribe(
        str(audio), word_timestamps=True, beam_size=5, best_of=5,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        condition_on_previous_text=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    result = build_transcript(segments, info, speaker_rows)
    atomic_json(dest / "transcription.json", result)
    return result


def process(video_id, channel, root, args):
    folder = root / channel / video_id
    if (folder / "transcription.json").is_file() and not args.force and (
        not args.diarize or (folder / "grouped.json").is_file()
    ):
        print(f"[skip] {video_id}: transcript already exists", flush=True)
        return
    print(f"[audio] {video_id}", flush=True)
    download(video_id, folder, args.cookies)
    audio = folder / "audio.wav"
    if args.diarize and (args.force or not (folder / "grouped.json").is_file()):
        print(f"[speakers] {video_id}", flush=True)
        diarize(audio, folder, os.environ.get("HF_TOKEN"), args.device)
    rows = json.loads((folder / "grouped.json").read_text(encoding="utf-8"))["diarization"] if args.diarize else []
    print(f"[transcribe] {video_id} ({args.model})", flush=True)
    result = transcribe(audio, folder, args.model, args.device, rows)
    print(f"[done] {video_id}: {len(result['turns'])} turns", flush=True)


def process_local(source, channel, root, args):
    video_id = "local-" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
    folder = root / channel / video_id
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "audio.wav"
    if not audio.exists():
        temp = folder / "audio.tmp.wav"
        try:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temp)], check=True)
            os.replace(temp, audio)
        finally:
            temp.unlink(missing_ok=True)
    if (folder / "transcription.json").exists() and not args.force and (
        not args.diarize or (folder / "grouped.json").exists()
    ):
        print(f"[skip] {source.name}: transcript already exists", flush=True)
        return
    if args.diarize and (args.force or not (folder / "grouped.json").exists()):
        diarize(audio, folder, os.environ.get("HF_TOKEN"), args.device)
    rows = json.loads((folder / "grouped.json").read_text())["diarization"] if args.diarize else []
    result = transcribe(audio, folder, args.model, args.device, rows)
    print(f"[done] {source.name}: {len(result['turns'])} turns in {folder}", flush=True)


def default_output():
    repo = Path(__file__).resolve().parents[2]
    return repo / "content/sources/raw/youtube" if (repo / "ops/scripts/import-colab-video.mjs").is_file() else Path(__file__).resolve().parent / "output"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Locally transcribe YouTube videos into JiangLens-compatible artifacts")
    parser.add_argument("source", help="YouTube video, playlist or channel URL, or local media file")
    parser.add_argument("--channel", default="@PredictiveHistory", help="Output channel folder")
    parser.add_argument("--output", type=Path, default=default_output())
    parser.add_argument("--model", default="large-v3", choices=("large-v3", "medium", "small"))
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--diarize", action="store_true", help="Identify speakers using gated, free pyannote model")
    parser.add_argument("--cookies", type=Path, help="Local yt-dlp cookies.txt (never committed)")
    parser.add_argument("--max-videos", type=int, default=0, help="Maximum videos from a channel/playlist (0 = all)")
    parser.add_argument("--force", action="store_true", help="Re-run speaker identification and transcription")
    args = parser.parse_args(argv)
    if args.max_videos < 0:
        parser.error("--max-videos must be >= 0")
    try:
        source = validate_source(args.source)
        channel = channel_path(args.channel)
        if args.cookies and not args.cookies.is_file():
            raise ValueError("--cookies file does not exist")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Install FFmpeg and put it on PATH")
        root = args.output.expanduser().resolve()
        if isinstance(source, Path):
            process_local(source, channel, root, args)
        else:
            ids = video_ids(source, args.max_videos, args.cookies)
            print(f"Found {len(ids)} video(s)", flush=True)
            failed = []
            for index, vid in enumerate(ids, 1):
                print(f"[{index}/{len(ids)}] {vid}", flush=True)
                try:
                    process(vid, channel, root, args)
                except Exception as exc:
                    failed.append(vid)
                    print(f"[error] {vid}: {exc}", file=sys.stderr, flush=True)
            if failed:
                raise RuntimeError(f"{len(failed)} video(s) failed: {', '.join(failed)}")
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
