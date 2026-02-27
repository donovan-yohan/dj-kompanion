# Tagger Module — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 2b (Parallel Module)
**Parent Design:** `2026-02-26-dj-kompanion-design.md`
**Depends On:** Phase 1 (Project Scaffold) must be complete

## Context

dj-kompanion is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the tagger module — the mutagen-based component that embeds metadata into audio files in a format Virtual DJ can read.

## Goal

A `server/tagger.py` module that:
- Takes an audio file path and an `EnrichedMetadata` object
- Detects the audio format (MP3, FLAC, M4A, OGG, WAV)
- Writes all metadata fields as the appropriate tag type for that format
- Renames the file to match `{Artist} - {Title}.{ext}` pattern

## Module Interface

```python
# server/tagger.py

def tag_file(filepath: Path, metadata: EnrichedMetadata) -> Path:
    """Embed metadata tags into audio file.
    Returns the (possibly renamed) file path.
    Raises TaggingError if the format is unsupported or file is corrupt."""

def read_tags(filepath: Path) -> EnrichedMetadata:
    """Read existing tags from an audio file.
    Returns an EnrichedMetadata with whatever fields are present."""
```

## Tag Mapping

Each audio format uses different tag standards. mutagen handles the abstraction, but we need to know which tag keys to write:

| Field | MP3 (ID3v2.4) | FLAC (Vorbis) | M4A (MP4) | OGG (Vorbis) |
|-------|---------------|---------------|-----------|--------------|
| Artist | TPE1 | ARTIST | \xa9ART | ARTIST |
| Title | TIT2 | TITLE | \xa9nam | TITLE |
| Genre | TCON | GENRE | \xa9gen | GENRE |
| Year | TDRC | DATE | \xa9day | DATE |
| Label | TPUB | LABEL | ----:com.apple.iTunes:LABEL | LABEL |
| Energy | TXXX:ENERGY | ENERGY | ----:com.apple.iTunes:ENERGY | ENERGY |
| BPM | TBPM | BPM | tmpo | BPM |
| Key | TKEY | INITIALKEY | ----:com.apple.iTunes:initialkey | INITIALKEY |
| Comment | COMM | COMMENT | \xa9cmt | COMMENT |

## Implementation Approach

Use mutagen's format-specific classes:

```python
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.id3 import TPE1, TIT2, TCON, TDRC, TPUB, TBPM, TKEY, COMM, TXXX
```

Detect format by file extension (mutagen also does magic byte detection as fallback). Dispatch to a format-specific tagger function.

## Filename Sanitization

After tagging, rename file to: `{Artist} - {Title}.{ext}`

Sanitization rules:
- Strip characters: `/ \ : * ? " < > |`
- Collapse multiple spaces to single space
- Trim leading/trailing whitespace
- Truncate to 200 characters (filesystem safety)
- If artist or title is empty, fall back to original filename

## Virtual DJ Compatibility

VDJ natively reads these tags on import:
- Artist, Title, Genre, Year, BPM, Key, Comment — all populated automatically
- Energy, Label — written to file tags for portability but VDJ stores these in its own `database.xml`. User may need to set these manually in VDJ.

The `comment` field is auto-filled with the source URL, which is useful for finding the original source later.

## Error Handling

```python
class TaggingError(Exception):
    """Raised when tagging fails."""
    def __init__(self, message: str, filepath: Path):
        self.message = message
        self.filepath = filepath
```

Failure modes:
- Unsupported format (e.g., WAV has limited tag support — write what we can)
- Corrupt file (mutagen raises `MutagenError`)
- Permission error on file write

## Testing Strategy

- Create small test audio files (a few seconds of silence) in MP3, FLAC, M4A, OGG formats
- Write tags, then read them back and verify
- Test with missing/None fields in metadata
- Test filename sanitization edge cases
- Test with real yt-dlp downloaded files if available

## Success Criteria

- [ ] Tags written correctly for MP3, FLAC, M4A, OGG formats
- [ ] Tags readable by mutagen after writing (round-trip test)
- [ ] File renamed to `{Artist} - {Title}.{ext}` pattern
- [ ] Handles None/missing fields gracefully (skips them)
- [ ] Filename sanitization handles edge cases
- [ ] `uv run mypy server/tagger.py` passes strict
- [ ] `uv run pytest tests/test_tagger.py` passes
