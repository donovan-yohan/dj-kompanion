from __future__ import annotations

import asyncio
from typing import Annotated

import typer
import uvicorn

from server.config import load_config, open_config_in_editor
from server.downloader import DownloadError, download_audio, extract_metadata
from server.enrichment import basic_enrich, enrich_metadata, is_claude_available
from server.tagger import TaggingError, build_download_filename, tag_file

app = typer.Typer(
    name="dj-kompanion",
    help="One-click music downloading with DJ-ready metadata.",
    no_args_is_help=True,
)


async def _download_pipeline(url: str, preferred_format: str | None) -> None:
    cfg = load_config()

    typer.echo(f"Extracting metadata for {url}...")
    raw = await extract_metadata(url)

    typer.echo("Enriching metadata...")
    if cfg.llm.enabled and await is_claude_available():
        enriched = await enrich_metadata(raw, model=cfg.llm.model)
    else:
        enriched = basic_enrich(raw)

    typer.echo(f"  Artist: {enriched.artist}")
    typer.echo(f"  Title:  {enriched.title}")
    if enriched.genre:
        typer.echo(f"  Genre:  {enriched.genre}")

    preferred = preferred_format or cfg.preferred_format
    filename = build_download_filename(enriched.artist, enriched.title)

    typer.echo(f"Downloading to {cfg.output_dir}...")
    filepath = await download_audio(url, cfg.output_dir, filename, preferred)
    final = tag_file(filepath, enriched)
    typer.echo(f"Saved: {final}")


@app.command()
def serve(
    port: Annotated[int | None, typer.Option("--port", "-p", help="Port to listen on.")] = None,
) -> None:
    """Start the local FastAPI server."""
    cfg = load_config()
    actual_port = port if port is not None else cfg.server_port
    uvicorn.run("server.app:app", host="127.0.0.1", port=actual_port)


@app.command()
def config() -> None:
    """Create (if needed) and open the config file in $EDITOR."""
    open_config_in_editor()


@app.command()
def download(
    url: Annotated[str, typer.Argument(help="URL to download.")],
    format: Annotated[str | None, typer.Option("--format", "-f", help="Audio format.")] = None,
) -> None:
    """Download audio from a URL directly."""
    try:
        asyncio.run(_download_pipeline(url, format))
    except DownloadError as e:
        typer.echo(f"Download failed: {e.message}", err=True)
        raise typer.Exit(1) from None
    except TaggingError as e:
        typer.echo(f"Tagging failed for '{e.filepath}': {e.message}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Unexpected error ({type(e).__name__}): {e}", err=True)
        raise typer.Exit(1) from None
