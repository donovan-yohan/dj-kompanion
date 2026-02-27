# dj-kompanion

A personal convenience tool wrapping [yt-dlp](https://github.com/yt-dlp/yt-dlp) with a Chrome extension and local server for one-click audio/video downloading with DJ-ready metadata (Virtual DJ format). Optional LLM-assisted metadata enrichment via the [Claude CLI](https://docs.anthropic.com/en/docs/claude-code).

## Architecture

- **Python server** (FastAPI) — handles downloading, tagging, and LLM enrichment
- **Chrome extension** (Manifest V3, TypeScript) — thin popup UI for previewing metadata and triggering downloads

## Prerequisites

- [Python 3.11+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Node.js 18+](https://nodejs.org/) and npm
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed automatically as a Python dependency)
- [ffmpeg](https://ffmpeg.org/) (required by yt-dlp for audio conversion)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (optional, for LLM metadata enrichment)

## Setup

### Server

```bash
# Install Python dependencies
uv sync

# Run the server on port 9234
uv run uvicorn server.app:app --reload --port 9234
```

### Chrome Extension

```bash
cd extension

# Install Node dependencies
npm install

# Build the extension
npm run build
```

Then load the extension in Chrome:

1. Navigate to `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the `extension/` directory

### Configuration

```bash
# Create/edit the config file (~/.config/dj-kompanion/config.yaml)
uv run dj-kompanion config
```

The config file controls:
- Output directory for downloads
- Preferred audio format
- Server port
- LLM enrichment (enable/disable, model selection)

## Usage

1. Start the server: `uv run uvicorn server.app:app --reload --port 9234`
2. Open a page with audio/video content (YouTube, SoundCloud, Bandcamp, etc.)
3. Click the dj-kompanion extension icon
4. Review and edit the metadata preview
5. Click download

### CLI

You can also download directly from the command line:

```bash
# Download with metadata enrichment
uv run dj-kompanion download "https://www.youtube.com/watch?v=..."

# Specify format
uv run dj-kompanion download "https://www.youtube.com/watch?v=..." --format mp3
```

## Development

| Action | Command |
|--------|---------|
| Server (dev mode) | `uv run uvicorn server.app:app --reload --port 9234` |
| Run tests | `uv run pytest` |
| Type check (Python) | `uv run mypy server/` |
| Lint (Python) | `uv run ruff check .` |
| Format (Python) | `uv run ruff format .` |
| Build extension | `cd extension && npm run build` |
| Type check (Extension) | `cd extension && npm run typecheck` |
| Lint (Extension) | `cd extension && npm run lint` |
| Format (Extension) | `cd extension && npm run format` |

## License

Personal project — no license specified.
