You are implementing Phase 3 of the yt-dlp-dj project: FastAPI Server & CLI.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-03-server-design.md`
2. Read the existing modules: `server/downloader.py`, `server/tagger.py`, `server/enrichment.py`, `server/models.py`, `server/config.py`
3. Read the project CLAUDE.md for conventions
4. Check what already exists — previous iterations may have made progress
5. Work through the success criteria, verifying each with tests
6. Run `uv run mypy server/` and `uv run pytest` to verify

## What To Build

- `server/app.py` — FastAPI application with /api/health, /api/preview, /api/download endpoints
- Wire up `server/cli.py` — connect the `serve` and `download` commands to real implementations
- `tests/test_app.py` — endpoint tests with httpx.AsyncClient, mocked modules
- `tests/test_cli.py` — CLI tests with typer.testing.CliRunner

## Success Criteria (from design doc)

- [ ] `yt-dlp-dj serve` starts server, responds to `/api/health`
- [ ] `POST /api/preview` returns enriched metadata for a valid URL
- [ ] `POST /api/download` downloads, tags, and saves a file
- [ ] `yt-dlp-dj download <URL>` works end-to-end from CLI
- [ ] CORS allows Chrome extension origin
- [ ] Error responses are structured JSON with appropriate status codes
- [ ] `uv run mypy server/` passes strict (entire server package)
- [ ] `uv run pytest` passes (all tests including previous phases)

## Completion

When ALL success criteria above pass, create the file `.claude/phase-3-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-3-complete` unless every single criterion genuinely passes.
