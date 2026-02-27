You are implementing Phase 2b of the dj-kompanion project: Tagger Module.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-02b-tagger-design.md`
2. Read `server/models.py` for the Pydantic models (created in Phase 1)
3. Read the project CLAUDE.md for conventions
4. Check what already exists — previous iterations may have made progress
5. Work through the success criteria, verifying each with tests
6. Run `uv run mypy server/tagger.py` and `uv run pytest tests/test_tagger.py` to verify

## What To Build

- `server/tagger.py` — mutagen-based tagging with `tag_file()` and `read_tags()` functions
- `tests/test_tagger.py` — unit tests with real small audio files or mocked mutagen

## Success Criteria (from design doc)

- [ ] Tags written correctly for MP3, FLAC, M4A, OGG formats
- [ ] Tags readable by mutagen after writing (round-trip test)
- [ ] File renamed to `{Artist} - {Title}.{ext}` pattern
- [ ] Handles None/missing fields gracefully (skips them)
- [ ] Filename sanitization handles edge cases
- [ ] `uv run mypy server/tagger.py` passes strict
- [ ] `uv run pytest tests/test_tagger.py` passes

## Completion

When ALL success criteria above pass, create the file `.claude/phase-2b-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-2b-complete` unless every single criterion genuinely passes.
