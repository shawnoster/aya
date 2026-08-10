"""The clock seam: one patch freezes time everywhere it matters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

from aya.adapters import clock


class TestClock:
    def test_now_defaults_to_utc(self):
        assert clock.now().tzinfo is UTC
        assert clock.utcnow().tzinfo is UTC

    def test_now_honours_a_timezone(self):
        tz = timezone(timedelta(hours=5, minutes=30))
        assert clock.now(tz).tzinfo == tz

    def test_now_advances(self):
        assert clock.now() <= clock.now()


class TestSeam:
    """What this replaced: patching the datetime *class* and re-attaching
    fromisoformat so the rest of the module kept working."""

    FROZEN = datetime(2026, 3, 27, 10, 0, tzinfo=UTC)

    def test_one_patch_freezes_the_scheduler(self):
        from aya.scheduler.core import add_reminder

        with patch("aya.adapters.clock.now", return_value=self.FROZEN):
            item = add_reminder("test", "in 1 hour")
        assert item["created_at"] == self.FROZEN.isoformat()

    def test_one_patch_freezes_the_outbound_log(self):
        from aya.adapters.outbox import _idempotency_key_hash

        # Sanity: the hash is time-independent, so a frozen clock must not
        # change it — guards against over-broad patching.
        with patch("aya.adapters.clock.now", return_value=self.FROZEN):
            frozen = _idempotency_key_hash("k")
        assert frozen == _idempotency_key_hash("k")

    def test_patching_does_not_break_datetime_parsing(self):
        """The old mechanism broke fromisoformat unless re-attached by hand."""
        with patch("aya.adapters.clock.now", return_value=self.FROZEN):
            assert datetime.fromisoformat("2026-01-01T00:00:00+00:00").year == 2026
