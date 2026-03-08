# Design

dj-kompanion prioritizes simplicity and personal convenience. It is a single-user local tool, not a production web service. Design decisions favor "works on my machine" reliability over scalability or multi-user concerns.

## Current State

- Core download + tagging pipeline functional
- Chrome extension + local server architecture implemented
- LLM-assisted metadata enrichment operational, deferred to download phase for zero wall-clock overhead
- ML audio post-processing implemented: 5-stage pipeline (allin1 structure, essentia key, EDM reclassify, bar count, beat-snap) + VDJ cue writer
- allin1 runs in a separate Docker container (NATTEN has no macOS wheels); main server stays native for Claude CLI
- Analysis microservice on port 9235; results stored as sidecar `.meta.json` files, VDJ sync is a separate manual step
- SQLite tracks per-song status: downloaded → analyzing → analyzed → synced
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
| Decoupled analysis from VDJ | Analysis writes sidecar `.meta.json` files; VDJ database.xml only touched during explicit sync step. Prevents corruption from concurrent writes. | Decoupled analysis design |
| SQLite for track status | Lean tracker (`tracks.db`) for download→analysis→sync pipeline. Single table, status column as state machine. | Decoupled analysis design |
| VDJ safety check on sync | Sync refuses to write if VDJ process is running. Only writes to songs VDJ has already scanned. | Decoupled analysis design |
| Serato GEOB tags for cues | Write cue points as Serato Markers2 GEOB frames in MP3 files. VDJ reads them automatically on scan via `getCuesFromTags`. Replaces database.xml sync entirely. | Serato tag cues design |
| MP3 as default format | Serato GEOB tags are well-documented and reliable for MP3; M4A has known issues. MP3 320kbps is transparent for DJ use. | Serato tag cues design |
| Section merging over numbering | Consecutive same-type sections merged into one cue (summed bars) instead of numbered separately. Produces transition-focused cues. | Serato tag cues design |
| No hard cue limit | Every merged section transition becomes a cue. hotcues XT plugin provides page navigation in VDJ. | Serato tag cues design |

## Deep Docs

| Document | Purpose |
|----------|---------|
| `design-docs/core-beliefs.md` | Agent-first operating principles |
| `design-docs/2026-02-26-yt-dlp-dj-design.md` | Monolithic reference design |
| `design-docs/2026-02-26-01-*` through `04-*` | Per-phase focused design docs |
| `design-docs/2026-02-27-audio-post-processing-design.md` | ML audio analysis pipeline design |
| `design-docs/2026-02-28-metadata-api-enrichment-design.md` | MusicBrainz + Last.fm API lookup with LLM disambiguation |
| `design-docs/2026-03-08-decoupled-analysis-vdj-sync-design.md` | Decoupled analysis with sidecar JSON + manual VDJ sync |
| `design-docs/2026-03-08-serato-tag-cues-design.md` | Serato GEOB cue tags with section merging |

## See Also

- [Architecture](ARCHITECTURE.md) — module boundaries and invariants
- [Plans](PLANS.md) — active and completed execution plans
