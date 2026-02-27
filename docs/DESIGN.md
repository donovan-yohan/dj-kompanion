# Design

yt-dlp-dj prioritizes simplicity and personal convenience. It is a single-user local tool, not a production web service. Design decisions favor "works on my machine" reliability over scalability or multi-user concerns.

## Current State

- Project is in initial design phase, no code written yet
- Chrome extension + local server architecture selected as primary approach
- LLM-assisted metadata enrichment is a stretch goal, not a core requirement

## Key Decisions

| Decision | Rationale | Source |
|----------|-----------|--------|
| Chrome extension + local server | Browser context needed for URL capture; yt-dlp requires local CLI access | Initial brainstorm |
| Virtual DJ metadata format | Primary DJ software target for the user | Initial brainstorm |
| Optional LLM integration | Metadata sanitization and song structure marking are nice-to-haves | Initial brainstorm |
| Python (FastAPI) backend | yt-dlp as library, mutagen for tagging, future audio analysis ecosystem | Initial brainstorm |
| claude CLI for LLM | No separate API key, uses existing Claude Code auth | Initial brainstorm |
| 6-piece decomposition | Independent modules enable parallel development with fresh sessions | Decomposition brainstorm |

## Deep Docs

| Document | Purpose |
|----------|---------|
| `design-docs/core-beliefs.md` | Agent-first operating principles |
| `design-docs/2026-02-26-yt-dlp-dj-design.md` | Monolithic reference design |
| `design-docs/2026-02-26-01-*` through `04-*` | Per-phase focused design docs |

## See Also

- [Architecture](ARCHITECTURE.md) — module boundaries and invariants
- [Plans](PLANS.md) — active and completed execution plans
