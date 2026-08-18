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


@pytest.fixture(autouse=True)
def isolate_crontab(monkeypatch):
    """Keep the suite off the real crontab of whoever runs it.

    ``install_scheduler`` and ``uninstall_scheduler`` shell out to ``crontab -l``
    and ``crontab -``. A test that exercises either without patching subprocess
    edits the crontab of whoever runs the suite, deleting their
    ``aya-scheduler-tick`` entry and with it out-of-session polling. Nothing in
    a test run reports that, so the damage is silent and survives the run.

    Only ``crontab`` invocations are intercepted, against a per-test in-memory
    crontab; every other subprocess call passes through untouched, so this does
    not blunt tests that shell out for other reasons. A test that wants to drive
    the crontab explicitly can still patch ``subprocess.run`` itself — an inner
    patch wins and unwinds back to this one.
    """
    import subprocess as _sp

    from aya.adapters import install as _install

    state = {"text": ""}
    real_run = _sp.run

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "crontab":
            head = list(cmd[:2])
            if head == ["crontab", "-l"]:
                return _sp.CompletedProcess(cmd, 0, stdout=state["text"], stderr="")
            if head == ["crontab", "-"]:
                state["text"] = kwargs.get("input") or ""
                return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if head == ["crontab", "-r"]:
                state["text"] = ""
                return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            # Anything else is a crontab call this fake does not model. Faking
            # success would let a test pass against behaviour that does not
            # exist on a real system, so it fails and names itself instead.
            raise AssertionError(
                f"isolate_crontab does not model {cmd!r}. Teach the fixture the "
                f"new crontab usage rather than letting the suite fake success."
            )
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(_install.subprocess, "run", fake_run)
    return state
