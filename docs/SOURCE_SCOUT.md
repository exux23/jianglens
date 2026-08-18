# Source Scout Recovery Mode

This fork can discover new `@PredictiveHistory` uploads without depending on the original maintainer's private Google Drive or Colab state.

## What it fixes

The upstream pipeline only gives Virgil work after media artifacts have already been produced and synced into the repository. If the private Drive/Colab stage stops, the queue appears empty even when new Jiang videos exist.

`Source Scout` adds a public, no-secret front door:

1. Check the Predictive History videos tab with `yt-dlp` every six hours.
2. Compare returned video IDs with raw and canonical source state in the repository.
3. Record unseen uploads in `content/workflow/tasks/source-discovery.json`.
4. For ordinary Predictive History episodes, try to fetch English manual or automatic YouTube captions as `json3`.
5. Convert those captions into the `transcription.json` shape consumed by the existing importer.
6. Run `import-colab-video.mjs` and prepare agent transcript packets.
7. Compile and validate content before committing new source state to `main`.

The existing semantic-agent, episode-writing, QA, lens-distillation, and canon-promotion stages remain unchanged.

## Enable it on a fork

GitHub commonly disables scheduled workflows on newly created forks. Open the repository's **Actions** tab and enable workflows if GitHub shows an enable button.

Then open **Actions -> Source Scout -> Run workflow**. The default run bootstraps up to two newly discovered videos. Once the manual run succeeds, the schedule checks every six hours.

No secret is required when YouTube exposes English captions publicly.

### Optional YouTube cookies

If YouTube blocks metadata or captions from GitHub-hosted runners, add a repository Actions secret named `YOUTUBE_COOKIES_B64` containing a base64-encoded Netscape-format YouTube cookie file. The workflow writes it only to the runner's temporary directory and never commits it.

## Queue statuses

- `discovered`: upload exists but has not been converted into source artifacts.
- `artifacts-ready`: a raw `transcription.json` exists.
- `imported`: a canonical source directory exists under `content/sources/videos`.
- `needs-transcript`: public English captions were unavailable or the bootstrap failed.
- `blocked-policy`: the existing source-processing policy rejected the source as duplicate, skip, blocked, or archive-only.
- `manual-review`: reserved for sources that need a human decision before import.

## Interviews

Do not assume single-speaker captions for interviews. Interview-format appearances should continue through diarization or another speaker-aware transcript path before import. Source Scout currently targets the `@PredictiveHistory` channel's normal video feed.

## Local commands

```bash
python -m pip install -U yt-dlp
node ops/scripts/source-scout.mjs
node ops/scripts/bootstrap-youtube-source.mjs --max 2
node ops/scripts/compile-content.mjs
node ops/scripts/validate-content.mjs
```

To retry a source that previously had no usable captions:

```bash
node ops/scripts/bootstrap-youtube-source.mjs --max 2 --retry-needs-transcript
```

## Important boundary

This repair restores source discovery and mechanical source ingestion. It does not replace Virgil, Aristotle, Plato, or the semantic-agent steps. After a source reaches `imported`, the existing Jiang Lens agent workflow should continue from transcript packets into source-grounded analysis and public episode/lens updates.
