"""The system clock, in one place.

Reading the time is infrastructure, and scattering ``datetime.now()`` across
forty call sites made most time-dependent behaviour untestable — you could
only reach it by patching ``datetime`` itself. ``scheduler.core`` had grown a
``_dt_now`` shim whose only job was to make one such patch propagate after a
module split, and ``scheduler/__init__`` re-exported ``datetime`` with the
comment "exposed for test monkeypatching". Production indirection serving a
test mechanism.

Call ``clock.now()`` rather than ``datetime.now()``, and prefer an injectable
``now: datetime | None = None`` parameter on anything whose behaviour depends
on the answer — the convention already used by ``parse_due``, ``is_idle`` and
friends. Freezing time in a test is then a single patch here, or no patch at
all.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo

__all__ = ["now", "utcnow"]


def now(tz: tzinfo | None = None) -> datetime:
    """Current time in *tz*, or UTC when none is given."""
    return datetime.now(tz) if tz is not None else datetime.now(UTC)


def utcnow() -> datetime:
    """Current UTC time. Shorthand for ``now()``."""
    return datetime.now(UTC)
