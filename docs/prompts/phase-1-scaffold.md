You are implementing Phase 1 of the dj-kompanion project: Project Scaffold & Config.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-01-project-scaffold-design.md`
2. Read the project CLAUDE.md for context
3. Check what already exists — previous iterations may have made progress
4. Work through the success criteria in the design doc, one by one
5. After each piece of work, verify it (run mypy, ruff, pytest, npm typecheck, etc.)
6. If something fails, fix it before moving on

## Success Criteria (from design doc)

- [ ] `git init` and `.gitignore` set up
- [ ] `uv sync` installs all dependencies
- [ ] `uv run dj-kompanion --help` shows CLI help
- [ ] `uv run dj-kompanion config` creates default config file
- [ ] `uv run mypy server/` passes with strict mode
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` runs (empty test suite, 0 tests)
- [ ] `cd extension && npm install && npm run typecheck` passes
- [ ] `cd extension && npm run lint && npm run format` passes

## Completion

When ALL success criteria above pass, create the file `.claude/phase-1-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-1-complete` unless every single criterion genuinely passes.
