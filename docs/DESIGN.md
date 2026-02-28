# Design

dj-kompanion prioritizes simplicity and personal convenience. It is a single-user local tool, not a production web service. Design decisions favor "works on my machine" reliability over scalability or multi-user concerns.

## Current State

- Core download + tagging pipeline functional
- Chrome extension + local server architecture implemented
- LLM-assisted metadata enrichment operational, deferred to download phase for zero wall-clock overhead
- ML audio post-processing implemented: 5-stage pipeline (allin1 structure, essentia key, EDM reclassify, bar count, beat-snap) + VDJ cue writer
- allin1 runs in a separate Docker container (NATTEN has no macOS wheels); main server stays native for Claude CLI
- Analysis microservice on port 9235; main server proxies /api/analyze calls and handles VDJ write
- Metadata API enrichment complete: MusicBrainz + Last.fm search with LLM disambiguation at download time

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
| allin1 + essentia for audio analysis | ML-based structure detection (allin1) + EDM-tuned key detection (essentia bgate) + custom EDM reclassifier | Audio post-processing design |
| VDJ database.xml for cue points | Analysis results written to VDJ sidecar XML, not embedded tags; named hot cues with bar counts | Audio post-processing design |
| Post-download analysis trigger | Analysis runs as background task after download+tagging; non-blocking; best-effort | Audio post-processing design |
| Docker for allin1 on macOS ARM64 | NATTEN (required by allin1) has no macOS wheels — CUDA only; Docker container planned for production use | Audio post-processing implementation |
| Graceful fallback on analysis failure | Key detection, stem energy, VDJ write each catch exceptions independently; analysis failure is non-critical | Audio post-processing implementation |
| Analyzer as separate Docker microservice | Only analysis needs Linux; main server stays native for Claude CLI. Volume-mount audio dir read-only, return JSON results, main server writes VDJ | Dockerized analyzer design |
| Search-then-Select for metadata | MusicBrainz + Last.fm provide candidates; LLM picks best match using YouTube context. APIs for structured data, LLM for reasoning. | Metadata API enrichment design |
| LLM as disambiguator, not guesser | LLM decides match quality (high/medium/low/no_match). No auto-pick from API without LLM validation. | Metadata API enrichment design |
| Enrichment source tracking | `enrichment_source` field tracks provenance: api+claude, claude, basic, none. Frontend can display this. | Metadata API enrichment design |

## Deep Docs

| Document | Purpose |
|----------|---------|
| `design-docs/core-beliefs.md` | Agent-first operating principles |
| `design-docs/2026-02-26-yt-dlp-dj-design.md` | Monolithic reference design |
| `design-docs/2026-02-26-01-*` through `04-*` | Per-phase focused design docs |
| `design-docs/2026-02-27-audio-post-processing-design.md` | ML audio analysis pipeline design |
| `design-docs/2026-02-28-metadata-api-enrichment-design.md` | MusicBrainz + Last.fm API lookup with LLM disambiguation |

## See Also

- [Architecture](ARCHITECTURE.md) — module boundaries and invariants
- [Plans](PLANS.md) — active and completed execution plans
