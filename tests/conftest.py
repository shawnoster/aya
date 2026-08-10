"""Global test isolation.

Without this, the suite writes into the developer's real ``~/.aya`` — and
``aya.ingest`` unlinks anything in ``PACKETS_DIR`` older than 7 days, so
running the tests destroyed real packets.

One env var is enough now that ``aya.adapters.paths`` resolves on access. It previously
took an eight-entry alias table, because modules that did
``from aya.adapters.paths import X`` at import time held a snapshot that patching
``aya.adapters.paths`` could not reach.
"""

from __future__ import annotations

import os

import pytest

# Rich decides on colour when its Console is built, which happens at import
# time — so this has to be set before any aya module loads, not in a fixture.
# CI often forces colour, and Rich styles the two dashes of a long option
# separately, so `--message` stops being a literal substring and assertions on
# rendered text pass locally while failing in CI.
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)


@pytest.fixture(autouse=True)
def isolate_aya_home(tmp_path, monkeypatch):
    """Point every aya data path at a per-test scratch directory.

    Autouse on purpose: opt-in isolation is what let the leak persist for so
    long. Tests needing a specific path still override it themselves.
    """
    import aya.adapters.paths as paths
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
