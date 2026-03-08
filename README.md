# dj-kompanion

A personal convenience tool wrapping [yt-dlp](https://github.com/yt-dlp/yt-dlp) with a Chrome extension and local server for one-click audio/video downloading with DJ-ready metadata (Virtual DJ format). Optional LLM-assisted metadata enrichment via the [Claude CLI](https://docs.anthropic.com/en/docs/claude-code).

## Quick Start

```bash
# 1. Install dependencies
uv sync
cd extension && npm install && npm run build && cd ..

# 2. Initialize vendored dependencies (required once after clone)
cd analyzer && git submodule update --init --recursive && cd ..

# 3. Start the analyzer container (see "Analyzer" section below)
docker compose up -d

# 4. Start the server
uv run uvicorn server.app:app --reload --port 9234

# 5. Load the extension in Chrome
#    chrome://extensions → Developer mode → Load unpacked → select extension/
```

**Verify it's working:**
- Analyzer: `curl http://localhost:9235/health` → `{"status":"ok"}`
- Server: `curl http://localhost:9234/api/health` → `{"status":"ok","yt_dlp_version":"...","claude_available":...}`

## Architecture

- **Python server** (FastAPI) — handles downloading, tagging, and LLM enrichment
- **Chrome extension** (Manifest V3, TypeScript) — thin popup UI for previewing metadata and triggering downloads
- **Analyzer** (Docker) — ML-based audio analysis (song structure, BPM, key detection). Runs in a container because some ML libraries (NATTEN) don't have macOS ARM64 support.

## Prerequisites

- [Python 3.11+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Node.js 18+](https://nodejs.org/) and npm
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed automatically as a Python dependency)
- [ffmpeg](https://ffmpeg.org/) (required by yt-dlp for audio conversion)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) (optional, for LLM metadata enrichment)
- [Docker](https://www.docker.com/) (required for the analyzer)

## Setup

### Server

```bash
# Install Python dependencies
uv sync

# Run the server on port 9234
uv run uvicorn server.app:app --reload --port 9234
```

### Analyzer

The analyzer runs ML audio analysis in Docker. Two configurations are available:

#### Option A: CPU (local / macOS / any machine)

Uses `python:3.11-slim` base image with CPU-only PyTorch. Simpler setup, works everywhere, but slower for analysis.

```bash
# Build and start
docker compose up -d

# Verify
curl http://localhost:9235/health
```

| File | Purpose |
|------|---------|
| `docker-compose.yml` | CPU compose config (maps `~/Music/DJ Library` into container) |
| `analyzer/Dockerfile` | CPU image (PyTorch CPU, NATTEN CPU wheel) |

#### Option B: NVIDIA GPU (CUDA)

Uses `nvidia/cuda:12.1.0-runtime-ubuntu22.04` base image with CUDA-accelerated PyTorch. Requires an NVIDIA GPU with drivers and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

```bash
# Build and start
docker compose -f docker-compose.gpu.yml up -d

# Verify GPU is visible inside the container
docker compose -f docker-compose.gpu.yml exec analyzer python3 -c "import torch; print(torch.cuda.get_device_name(0))"
```

| File | Purpose |
|------|---------|
| `docker-compose.gpu.yml` | GPU compose config (NVIDIA runtime, `/mnt/dj-library` mount) |
| `analyzer/Dockerfile.gpu` | GPU image (PyTorch CUDA 12.1, NATTEN CUDA wheel) |

**GPU prerequisites:**
- NVIDIA GPU with working drivers (`nvidia-smi` should show your card)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed and configured
- Docker configured with the NVIDIA runtime (`nvidia-ctk runtime configure --runtime=docker`)

**Proxmox / AppArmor note:** On Proxmox hosts, the CUDA base image requires `security_opt: [seccomp=unconfined, apparmor=unconfined]` in the compose file (already set in `docker-compose.gpu.yml`) due to AppArmor restrictions on socket operations.

For a full walkthrough of setting up GPU analysis on a Proxmox server with Tailscale, see [`docs/gpu-analyzer-setup.md`](docs/gpu-analyzer-setup.md).

#### Performance comparison

| Stage | CPU (Rosetta) | GTX 1080 |
|-------|--------------|----------|
| Demucs separation | ~4 min | ~15-30 sec |
| allin1 inference | ~2 min | ~10-20 sec |
| Key detection | ~5 sec | ~5 sec (CPU-bound) |
| **Total** | **~6 min** | **~30-60 sec** |

#### Vendored dependencies

The analyzer vendors two libraries in `analyzer/vendor/` that can't be installed from PyPI on Python 3.11+:

- **[madmom](https://github.com/CPJKU/madmom)** — beat/tempo detection. PyPI release (0.16.1) is broken on Python 3.11+; the git `main` branch has fixes. Includes a `models` git submodule that must be initialized.
- **[all-in-one](https://github.com/hordiales/all-in-one)** (hordiales fork) — music structure analysis. Fork of [mir-aidj/all-in-one](https://github.com/mir-aidj/all-in-one) with custom modifications.

After cloning, initialize submodules:

```bash
cd analyzer/vendor/madmom
git submodule update --init --recursive
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
- Analyzer URL (set to a remote host for GPU offloading)
- LLM enrichment (enable/disable, model selection)

## Usage

1. Start the analyzer: `docker compose up -d` (or `docker compose -f docker-compose.gpu.yml up -d` for GPU)
2. Start the server: `uv run uvicorn server.app:app --reload --port 9234`
3. Open a page with audio/video content (YouTube, SoundCloud, Bandcamp, etc.)
4. Click the dj-kompanion extension icon
5. Review and edit the metadata preview
6. Click download

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
| Start analyzer (CPU) | `docker compose up -d` |
| Start analyzer (GPU) | `docker compose -f docker-compose.gpu.yml up -d` |
| Rebuild analyzer | `docker compose build --no-cache` |
| Analyzer logs | `docker compose logs -f analyzer` |
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
