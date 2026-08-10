"""Centralized path resolution for aya data storage.

All aya data lives under AYA_HOME (~/.aya by default). Override with the
AYA_HOME environment variable.

Paths resolve **on access**, not at import: the names below are served by
:func:`__getattr__`, so changing ``AYA_HOME`` takes effect immediately.
Computing them once at import meant a caller had to ``importlib.reload`` this
module, which left every module that had already done
``from aya.paths import X`` pointing at the old value.

Prefer ``from aya import paths`` + ``paths.PROFILE_PATH`` over
``from aya.paths import PROFILE_PATH``: the second form snapshots the value at
import and cannot be redirected afterwards.

Workspace-relative paths (CLAUDE.md, AGENTS.md, daily notes) are NOT defined
here — those belong to the notebook repo, not to aya.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

__all__ = ["default_home"]

# name → filename under AYA_HOME. AYA_HOME itself maps to the root.
_CONSTANTS: dict[str, str] = {
    "AYA_HOME": "",
    "PROFILE_PATH": "profile.json",
    "CONFIG_PATH": "config.json",
    "SCHEDULER_FILE": "scheduler.json",
    "ALERTS_FILE": "alerts.json",
    "ACTIVITY_FILE": "activity.json",
    "LOCK_FILE": ".scheduler.lock",
    "CLAIMS_DIR": "claims",
    "SENT_CACHE": "sent_cache.json",
    "LOG_STATE_FILE": "log_state.json",
    "PACKETS_DIR": "packets",
}


def default_home() -> Path:
    """Resolve AYA_HOME from the environment, falling back to ``~/.aya``."""
    env = os.environ.get("AYA_HOME")
    return Path(env).expanduser() if env else Path.home() / ".aya"


if TYPE_CHECKING:
    # Declared for type checkers only; served at runtime by __getattr__.
    AYA_HOME: Path
    PROFILE_PATH: Path
    CONFIG_PATH: Path
    SCHEDULER_FILE: Path
    ALERTS_FILE: Path
    ACTIVITY_FILE: Path
    LOCK_FILE: Path
    CLAIMS_DIR: Path
    SENT_CACHE: Path
    LOG_STATE_FILE: Path
    PACKETS_DIR: Path


def __getattr__(name: str) -> Path:
    leaf = _CONSTANTS.get(name)
    if leaf is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    home = default_home()
    return home / leaf if leaf else home


def __dir__() -> list[str]:
    return sorted([*__all__, *_CONSTANTS])
