"""Global test isolation.

Without this, the suite writes into the developer's real ``~/.aya`` — and
``aya.ingest`` unlinks anything in ``PACKETS_DIR`` older than 7 days, so
running the tests destroyed real packets.

One env var is enough now that ``aya.paths`` resolves on access. It previously
took an eight-entry alias table, because modules that did
``from aya.paths import X`` at import time held a snapshot that patching
``aya.paths`` could not reach.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_aya_home(tmp_path, monkeypatch):
    """Point every aya data path at a per-test scratch directory.

    Autouse on purpose: opt-in isolation is what let the leak persist for so
    long. Tests needing a specific path still override it themselves.
    """
    import aya.paths as paths
    import aya.scheduler as scheduler

    home = tmp_path / "aya_home"
    (home / "packets").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AYA_HOME", str(home))
    _drop_pinned_paths(paths, scheduler)
    try:
        yield home
    finally:
        # monkeypatch.setattr on a name served by module __getattr__ reads the
        # current value, then *restores it as a real global* on teardown — which
        # shadows the dynamic lookup and pins one test's tmp path for the rest
        # of the session. Undo that here so path patching stays test-local.
        _drop_pinned_paths(paths, scheduler)


def _drop_pinned_paths(paths, scheduler) -> None:
    for name in paths._CONSTANTS:
        paths.__dict__.pop(name, None)
    for name in scheduler._LAZY_ATTRS:
        scheduler.__dict__.pop(name, None)
