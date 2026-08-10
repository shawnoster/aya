"""Centralized path resolution for aya data storage.

All aya data lives under AYA_HOME (~/.aya by default). Override with the
AYA_HOME environment variable.

Paths are resolved **on access**, not at import. The constants below are served
by :func:`__getattr__` from :func:`current`, so changing ``AYA_HOME`` takes
effect immediately. Previously they were computed once at import, which meant
a test had to ``importlib.reload`` this module — leaving every module that had
already done ``from aya.paths import X`` pointing at the old value, and the two
disagreeing for the rest of the process.

Prefer ``from aya import paths`` + ``paths.PROFILE_PATH`` over
``from aya.paths import PROFILE_PATH``: the second form snapshots the value at
import and cannot be redirected afterwards.

Workspace-relative paths (CLAUDE.md, AGENTS.md, daily notes) are NOT defined
here — those belong to the notebook repo, not to aya.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

__all__ = ["AyaPaths", "current", "default_home"]


def default_home() -> Path:
    """Resolve AYA_HOME from the environment, falling back to ``~/.aya``."""
    env = os.environ.get("AYA_HOME")
    return Path(env).expanduser() if env else Path.home() / ".aya"


@dataclass(frozen=True)
class AyaPaths:
    """Every on-disk location aya owns, derived from one root.

    Pass one of these explicitly to make a component's storage a parameter
    rather than ambient state.
    """

    home: Path

    @property
    def profile(self) -> Path:
        return self.home / "profile.json"

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def scheduler(self) -> Path:
        return self.home / "scheduler.json"

    @property
    def alerts(self) -> Path:
        return self.home / "alerts.json"

    @property
    def activity(self) -> Path:
        return self.home / "activity.json"

    @property
    def lock(self) -> Path:
        return self.home / ".scheduler.lock"

    @property
    def claims(self) -> Path:
        return self.home / "claims"

    @property
    def sent_cache(self) -> Path:
        return self.home / "sent_cache.json"

    @property
    def log_state(self) -> Path:
        return self.home / "log_state.json"

    @property
    def packets(self) -> Path:
        return self.home / "packets"

    @property
    def session_lock(self) -> Path:
        return self.home / "session.lock"

    @property
    def registered_crons(self) -> Path:
        return self.home / "session_registered_crons.json"


def current() -> AyaPaths:
    """Paths for the current AYA_HOME. Cheap; safe to call per access."""
    return AyaPaths(default_home())


# Legacy constant names, resolved dynamically. Keeping them means the ~60
# existing call sites keep working while new code can take an AyaPaths.
_CONSTANTS: dict[str, str] = {
    "AYA_HOME": "home",
    "PROFILE_PATH": "profile",
    "CONFIG_PATH": "config",
    "SCHEDULER_FILE": "scheduler",
    "ALERTS_FILE": "alerts",
    "ACTIVITY_FILE": "activity",
    "LOCK_FILE": "lock",
    "CLAIMS_DIR": "claims",
    "SENT_CACHE": "sent_cache",
    "LOG_STATE_FILE": "log_state",
    "PACKETS_DIR": "packets",
}


if TYPE_CHECKING:
    # Declared for type checkers only; served at runtime by __getattr__ below.
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


def __getattr__(name: str) -> Any:
    field = _CONSTANTS.get(name)
    if field is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(current(), field)


def __dir__() -> list[str]:
    return sorted([*__all__, *_CONSTANTS])
