You are implementing Phase 2c of the yt-dlp-dj project: LLM Enrichment Module.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-02c-enrichment-design.md`
2. Read `server/models.py` for the Pydantic models (created in Phase 1)
3. Read the project CLAUDE.md for conventions
4. Check what already exists — previous iterations may have made progress
5. Work through the success criteria, verifying each with tests
6. Run `uv run mypy server/enrichment.py` and `uv run pytest tests/test_enrichment.py` to verify

## What To Build

- `server/enrichment.py` — LLM enrichment via `claude` CLI with `enrich_metadata()`, `basic_enrich()`, and `is_claude_available()` functions
- `tests/test_enrichment.py` — unit tests with mocked subprocess.run

## Success Criteria (from design doc)

- [ ] `enrich_metadata()` returns valid `EnrichedMetadata` when claude succeeds
- [ ] `enrich_metadata()` falls back to `basic_enrich()` when claude is unavailable
- [ ] `basic_enrich()` correctly splits common YouTube title formats
- [ ] 30-second timeout prevents hanging
- [ ] `uv run mypy server/enrichment.py` passes strict
- [ ] `uv run pytest tests/test_enrichment.py` passes

## Completion

When ALL success criteria above pass, create the file `.claude/phase-2c-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-2c-complete` unless every single criterion genuinely passes.
