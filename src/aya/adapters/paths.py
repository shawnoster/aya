"""Centralized path resolution for aya data storage.

All aya data lives under AYA_HOME (~/.aya by default). Override with the
AYA_HOME environment variable.

Paths resolve **on access**, not at import: the names below are served by
:func:`__getattr__`, so changing ``AYA_HOME`` takes effect immediately.
Computing them once at import meant a caller had to ``importlib.reload`` this
module, which left every module that had already done
``from aya.adapters.paths import X`` pointing at the old value.

Prefer ``from aya.adapters import paths`` + ``paths.PROFILE_PATH`` over
``from aya.adapters.paths import PROFILE_PATH``: the second form snapshots the value at
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


class RealAyaHomeUnderTestError(RuntimeError):
    """Raised when test code would resolve the developer's real AYA_HOME."""

    def __init__(self) -> None:
        super().__init__(
            "Refusing to use the real AYA_HOME from a test: set the AYA_HOME "
            "environment variable to a temporary directory. Code run outside "
            "tests/ does not get conftest's isolate_aya_home fixture, so it would "
            "read and write the developer's own aya data."
        )


def default_home() -> Path:
    """Resolve AYA_HOME from the environment, falling back to ``~/.aya``.

    Under pytest the fallback is refused rather than served. ``tests/conftest.py``
    sets AYA_HOME for every test, but only for code run from ``tests/`` — a script
    or probe run from anywhere else reaches the developer's real home and writes
    to it. That is not hypothetical: it overwrote a real ledger, losing the sent
    log and the drop list, and nothing failed at the time.

    Raising here rather than in each writer covers every path under the home —
    profile, scheduler, packets — and fails at resolution, before anything is
    created. Set AYA_HOME explicitly to run against a chosen directory.
    """
    env = os.environ.get("AYA_HOME")
    if env:
        return Path(env).expanduser()
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RealAyaHomeUnderTestError
    return Path.home() / ".aya"


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
