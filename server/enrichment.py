from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from typing import Any

from server.models import EnrichedMetadata, RawMetadata

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

    try:
        raw_parsed: Any = json.loads(text_to_parse)
    except json.JSONDecodeError:
        logger.warning("claude returned invalid JSON (first 200 chars): %.200s", text_to_parse)
        return None

    if not isinstance(raw_parsed, dict):
        logger.warning("claude returned non-dict JSON")
        return None

    data: dict[str, Any] = raw_parsed

    try:
        return EnrichedMetadata(
            artist=str(data.get("artist") or ""),
            title=str(data.get("title") or ""),
            genre=str(data["genre"]) if data.get("genre") else None,
            year=int(data["year"]) if data.get("year") else None,
            label=str(data["label"]) if data.get("label") else None,
            energy=int(data["energy"]) if data.get("energy") else None,
            bpm=None,
            key=None,
            comment=raw.source_url,
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


async def enrich_metadata(raw: RawMetadata, model: str = "haiku") -> EnrichedMetadata:
    """Use claude CLI to parse and enrich raw metadata.

    Falls back to basic parsing if claude is unavailable.
    Never raises -- always returns an EnrichedMetadata.
    """
    if not await is_claude_available():
        logger.warning("claude CLI not found on PATH; falling back to basic_enrich")
        return basic_enrich(raw)

    prompt = _PROMPT_TEMPLATE.format(
        raw_metadata_json=raw.model_dump_json(indent=2),
    )

    cmd = ["claude", "-p", "--model", model, "--output-format", "json", prompt]

    try:
        result = await asyncio.to_thread(_run_subprocess, cmd, 30.0)
    except subprocess.TimeoutExpired:
        logger.warning("claude timed out after 30s, falling back to basic_enrich")
        return basic_enrich(raw)
    except (FileNotFoundError, OSError) as e:
        logger.warning("claude CLI error: %s", e)
        return basic_enrich(raw)

    if result.returncode != 0:
        logger.warning("claude returned non-zero exit code %d", result.returncode)
        return basic_enrich(raw)

    enriched = _parse_claude_response(result.stdout, raw)
    if enriched is None:
        return basic_enrich(raw)

    return enriched


async def try_enrich_metadata(raw: RawMetadata, model: str = "haiku") -> EnrichedMetadata | None:
    """Like enrich_metadata, but returns None instead of falling back.

    Used by the download endpoint to distinguish Claude success from failure.
    """
    if not await is_claude_available():
        return None

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

    return _parse_claude_response(result.stdout, raw)
