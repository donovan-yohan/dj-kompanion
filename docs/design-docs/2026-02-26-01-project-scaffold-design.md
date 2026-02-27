# Project Scaffold & Config — Design

**Date:** 2026-02-26
**Status:** Approved
**Phase:** 1 (Foundation)
**Parent Design:** `2026-02-26-yt-dlp-dj-design.md`

## Context

yt-dlp-dj is a Chrome extension + Python local server that wraps yt-dlp for one-click music downloading with DJ-ready metadata. This design doc covers the project foundation: directory structure, Python packaging, config system, dev tooling, and the CLI entry point skeleton.

Everything else (downloader, tagger, enrichment, server, extension) builds on top of this scaffold.

## Goal

A working project skeleton where:
- `uv run yt-dlp-dj --help` shows the CLI
- `uv run pytest` runs (with zero tests passing — just the harness)
- `uv run mypy server/` passes with strict mode
- `uv run ruff check .` passes
- Config loads from `~/.config/yt-dlp-dj/config.yaml` with sensible defaults

## Project Structure

```
yt-dlp-dj/
├── .gitignore
├── CLAUDE.md                    # (already exists)
├── docs/                        # (already exists)
├── pyproject.toml               # uv project, ruff + mypy + pytest config
├── server/
│   ├── __init__.py
│   ├── py.typed                 # PEP 561 marker
│   ├── cli.py                   # typer CLI entry point (serve, download, config)
│   ├── config.py                # Config loading, validation, defaults
│   └── models.py                # Pydantic models (shared data shapes)
├── extension/
│   ├── tsconfig.json            # strict: true
│   ├── package.json             # esbuild, eslint, prettier, typescript
│   ├── .eslintrc.json
│   ├── .prettierrc
│   └── src/
│       └── types.ts             # Shared TypeScript types
└── tests/
    ├── __init__.py
    └── conftest.py
```

## pyproject.toml

```toml
[project]
name = "yt-dlp-dj"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn",
    "yt-dlp",
    "mutagen",
    "typer",
    "pyyaml",
]

[project.scripts]
yt-dlp-dj = "server.cli:app"

[tool.mypy]
strict = true
packages = ["server"]

[tool.ruff]
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

## Config System

`server/config.py` — Loads config from `~/.config/yt-dlp-dj/config.yaml`, merging with defaults.

```python
from pydantic import BaseModel
from pathlib import Path

class LLMConfig(BaseModel):
    enabled: bool = True
    model: str = "haiku"

class AppConfig(BaseModel):
    output_dir: Path = Path("~/Music/DJ Library").expanduser()
    preferred_format: str = "best"  # best | mp3 | flac | m4a
    filename_template: str = "{artist} - {title}"
    server_port: int = 9234
    llm: LLMConfig = LLMConfig()
```

Config file created on first run if it doesn't exist. `yt-dlp-dj config` opens it in `$EDITOR`.

## Pydantic Models

`server/models.py` — Shared data shapes used across all modules.

```python
class RawMetadata(BaseModel):
    title: str
    uploader: str | None
    duration: int | None
    upload_date: str | None
    description: str | None
    tags: list[str]
    source_url: str

class EnrichedMetadata(BaseModel):
    artist: str
    title: str
    genre: str | None = None
    year: int | None = None
    label: str | None = None
    energy: int | None = None
    bpm: int | None = None
    key: str | None = None
    comment: str = ""

class PreviewResponse(BaseModel):
    raw: RawMetadata
    enriched: EnrichedMetadata
    enrichment_source: str  # "claude" | "none"

class DownloadRequest(BaseModel):
    url: str
    metadata: EnrichedMetadata
    format: str = "best"

class DownloadResponse(BaseModel):
    status: str
    filepath: str
```

## TypeScript Types

`extension/src/types.ts` — Mirror of the Pydantic models for the extension.

```typescript
export interface EnrichedMetadata {
  artist: string;
  title: string;
  genre: string | null;
  year: number | null;
  label: string | null;
  energy: number | null;
  bpm: number | null;
  key: string | null;
  comment: string;
}

export interface PreviewResponse {
  raw: RawMetadata;
  enriched: EnrichedMetadata;
  enrichment_source: "claude" | "none";
}

export interface DownloadRequest {
  url: string;
  metadata: EnrichedMetadata;
  format: string;
}

export interface DownloadResponse {
  status: string;
  filepath: string;
}
```

## CLI Skeleton

`server/cli.py` — typer app with stubbed commands.

```
yt-dlp-dj serve              # Start FastAPI server
yt-dlp-dj serve -p 8080      # Custom port
yt-dlp-dj config             # Open config in $EDITOR
yt-dlp-dj download <URL>     # Direct CLI download (implemented later)
```

The `serve` and `download` commands are stubs that print "not implemented yet" — they'll be wired up in the server phase.

## Dev Tooling

- **uv** for package management
- **ruff** for linting (E, F, I, UP, B, SIM, TCH rule sets) and formatting
- **mypy** strict mode for type checking
- **pytest** for tests
- **esbuild** for TypeScript compilation
- **eslint + prettier** for extension code

## Extension package.json

Minimal setup with build/lint/format scripts:
```json
{
  "name": "yt-dlp-dj-extension",
  "private": true,
  "scripts": {
    "build": "esbuild src/popup.ts src/background.ts src/options.ts --bundle --outdir=dist",
    "lint": "eslint src/",
    "format": "prettier --write src/",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "esbuild": "^0.24",
    "eslint": "^9",
    "prettier": "^3",
    "typescript": "^5",
    "@anthropic-ai/claude-code": "latest"
  }
}
```

## Success Criteria

- [ ] `git init` and `.gitignore` set up
- [ ] `uv sync` installs all dependencies
- [ ] `uv run yt-dlp-dj --help` shows CLI help
- [ ] `uv run yt-dlp-dj config` creates default config file
- [ ] `uv run mypy server/` passes with strict mode
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` runs (empty test suite, 0 tests)
- [ ] `cd extension && npm install && npm run typecheck` passes
- [ ] `cd extension && npm run lint && npm run format` passes
