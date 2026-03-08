# Serato Tag Cues with Section Merging

> **Status**: Approved | **Created**: 2026-03-08

## Goal

Write analysis cue points directly into MP3 file tags using Serato's GEOB format so VirtualDJ reads them automatically on file scan. Merge consecutive same-type sections to produce clean, transition-focused cues. Remove the database.xml sync pipeline entirely.

## Background

The current system writes cue points to VDJ's `database.xml` via a manual "Sync to VDJ" step. This has three problems:

1. **Sync friction** — user must remember to click sync, and VDJ must be closed during sync
2. **Slot waste** — consecutive same-type sections (e.g., "Verse 1", "Verse 2", "Verse 3") consume multiple cue slots instead of marking one transition
3. **Cue limit** — hard cap of 8 cues misses important structural transitions

VDJ can read Serato-format cue points from ID3v2 GEOB frames (well-documented for MP3). The `getCuesFromTags` setting imports them on first scan. Once VDJ has its own cue data for a track, it stops reading from tags — so we must NOT also write to database.xml or it will override the tag-based cues.

The user has installed the "hotcues XT" VDJ plugin, which provides page-based hot cue navigation for more than 8 cues.

## Constraints

- **MP3 only** — Serato GEOB tags are well-documented for MP3 (ID3v2). M4A/MP4 support has known reliability issues (first 5 cues may not be read). Default download format changes from M4A to MP3.
- **No hard cue limit** — every merged section transition becomes a cue. Typical EDM tracks produce 8-12 cues after merging.
- **No database.xml writing** — VDJ ignores Serato tags once it has its own cue data, so writing to database.xml would sabotage the tag approach.

## Design

### 1. Section Merging (Analyzer Container)

New post-processing step in `analyzer/edm_reclassify.py`, replacing `_number_duplicates`:

**Merge rule:** Consecutive segments with the same base label are collapsed into a single segment. The merged segment uses the first occurrence's start time, the last occurrence's end time, and the sum of all bar counts.

Example:
```
Verse 1 (8 bars, 0.0-15.0s) + Verse 2 (7 bars, 15.0-28.0s) + Verse 3 (9 bars, 28.0-45.0s)
→ Verse (24 bars, 0.0-45.0s)
```

After merging, the existing `_number_duplicates` logic re-numbers any remaining duplicates (e.g., two non-consecutive "Drop" sections become "Drop 1" and "Drop 2").

Pipeline order:
```
allin1 → EDM reclassify → MERGE consecutive → number duplicates → bar count → beat snap
```

Note: merging must happen BEFORE bar counting and beat snapping, since merged segments have different boundaries. Actually — bar counting uses downbeats between start/end, and beat-snapping adjusts start/end to nearest downbeat. So the correct order is:

```
allin1 → EDM reclassify → MERGE consecutive → number duplicates → beat snap → bar count
```

The merge step operates on `ClassifiedSegment` objects (which have start/end from allin1). Beat-snapping then adjusts the merged boundaries. Bar counting uses the snapped boundaries.

### 2. Serato Tag Writing (Server Side)

New module: `server/serato_tags.py`

Uses the `serato-tools` Python library to write Serato Markers2 GEOB frames into MP3 files via mutagen.

**When:** Called inside the fire-and-forget `analyze_audio` flow, after the analyzer container returns results and before marking the track as "analyzed" in SQLite.

**What:** Each merged segment becomes a numbered hot cue:
- Position: segment start time (in the format serato-tools expects)
- Name: `"{Label} ({bars} bars)"` (e.g., `"Drop (16 bars)"`, `"Verse (24 bars)"`)
- Color: optional, can use a color map per label type (stretch goal)
- Index: sequential starting from 0

**Fallback:** If serato-tools fails or the file is not MP3, log a warning and continue — analysis results are still saved in `.meta.json`. The cue writing is best-effort, matching the existing graceful-failure pattern.

### 3. VDJ Sync Pipeline Removal

Remove entirely:
- `server/vdj.py` — VDJ database.xml writer
- `server/vdj_sync.py` — batch sync orchestrator
- `POST /api/sync-vdj` endpoint in `server/app.py`
- `SyncVdjResponse` model from `server/models.py`
- `requestSyncVdj()` from `extension/src/api.ts`
- `SyncVdjResponse` from `extension/src/types.ts`
- Sync button + footer from `extension/popup.html` and `extension/popup.css`
- `handleSyncVdj()` from `extension/src/popup.ts`
- `sync_vdj` import and endpoint wiring from `server/app.py`

Remove from `server/track_db.py`:
- `synced` status and `mark_synced` function
- `get_unsynced` function
- `synced_at` column (can keep if useful for auditing, but status never transitions to "synced")

Remove from `server/config.py`:
- `AnalysisConfig.vdj_database` field
- `AnalysisConfig.max_cues` field

### 4. Default Format Change

Extension: change default format from `"m4a"` to `"mp3"` in:
- `extension/src/popup.ts` — `getSelectedFormat()` fallback
- `extension/src/popup.ts` — `init()` stored format default
- Any hardcoded `"m4a"` references in storage defaults

### 5. Config Changes

```yaml
# Before
analysis:
  enabled: true
  vdj_database: ~/Library/Application Support/VirtualDJ/database.xml
  max_cues: 8
  analyzer_url: http://localhost:9235

# After
analysis:
  enabled: true
  analyzer_url: http://localhost:9235
```

## Dependencies

- `serato-tools` — Python library for writing Serato Markers2 GEOB frames. Uses mutagen internally (already a project dependency).

## Data Flow (After)

```
Download MP3 → Tag metadata → Insert SQLite ("downloaded")
                                    ↓
                              Fire-and-forget: analyze_audio()
                                    ↓
                              Analyzer container: allin1 → key → EDM reclassify
                                → merge consecutive → number duplicates
                                → beat snap → bar count
                                    ↓
                              Server: write .meta.json sidecar
                              Server: write Serato GEOB tags to MP3
                              Server: mark "analyzed" in SQLite
```

VDJ picks up cues automatically when the file is scanned/loaded. No manual sync step.

## Testing

- Unit test section merging: consecutive same-type → merged, non-consecutive same-type → kept separate and numbered
- Unit test Serato tag writing: verify GEOB frame is written with correct cue count and positions
- Integration test: full pipeline produces MP3 with readable Serato markers
- Verify VDJ reads cues by loading an output MP3

## Risks

| Risk | Mitigation |
|------|------------|
| `serato-tools` library instability | Pin version; wrap in try/except; `.meta.json` sidecar remains as backup |
| VDJ `getCuesFromTags` disabled | Document in README that this setting should be enabled (it's on by default) |
| MP3 quality vs M4A | MP3 at 320kbps is effectively transparent for DJ use |
| Future non-MP3 format needs | `.meta.json` sidecars preserved; database.xml writer can be re-added if needed |

## Sources

- [Serato GEOB tags documentation](https://github.com/Holzhaus/serato-tags)
- [serato-tools Python library](https://github.com/bvandercar-vt/serato-tools)
- [VDJ forum: cue points not stored in tags](https://virtualdj.com/forums/247117/VirtualDJ_Technical_Support/Name_of_the_id3tag_for_Cue_points_.html)
- [VDJ forum: importing Serato cue points](https://virtualdj.com/forums/164220/General_Discussion/Importing_Serato_Cue_points_to_VDJ_.html)
- [Mixxx wiki: VDJ cue storage format](https://github.com/mixxxdj/mixxx/wiki/Virtual-Dj-Cue-Storage-Format)
- [Mixxx wiki: Serato metadata format](https://github.com/mixxxdj/mixxx/wiki/Serato-Metadata-Format)
