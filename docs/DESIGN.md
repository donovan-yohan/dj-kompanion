# Design

dj-kompanion prioritizes simplicity and personal convenience. It is a single-user local tool, not a production web service. Design decisions favor "works on my machine" reliability over scalability or multi-user concerns.

## Current State

- Core download + tagging pipeline functional
- Chrome extension + local server architecture implemented
- LLM-assisted metadata enrichment operational, deferred to download phase for zero wall-clock overhead

## Key Decisions

| Decision | Rationale | Source |
|----------|-----------|--------|
| Chrome extension + local server | Browser context needed for URL capture; yt-dlp requires local CLI access | Initial brainstorm |
| Virtual DJ metadata format | Primary DJ software target for the user | Initial brainstorm |
| Optional LLM integration | Metadata sanitization and song structure marking are nice-to-haves | Initial brainstorm |
| Python (FastAPI) backend | yt-dlp as library, mutagen for tagging, future audio analysis ecosystem | Initial brainstorm |
| claude CLI for LLM | No separate API key, uses existing Claude Code auth | Initial brainstorm |
| 6-piece decomposition | Independent modules enable parallel development with fresh sessions | Decomposition brainstorm |
| Deferred enrichment | Preview uses basic_enrich (instant); download runs Claude in parallel with yt-dlp | Deferred enrichment plan |
| User-edit tracking | Extension tracks which fields user modified; merge preserves user edits over Claude | Deferred enrichment plan |
| Three-way merge | Priority: user-edited > Claude non-null > basic fallback; comment always from user | Deferred enrichment plan |
| Download queue in extension | Service worker processes downloads in background; chrome.storage.local is source of truth; popup is stateless renderer | Download queue design |

## Deep Docs

| Document | Purpose |
|----------|---------|
| `design-docs/core-beliefs.md` | Agent-first operating principles |
| `design-docs/2026-02-26-yt-dlp-dj-design.md` | Monolithic reference design |
| `design-docs/2026-02-26-01-*` through `04-*` | Per-phase focused design docs |

## See Also

- [Architecture](ARCHITECTURE.md) — module boundaries and invariants
- [Plans](PLANS.md) — active and completed execution plans
