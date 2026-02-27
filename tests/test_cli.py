from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from server.cli import app as cli_app
from server.models import EnrichedMetadata, RawMetadata

runner = CliRunner()

SAMPLE_RAW = RawMetadata(
    title="DJ Snake - Turn Down for What",
    uploader="DJ Snake",
    duration=210,
    upload_date="20140101",
    description="",
    tags=[],
    source_url="https://youtube.com/watch?v=test",
)

SAMPLE_ENRICHED = EnrichedMetadata(
    artist="DJ Snake",
    title="Turn Down for What",
    genre="EDM",
)

MOCK_PATH = Path("/tmp/DJ Snake - Turn Down for What.m4a")


def test_serve_starts_uvicorn() -> None:
    with patch("server.cli.uvicorn") as mock_uvicorn:
        result = runner.invoke(cli_app, ["serve"])
    assert result.exit_code == 0
    mock_uvicorn.run.assert_called_once()


def test_serve_uses_default_port() -> None:
    with patch("server.cli.uvicorn") as mock_uvicorn:
        result = runner.invoke(cli_app, ["serve"])
    assert result.exit_code == 0
    assert mock_uvicorn.run.call_args.kwargs["port"] == 9234


def test_serve_uses_custom_port() -> None:
    with patch("server.cli.uvicorn") as mock_uvicorn:
        result = runner.invoke(cli_app, ["serve", "--port", "8080"])
    assert result.exit_code == 0
    assert mock_uvicorn.run.call_args.kwargs["port"] == 8080


def test_serve_uses_app_string() -> None:
    with patch("server.cli.uvicorn") as mock_uvicorn:
        result = runner.invoke(cli_app, ["serve"])
    assert result.exit_code == 0
    call_args = mock_uvicorn.run.call_args
    assert call_args.args[0] == "server.app:app"


def test_download_success() -> None:
    with (
        patch("server.cli.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch(
            "server.cli.enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.cli.download_audio", new_callable=AsyncMock, return_value=MOCK_PATH),
        patch("server.cli.tag_file", return_value=MOCK_PATH),
    ):
        result = runner.invoke(cli_app, ["download", "https://youtube.com/watch?v=test"])

    assert result.exit_code == 0
    assert "Saved:" in result.output


def test_download_shows_metadata() -> None:
    with (
        patch("server.cli.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch(
            "server.cli.enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.cli.download_audio", new_callable=AsyncMock, return_value=MOCK_PATH),
        patch("server.cli.tag_file", return_value=MOCK_PATH),
    ):
        result = runner.invoke(cli_app, ["download", "https://youtube.com/watch?v=test"])

    assert "DJ Snake" in result.output
    assert "Turn Down for What" in result.output


def test_download_error_exits_nonzero() -> None:
    from server.downloader import DownloadError

    with patch(
        "server.cli.extract_metadata",
        new_callable=AsyncMock,
        side_effect=DownloadError("Bad URL", url="https://bad.com"),
    ):
        result = runner.invoke(cli_app, ["download", "https://bad.com"])

    assert result.exit_code == 1


def test_download_with_format_option() -> None:
    with (
        patch("server.cli.extract_metadata", new_callable=AsyncMock, return_value=SAMPLE_RAW),
        patch(
            "server.cli.enrich_metadata", new_callable=AsyncMock, return_value=SAMPLE_ENRICHED
        ),
        patch("server.cli.download_audio", new_callable=AsyncMock, return_value=MOCK_PATH) as mock_dl,
        patch("server.cli.tag_file", return_value=MOCK_PATH),
    ):
        result = runner.invoke(
            cli_app, ["download", "https://youtube.com/watch?v=test", "--format", "mp3"]
        )

    assert result.exit_code == 0
    # The format "mp3" should be passed to download_audio
    call_args = mock_dl.call_args
    assert call_args.args[3] == "mp3"
