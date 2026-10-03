"""Load validated settings at runtime without import-time filesystem access."""

import json
import os
from pathlib import Path

from .files import atomic_text_writer
from .locking import file_lock


def config_file() -> Path:
    """Keep the historical location; allow isolated CLI runs through an override."""
    override = os.environ.get("HIPER_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "hiper" / "config.json"


def _load_config() -> dict[str, str]:
    path = config_file()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as stream:
        value: object = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: configuration must be an object of string settings")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"{path}: configuration keys and values must be strings")
        result[key] = item
    return result


def _save_config(cfg: dict[str, str]) -> None:
    with atomic_text_writer(config_file()) as stream:
        json.dump(cfg, stream, indent=2)
        stream.write("\n")


def get_config(key: str, default: str = "") -> str:
    return _load_config().get(key, default)


def update_config(values: dict[str, str]) -> None:
    with file_lock(config_file().with_suffix(".lock")):
        cfg = _load_config()
        cfg.update(values)
        _save_config(cfg)


def set_config(key: str, value: str) -> None:
    update_config({key: value})


def get_data_dir() -> str:
    savedir = get_config("savedir")
    if savedir and os.path.isabs(savedir):
        return savedir
    return str(Path.home() / ".local" / "share" / "hiper")
