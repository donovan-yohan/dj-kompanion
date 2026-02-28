# MusicBrainz API Reference for dj-kompanion

**Source:** https://musicbrainz.org/doc/MusicBrainz_API
**Search docs:** https://musicbrainz.org/doc/MusicBrainz_API/Search
**Rate limiting:** https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
**Python library:** https://python-musicbrainzngs.readthedocs.io/en/latest/api/
**Library usage:** https://python-musicbrainzngs.readthedocs.io/en/latest/usage/
**Cover Art Archive:** https://coverartarchive.org/

## Python Library: musicbrainzngs

**PyPI:** https://pypi.org/project/musicbrainzngs/
**GitHub:** https://github.com/alastair/python-musicbrainzngs

### Setup

```python
import musicbrainzngs

# MUST be called before any requests
musicbrainzngs.set_useragent("dj-kompanion", "1.0", "contact@example.com")

# Rate limiting: 1 request per second (default, enforced by library)
# musicbrainzngs.set_rate_limit(limit_or_interval=1.0, new_requests=1)
```

### Search Recordings

```python
result = musicbrainzngs.search_recordings(
    artist="Skrillex",
    recording="Rumble",
    limit=5,
)

# Returns dict with 'recording-list' key
recordings = result["recording-list"]

for rec in recordings:
    print(rec["id"])           # MusicBrainz ID (MBID)
    print(rec["title"])        # Recording title
    print(rec["ext:score"])    # Match score 0-100
    print(rec.get("artist-credit"))  # Artist info
    print(rec.get("release-list"))   # Albums/releases
    print(rec.get("tag-list"))       # Genre tags
```

### Search Fields (Lucene Syntax)

| Field | Purpose |
|-------|---------|
| `recording` | Track name |
| `artist` | Artist name |
| `release` | Album/release title |
| `tag` | User-assigned genre/mood tags |
| `dur` | Duration in milliseconds |
| `firstreleasedate` | Earliest release date (YYYY-MM-DD) |
| `status` | Release status (Official, Promotion, etc.) |
| `primarytype` | Release group type (Album, Single, EP) |
| `country` | 2-letter country code |

### Get Recording Details by ID (with includes)

```python
result = musicbrainzngs.get_recording_by_id(
    recording_mbid,
    includes=["artists", "releases", "tags"],
)

recording = result["recording"]
# recording["artist-credit"] -> artist info
# recording["release-list"] -> album/release info with label
# recording["tag-list"] -> genre tags with counts
```

**Available includes for recordings:** artists, releases, discids, media, artist-credits, isrcs, work-level-rels, annotation, aliases, tags, user-tags, ratings, user-ratings, area-rels, artist-rels, label-rels, place-rels, event-rels, recording-rels, release-rels, release-group-rels, series-rels, url-rels, work-rels, instrument-rels

### Response Structure

Recording search result:
```json
{
  "id": "MBID",
  "title": "Track name",
  "ext:score": "95",
  "length": "duration_in_milliseconds",
  "artist-credit": [
    {
      "artist": {
        "id": "artist_MBID",
        "name": "Artist Name",
        "sort-name": "Name, Artist"
      }
    }
  ],
  "first-release-date": "YYYY-MM-DD",
  "release-list": [
    {
      "id": "release_MBID",
      "title": "Album title",
      "date": "YYYY-MM-DD",
      "country": "US",
      "status": "Official",
      "release-group": {
        "primary-type": "Album"
      }
    }
  ],
  "tag-list": [
    {"name": "electronic", "count": "5"},
    {"name": "house", "count": "3"}
  ]
}
```

### Getting Label Info

Labels are on releases, not recordings. To get label info, look up the release:

```python
result = musicbrainzngs.get_release_by_id(
    release_mbid,
    includes=["labels"],
)
release = result["release"]
# release["label-info-list"] -> [{"label": {"name": "Label Name"}}]
```

### Cover Art Archive

```python
# Get front cover URL by release MBID
cover_url = f"https://coverartarchive.org/release/{release_mbid}/front-250"
# Returns 307 redirect to actual image. Sizes: 250, 500, 1200

# Or get all images:
# GET https://coverartarchive.org/release/{release_mbid}/
# Returns JSON with "images" array
```

No rate limits currently enforced on Cover Art Archive.

### Error Handling

```python
import musicbrainzngs

try:
    result = musicbrainzngs.search_recordings(recording="test")
except musicbrainzngs.WebServiceError as e:
    # Network error, 503 rate limit, etc.
    print(f"API error: {e}")
except musicbrainzngs.UsageError as e:
    # Missing user agent, invalid parameters
    print(f"Usage error: {e}")
```

### Rate Limits

- Global: 300 requests/second across all users
- Per-application: **1 request per second** (enforced by library by default)
- Violations result in HTTP 503
- User-Agent string is **required** — requests without it may be blocked
