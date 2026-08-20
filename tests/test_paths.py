"""Tests for AYA_HOME resolution."""

from __future__ import annotations

import pytest


class TestRealHomeIsRefusedUnderTest:
    """The isolation fixture is directory-scoped; this is not.

    `tests/conftest.py` sets AYA_HOME for every test, but only for code run from
    `tests/`. A probe or script run from elsewhere reached the developer's real
    home and wrote to it — which happened, overwriting a real ledger and losing
    the sent log and drop list, with nothing failing at the time.
    """

    def test_the_fallback_raises_when_pytest_is_running(self, monkeypatch):
        from aya.adapters.paths import RealAyaHomeUnderTestError, default_home

        monkeypatch.delenv("AYA_HOME", raising=False)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe (call)")
        with pytest.raises(RealAyaHomeUnderTestError, match="Refusing to use the real"):
            default_home()

    def test_an_explicit_home_is_always_honoured(self, monkeypatch, tmp_path):
        """The guard must not block a deliberately chosen directory."""
        from aya.adapters.paths import default_home

        monkeypatch.setenv("AYA_HOME", str(tmp_path / "chosen"))
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe (call)")
        assert default_home() == tmp_path / "chosen"

    def test_outside_pytest_the_fallback_still_works(self, monkeypatch):
        """Production must be unaffected: no PYTEST_CURRENT_TEST, no guard."""
        from pathlib import Path

        from aya.adapters.paths import default_home

        monkeypatch.delenv("AYA_HOME", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        assert default_home() == Path.home() / ".aya"
