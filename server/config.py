from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path("~/.config/yt-dlp-dj").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class LLMConfig(BaseModel):
    enabled: bool = True
    model: str = "haiku"


class AppConfig(BaseModel):
    output_dir: Path = Path("~/Music/DJ Library").expanduser()
    preferred_format: str = "best"
    filename_template: str = "{artist} - {title}"
    server_port: int = 9234
    llm: LLMConfig = LLMConfig()


def _default_config_dict() -> dict[str, object]:
    config = AppConfig()
    return {
        "output_dir": str(config.output_dir),
        "preferred_format": config.preferred_format,
        "filename_template": config.filename_template,
        "server_port": config.server_port,
        "llm": {
            "enabled": config.llm.enabled,
            "model": config.llm.model,
        },
    }


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as f:
            yaml.dump(_default_config_dict(), f, default_flow_style=False)
        return AppConfig()

    with CONFIG_FILE.open() as f:
        data: dict[str, object] = yaml.safe_load(f) or {}

    return AppConfig.model_validate(data)


def open_config_in_editor() -> None:
    if not CONFIG_FILE.exists():
        load_config()  # creates the file with defaults

    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(CONFIG_FILE)], check=False)
