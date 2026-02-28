from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

CONFIG_DIR = Path("~/.config/dj-kompanion").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class LLMConfig(BaseModel):
    enabled: bool = True
    model: str = "haiku"


class AnalysisConfig(BaseModel):
    enabled: bool = True
    vdj_database: Path = Path("~/Documents/VirtualDJ/database.xml").expanduser()
    max_cues: int = 8
    analyzer_url: str = "http://localhost:9235"


class AppConfig(BaseModel):
    output_dir: Path = Path("~/Music/DJ Library").expanduser()
    preferred_format: str = "best"
    filename_template: str = "{artist} - {title}"
    server_port: int = 9234
    llm: LLMConfig = LLMConfig()
    analysis: AnalysisConfig = AnalysisConfig()


def _serializable_defaults() -> dict[str, object]:
    """Return default config as a YAML-friendly dict (Paths as strings)."""
    config = AppConfig()
    data = config.model_dump()
    data["output_dir"] = str(config.output_dir)
    data["analysis"] = {
        "enabled": config.analysis.enabled,
        "vdj_database": str(config.analysis.vdj_database),
        "max_cues": config.analysis.max_cues,
    }
    return data


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as f:
            yaml.dump(_serializable_defaults(), f, default_flow_style=False)
        return AppConfig()

    try:
        with CONFIG_FILE.open() as f:
            data: dict[str, object] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise RuntimeError(
            f"Config file at {CONFIG_FILE} contains invalid YAML: {e}. "
            "Fix or delete the file to reset to defaults."
        ) from e

    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        raise RuntimeError(
            f"Config file at {CONFIG_FILE} has invalid values: {e}. "
            "Fix or delete the file to reset to defaults."
        ) from e


def open_config_in_editor() -> None:
    if not CONFIG_FILE.exists():
        load_config()

    editor = os.environ.get("EDITOR", "nano")
    try:
        result = subprocess.run([editor, str(CONFIG_FILE)], check=False)
        if result.returncode != 0:
            print(
                f"Warning: editor '{editor}' exited with code {result.returncode}.",
                file=sys.stderr,
            )
    except FileNotFoundError:
        print(
            f"Error: editor '{editor}' not found. Set $EDITOR to a valid editor.",
            file=sys.stderr,
        )
