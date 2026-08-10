"""Workspace configuration for aya.

Stored at ~/.aya/config.json. Tracks workspace-level settings like
notebook_path that aya needs to find user data.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from aya import paths as _paths

logger = logging.getLogger(__name__)


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from disk, returning empty dict if missing or invalid."""
    path = path or _paths.CONFIG_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or _paths.CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


def set_config_value(key: str, value: str, path: Path | None = None) -> dict[str, Any]:
    path = path or _paths.CONFIG_PATH
    config = load_config(path)
    config[key] = value
    save_config(config, path)
    return config


def get_notebook_path(path: Path | None = None) -> Path | None:
    """Return the notebook path from AYA_NOTEBOOK_PATH env var or config.json."""
    path = path or _paths.CONFIG_PATH
    env = os.environ.get("AYA_NOTEBOOK_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    config = load_config(path)
    raw = config.get("notebook_path")
    return Path(raw).expanduser() if raw else None
