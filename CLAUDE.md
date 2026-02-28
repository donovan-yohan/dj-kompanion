# dj-kompanion

A personal convenience tool wrapping yt-dlp with a Chrome extension and local server for one-click audio/video downloading with DJ-ready metadata (Virtual DJ format). Optional LLM-assisted metadata enrichment.

## Quick Reference

| Action | Command |
|--------|---------|
| Start analyzer | `docker compose up -d` |
| Server dev | `uv run uvicorn server.app:app --reload --port 9234` |
| Type check (Python) | `uv run mypy server/` |
| Lint + format (Python) | `uv run ruff check . && uv run ruff format .` |
| Test | `uv run pytest` |
| Build extension | `cd extension && npm run build` |
| Lint + format (Extension) | `cd extension && npm run lint && npm run format` |
| Type check (Extension) | `cd extension && npx tsc --noEmit` |
| Server logs | `~/.config/dj-kompanion/logs/server.log` |

## Documentation Map

| Category | Path | When to look here |
|----------|------|-------------------|
| Architecture | `docs/ARCHITECTURE.md` | Understanding module boundaries, package layering, where code lives |
| Design | `docs/DESIGN.md` | Design principles, core beliefs, pattern decisions |
| Plans | `docs/PLANS.md` | Active work, completed plans, tech debt tracking |
| Design Docs | `docs/design-docs/` | Deep dives on specific features or design topics |
| References | `docs/references/` | External library docs, API specs, llms.txt files |

## Key Patterns

- Analyzer runs in Docker container (allin1/NATTEN need Linux) — main server calls it over HTTP
- Python server is the brain — all yt-dlp, tagging, and LLM logic lives there
- Chrome extension is a thin UI — TypeScript, no heavy framework
- LLM enrichment via `claude -p --model haiku` — no separate API key needed
- All metadata written to file tags via mutagen — file is the source of truth
- Pydantic models on server, TypeScript interfaces on extension — keep in sync manually
- `mypy --strict` for Python, `tsconfig strict: true` for TypeScript — no untyped code

## Workflow

> brainstorm → plan → orchestrate → complete

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `/harness:brainstorm` | Design through collaborative dialogue |
| 2 | `/harness:plan` | Create living implementation plan |
| 3 | `/harness:orchestrate` | Execute with agent teams + micro-reflects |
| 4 | `/harness:complete` | Reflect, review, and create PR |
