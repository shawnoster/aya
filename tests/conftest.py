"""Global test isolation.

Without this, the suite writes into the developer's real ``~/.aya`` — and
``aya.ingest`` unlinks anything in ``PACKETS_DIR`` older than 7 days, so
running the tests destroys real packets.

Isolation is awkward because ``aya.paths`` publishes module-level constants
that callers bind three different ways:

1. ``from aya.paths import X`` at module scope — early-bound, so the *alias*
   must be patched, not ``aya.paths.X``.
2. ``from aya import paths as _paths`` then ``_paths.X`` — late-bound, so
   patching ``aya.paths.X`` is enough.
3. function-local ``from aya.paths import X`` — resolved per call, also fine.

Style 1 is why the alias table below exists. Removing it is the point of the
paths-injection work; until then this fixture is the single place that knows
the full set.
"""

from __future__ import annotations

import pytest

# Style-1 aliases: (module, attribute, paths-attribute it copied).
_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("aya.config", "CONFIG_PATH", "CONFIG_PATH"),
    ("aya.profile", "PROFILE_PATH", "PROFILE_PATH"),
    ("aya.cli", "CONFIG_PATH", "CONFIG_PATH"),
    ("aya.cli", "PROFILE_PATH", "PROFILE_PATH"),
    ("aya.cli", "DEFAULT_PROFILE", "PROFILE_PATH"),
    ("aya.log", "LOG_STATE_FILE", "LOG_STATE_FILE"),
    ("aya.log", "PACKETS_DIR", "PACKETS_DIR"),
    ("aya.status", "PROFILE", "PROFILE_PATH"),
)

_PATH_ATTRS: tuple[tuple[str, str], ...] = (
    ("PROFILE_PATH", "profile.json"),
    ("CONFIG_PATH", "config.json"),
    ("SCHEDULER_FILE", "scheduler.json"),
    ("ALERTS_FILE", "alerts.json"),
    ("ACTIVITY_FILE", "activity.json"),
    ("LOCK_FILE", ".scheduler.lock"),
    ("CLAIMS_DIR", "claims"),
    ("SENT_CACHE", "sent_cache.json"),
    ("LOG_STATE_FILE", "log_state.json"),
    ("PACKETS_DIR", "packets"),
)


@pytest.fixture(autouse=True)
def isolate_aya_home(tmp_path, monkeypatch):
    """Point every aya data path at a per-test scratch directory.

    Autouse: opting in per-file is what let the leak persist. Tests that need
    the real path for a specific file still override it themselves.
    """
    import importlib

    import aya.paths as paths
    import aya.scheduler as scheduler

    home = tmp_path / "aya_home"
    (home / "packets").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AYA_HOME", str(home))
    monkeypatch.setattr(paths, "AYA_HOME", home, raising=False)
    resolved = {attr: home / leaf for attr, leaf in _PATH_ATTRS}
    for attr, value in resolved.items():
        monkeypatch.setattr(paths, attr, value, raising=False)

    for module_name, attr, source in _ALIASES:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, attr, resolved[source], raising=False)

    # aya.scheduler.__getattr__ caches resolved paths into package globals on
    # first read and never invalidates them, so one early read pins the real
    # path for the rest of the process. Clear before and after.
    lazy = tuple(scheduler._LAZY_ATTRS)
    for name in lazy:
        scheduler.__dict__.pop(name, None)
    try:
        yield home
    finally:
        for name in lazy:
            scheduler.__dict__.pop(name, None)
