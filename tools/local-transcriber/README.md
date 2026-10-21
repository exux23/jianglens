# JiangLens Local Transcriber

Free local replacement for JiangLens's Google Colab transcription stage. Built following [Ponytail's minimal-code approach](https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail/SKILL.md). Ponytail is a development skill, not a runtime dependency.

Uses yt-dlp for YouTube audio, FFmpeg for 16 kHz mono WAV, Faster-Whisper large-v3 for word-timestamp transcription, and optional pyannote speaker-diarization-3.1 for speaker identification. Writes the original JiangLens-compatible audio.wav, metadata.youtube.json, dump.json, grouped.json and transcription.json files. Everything runs on your PC, with no paid API or cloud processing. Internet is required to download YouTube audio and model weights.

## Install on Windows 11 with WSL2 Ubuntu

Install WSL2, Ubuntu and current NVIDIA Windows drivers. In Ubuntu, use Python 3.11 or 3.12 and run these commands from the JiangLens repo root:

    sudo apt update && sudo apt install -y python3-venv python3-tk ffmpeg
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r tools/local-transcriber/requirements.txt

For local speaker identification, also install a compatible CUDA-enabled PyTorch distribution (see PyTorch's installation selector) and:

    pip install pyannote.audio==4.0.3

Faster-Whisper GPU execution needs CUDA 12 cuBLAS and cuDNN 9 libraries (https://github.com/SYSTRAN/faster-whisper#gpu). On Linux, one installation method is:

    pip install nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'

Then put the directories containing those libraries on LD_LIBRARY_PATH before starting Python. If CUDA is unavailable, specify --device cpu. Large-v3 on the RTX 3060 Ti uses INT8 quantization to reduce VRAM use. Hardware compatibility has not been verified on your PC.

## Run

Run one video:

    python tools/local-transcriber/transcribe.py 'https://www.youtube.com/watch?v=VIDEO_ID' --channel @PredictiveHistory

Run a channel or playlist (start with 10 for testing):

    python tools/local-transcriber/transcribe.py 'https://www.youtube.com/@PredictiveHistory/videos' --max-videos 10

Run a local audio or video file:

    python tools/local-transcriber/transcribe.py '/path/to/video.mp4' --channel Local

Launch the desktop interface (requires Tkinter and WSLg):

    python tools/local-transcriber/gui.py

Outputs default to content/sources/raw/youtube/<channel>/<video-id>/ under JiangLens. Already completed videos are skipped. Use --force to redo transcription or --max-videos 0 to process an entire playlist. Options include --device auto|cuda|cpu, --model large-v3|medium|small, --output PATH, --channel NAME, --cookies PATH and --diarize.

## Speakers

Accept the free model conditions at:

- https://huggingface.co/pyannote/segmentation-3.0
- https://huggingface.co/pyannote/speaker-diarization-3.1

Create a free read token at https://huggingface.co/settings/tokens, set the HF_TOKEN environment variable locally, and pass --diarize. Never commit access tokens or cookies. Speaker IDs are model estimates and need review for ambiguous dialogue.

## Import into original JiangLens

When working in the original JiangLens repo, run:

    node ops/scripts/import-colab-video.mjs --video-id VIDEO_ID --channel @PredictiveHistory

This uses the existing importer to generate transcript.clean.jsonl, transcript.clean.md and timestamps. Local media files are not supported by that YouTube-specific importer without an adapter. Downstream AI interpretation and site generation are separate from this transcription tool.

## Test

    cd tools/local-transcriber
    python -m unittest discover -v

The tests cover path security, transcript layout, speaker timing, metadata and resumption. They do not need GPU/network/model downloads. Test one real video and the importer on your machine before batch processing.

Only download material you are authorized to access. yt-dlp can fail on private, geo-restricted or changed YouTube video formats.
