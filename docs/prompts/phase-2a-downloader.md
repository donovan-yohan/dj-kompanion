You are implementing Phase 2a of the yt-dlp-dj project: Downloader Module.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-02a-downloader-design.md`
2. Read `server/models.py` for the Pydantic models (created in Phase 1)
3. Read the project CLAUDE.md for conventions
4. Check what already exists — previous iterations may have made progress
5. Work through the success criteria, verifying each with tests
6. Run `uv run mypy server/downloader.py` and `uv run pytest tests/test_downloader.py` to verify

## What To Build

- `server/downloader.py` — yt-dlp wrapper with `extract_metadata()` and `download_audio()` functions
- `tests/test_downloader.py` — unit tests with mocked yt-dlp

## Success Criteria (from design doc)

- [ ] `extract_metadata(url)` returns structured `RawMetadata` for YouTube, SoundCloud, Bandcamp URLs
- [ ] `download_audio(url, ...)` downloads audio and returns file path
- [ ] Format conversion works (mp3, flac, m4a)
- [ ] Errors are caught and raised as `DownloadError` with clear messages
- [ ] `uv run mypy server/downloader.py` passes strict
- [ ] `uv run pytest tests/test_downloader.py` passes

## Completion

When ALL success criteria above pass, create the file `.claude/phase-2a-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-2a-complete` unless every single criterion genuinely passes.
