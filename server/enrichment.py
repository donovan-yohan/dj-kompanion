from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import subprocess
from typing import TYPE_CHECKING, Any

from server.models import EnrichedMetadata, RawMetadata

if TYPE_CHECKING:
    from server.metadata_lookup import MetadataCandidate

logger = logging.getLogger(__name__)

_SUFFIXES = [
    "(Official Video)",
    "(Official Audio)",
    "(Official Music Video)",
    "(Lyrics)",
    "(Lyric Video)",
    "[HD]",
    "[4K]",
    "[HQ]",
    "(HD)",
    "(HQ)",
    "(Audio)",
    "(Video)",
]

_MARKDOWN_FENCE_RE = re.compile(r"```\w*\s*\n(.*?)\n\s*```", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Extract content from markdown code fences if present."""
    match = _MARKDOWN_FENCE_RE.search(text)
    if match:
        return match.group(1)
    return text


_PROMPT_TEMPLATE = """\
You are a metadata parser for DJ music files. Given raw metadata from a music download, \
extract clean, accurate metadata.

Rules:
- Separate artist from title (YouTube titles often combine them with " - ", " | ", " // ")
- Remove quality indicators: [HD], [4K], (Official Video), (Official Audio), (Lyrics), etc.
- Remove channel self-promotion suffixes
- Infer genre from title, description, tags, and channel context
- Estimate energy level 1-10 (1=ambient/chill, 5=moderate, 10=hard/intense)
- Use release year, not upload year, when inferable from description
- Extract label name if mentioned in description or tags
- If unsure about a field, return null

Raw metadata:
{raw_metadata_json}

Return ONLY valid JSON matching this schema:
{{
  "artist": "string",
  "title": "string",
  "genre": "string or null",
  "year": "number or null",
  "label": "string or null",
  "energy": "number 1-10 or null",
  "bpm": null,
  "key": null,
  "comment": "source URL"
}}"""

_PROMPT_WITH_CANDIDATES_TEMPLATE = """\
You are a metadata matcher for DJ music files. You have raw metadata from a YouTube
download AND search results from music databases. Your job is to:

1. Determine which search result (if any) matches this actual song
2. Extract the best metadata by combining the match with raw context
3. If no result matches, infer metadata as best you can

Raw metadata from download:
{raw_metadata_json}

Search results from music databases:
{candidates_json}

Rules:
- Pick the search result that matches this SPECIFIC recording (not just same artist)
- For remixes: match the REMIX version, not the original. "Artist - Song (Remixer Remix)"
  should match a release that credits the remixer, not the original release. If only the
  original is in results, say no_match rather than using wrong release metadata.
- Genre: prefer the API genre tags, pick the most specific applicable one
  (e.g. "deep house" over "electronic")
- If no search result matches well, say "no_match" and infer like before
- Energy level 1-10 is always your inference (APIs don't have this)
- cover_art_url: pass through from the selected candidate if available

Return ONLY valid JSON:
{{
  "selected_candidate_index": null or number,
  "confidence": "high" or "medium" or "low",
  "artist": "string",
  "title": "string",
  "album": "string or null",
  "genre": "string or null",
  "year": null or number,
  "label": "string or null",
  "energy": null or number 1-10,
  "bpm": null,
  "key": null,
  "comment": "source URL",
  "cover_art_url": "string or null"
}}"""


def _candidates_to_json(candidates: list[MetadataCandidate]) -> str:
    return json.dumps([dataclasses.asdict(c) for c in candidates], indent=2)


def basic_enrich(raw: RawMetadata) -> EnrichedMetadata:
    """Fallback enrichment without LLM.

    Attempts basic artist/title splitting from common YouTube title patterns.
    """
    title = raw.title
    artist: str

    if " - " in title:
        artist, title = title.split(" - ", 1)
    elif " | " in title:
        artist, title = title.split(" | ", 1)
    elif " // " in title:
        artist, title = title.split(" // ", 1)
    else:
        artist = raw.uploader or "Unknown"

    for suffix in _SUFFIXES:
        title = re.sub(re.escape(suffix), "", title, flags=re.IGNORECASE).strip()

    return EnrichedMetadata(
        artist=artist.strip(),
        title=title.strip(),
        comment=raw.source_url,
    )


def merge_metadata(
    user: EnrichedMetadata,
    claude: EnrichedMetadata | None,
    user_edited_fields: list[str],
) -> EnrichedMetadata:
    """Merge user-edited metadata with Claude enrichment results.

    Priority: user-edited fields > Claude non-null > user/basic value.
    Comment is always preserved from the user's metadata.
    """
    if claude is None:
        return user

    user_dict = user.model_dump()
    claude_dict = claude.model_dump()

    merged: dict[str, object] = {}
    for field, user_val in user_dict.items():
        if field == "comment" or field in user_edited_fields:
            merged[field] = user_val
        elif claude_dict[field] is not None:
            merged[field] = claude_dict[field]
        else:
            merged[field] = user_val

    return EnrichedMetadata.model_validate(merged)


def _parse_claude_response(response_text: str, raw: RawMetadata) -> EnrichedMetadata | None:
    """Parse JSON response from claude CLI. Returns None if parsing fails."""
    text_to_parse = response_text

    try:
        envelope: Any = json.loads(response_text)
        if isinstance(envelope, dict) and "result" in envelope:
            result_val = envelope["result"]
            if isinstance(result_val, str):
                text_to_parse = result_val
    except json.JSONDecodeError:
        pass

    text_to_parse = _strip_markdown_fences(text_to_parse)

    try:
        raw_parsed: Any = json.loads(text_to_parse)
    except json.JSONDecodeError:
        logger.warning("claude returned invalid JSON (first 500 chars): %.500s", response_text)
        return None

    if not isinstance(raw_parsed, dict):
        logger.warning("claude returned non-dict JSON")
        return None

    data: dict[str, Any] = raw_parsed

    try:
        return EnrichedMetadata(
            artist=str(data.get("artist") or ""),
            title=str(data.get("title") or ""),
            album=str(data["album"]) if data.get("album") else None,
            genre=str(data["genre"]) if data.get("genre") else None,
            year=int(data["year"]) if data.get("year") else None,
            label=str(data["label"]) if data.get("label") else None,
            energy=int(data["energy"]) if data.get("energy") else None,
            bpm=None,
            key=None,
            comment=raw.source_url,
            cover_art_url=str(data["cover_art_url"]) if data.get("cover_art_url") else None,
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.warning("failed to parse claude response fields: %s", e)
        return None


def _run_subprocess(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


async def is_claude_available() -> bool:
    """Check if claude CLI is on PATH."""
    try:
        result = await asyncio.to_thread(_run_subprocess, ["claude", "--version"], 5.0)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


async def _run_claude(
    raw: RawMetadata,
    model: str,
    candidates: list[MetadataCandidate] | None = None,
) -> EnrichedMetadata | None:
    """Run claude CLI and parse the response.

    Returns enriched metadata on success, None on any failure.
    Handles availability check, subprocess execution, and debug logging.
    """
    if not await is_claude_available():
        logger.warning("claude CLI not found on PATH")
        return None

    if candidates:
        prompt = _PROMPT_WITH_CANDIDATES_TEMPLATE.format(
            raw_metadata_json=raw.model_dump_json(indent=2),
            candidates_json=_candidates_to_json(candidates),
        )
    else:
        prompt = _PROMPT_TEMPLATE.format(
            raw_metadata_json=raw.model_dump_json(indent=2),
        )

    cmd = ["claude", "-p", "--model", model, "--output-format", "json", prompt]

    try:
        result = await asyncio.to_thread(_run_subprocess, cmd, 30.0)
    except subprocess.TimeoutExpired:
        logger.warning("claude timed out after 30s")
        return None
    except (FileNotFoundError, OSError) as e:
        logger.warning("claude CLI error: %s", e)
        return None

    if result.returncode != 0:
        logger.warning("claude returned non-zero exit code %d", result.returncode)
        return None

    logger.debug("claude raw stdout: %.1000s", result.stdout)
    if result.stderr:
        logger.debug("claude stderr: %.500s", result.stderr)

    return _parse_claude_response(result.stdout, raw)


async def enrich_metadata(
    raw: RawMetadata,
    model: str = "haiku",
    candidates: list[MetadataCandidate] | None = None,
) -> EnrichedMetadata:
    """Use claude CLI to parse and enrich raw metadata.

    Falls back to basic parsing if claude is unavailable.
    Never raises -- always returns an EnrichedMetadata.
    """
    return await _run_claude(raw, model, candidates) or basic_enrich(raw)


async def try_enrich_metadata(
    raw: RawMetadata,
    model: str = "haiku",
    candidates: list[MetadataCandidate] | None = None,
) -> EnrichedMetadata | None:
    """Like enrich_metadata, but returns None instead of falling back.

    Used by the download endpoint to distinguish Claude success from failure.
    """
    return await _run_claude(raw, model, candidates)
