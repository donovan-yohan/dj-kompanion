# Last.fm API Reference for dj-kompanion

**API docs:** https://www.last.fm/api
**Get API key:** https://www.last.fm/api/account/create
**track.search:** https://www.last.fm/api/show/track.search
**track.getTopTags:** https://www.last.fm/api/show/track.getTopTags
**track.getInfo:** https://www.last.fm/api/show/track.getInfo
**Python library (pylast):** https://github.com/pylast/pylast
**pylast PyPI:** https://pypi.org/project/pylast/

## Python Library: pylast

### Setup

```python
import pylast

# Only API_KEY is required for read-only operations
# API_SECRET, username, password_hash are only needed for write operations
network = pylast.LastFMNetwork(api_key="YOUR_API_KEY")
```

### Search for Tracks

```python
# Search returns TrackSearch object
results = network.search_for_track("Skrillex", "Rumble")
tracks = results.get_next_page()  # Returns list of Track objects

for track in tracks:
    print(track.get_name())    # Track title
    print(track.artist)        # Artist object
```

### Get Top Tags for a Track (Genre Data)

```python
track = network.get_track("Skrillex", "Rumble")
top_tags = track.get_top_tags()

for tag_item in top_tags:
    print(tag_item.item.name)  # Tag name like "dubstep", "electronic"
    print(tag_item.weight)     # Tag weight/count
```

### Get Track Info (Album, Duration, Tags)

```python
track = network.get_track("Cher", "Believe")

# Get album
album = track.get_album()
if album:
    print(album.get_name())     # Album title
    print(album.artist)         # Album artist

# Get duration
duration = track.get_duration()  # In milliseconds

# Get top tags inline
tags = track.get_top_tags()
```

### Direct HTTP API (Alternative to pylast)

If pylast doesn't expose something, you can call the API directly:

**track.search** — No auth required:
```
GET https://ws.audioscrobbler.com/2.0/?method=track.search&track=Believe&artist=Cher&api_key=YOUR_API_KEY&format=json&limit=5
```

Parameters:
- `track` (required): Track name
- `artist` (optional): Filter by artist
- `api_key` (required): Your API key
- `limit` (optional): Results per page, default 30
- `page` (optional): Page number, default 1
- `format` (optional): `json` for JSON response

Response:
```json
{
  "results": {
    "trackmatches": {
      "track": [
        {
          "name": "Track Name",
          "artist": "Artist Name",
          "url": "https://www.last.fm/music/...",
          "listeners": "12345",
          "image": [...]
        }
      ]
    }
  }
}
```

**track.getTopTags** — No auth required:
```
GET https://ws.audioscrobbler.com/2.0/?method=track.gettoptags&artist=radiohead&track=paranoid+android&api_key=YOUR_API_KEY&format=json
```

Parameters:
- `artist` + `track` (required together), OR `mbid` (MusicBrainz ID)
- `autocorrect` (optional): 0 or 1, corrects misspellings
- `api_key` (required)

Response:
```json
{
  "toptags": {
    "tag": [
      {"name": "alternative rock", "count": 100, "url": "..."},
      {"name": "rock", "count": 87, "url": "..."},
      {"name": "britpop", "count": 45, "url": "..."}
    ]
  }
}
```

**track.getInfo** — No auth required:
```
GET https://ws.audioscrobbler.com/2.0/?method=track.getInfo&artist=cher&track=believe&api_key=YOUR_API_KEY&format=json
```

Parameters:
- `artist` + `track` (required together), OR `mbid`
- `autocorrect` (optional): 0 or 1
- `username` (optional): adds user playcount/love status
- `api_key` (required)

Response fields:
- `name`: Track title
- `duration`: In milliseconds
- `artist`: { name, mbid, url }
- `album`: { title, artist, image[], position, mbid }
- `toptags`: { tag: [{ name, url }] }
- `wiki`: { published, summary, content }
- `listeners`: Number of listeners
- `playcount`: Total play count

### Error Handling

```python
import pylast

try:
    track = network.get_track("Artist", "Track")
    tags = track.get_top_tags()
except pylast.WSError as e:
    # API error (invalid params, rate limit, etc.)
    print(f"Last.fm error: {e}")
except pylast.NetworkError as e:
    # Connection error
    print(f"Network error: {e}")
```

Error codes:
- 2: Invalid service
- 3: Invalid method
- 4: Authentication failed
- 6: Track/artist not found
- 10: Invalid API key
- 26: API key suspended
- 29: Rate limit exceeded

### Rate Limits

- Not explicitly documented, but error code 29 = rate limit exceeded
- In practice, ~5 requests per second is safe
- Caching is recommended (pylast has built-in cache support, disabled by default)

### Enabling pylast Cache

```python
network.enable_caching()  # Uses shelve-based cache
# Or with custom file:
# network.enable_caching(file_path="/path/to/cache")
```
