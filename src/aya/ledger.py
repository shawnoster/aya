"""Packet ledgers: what has been ingested, sent, and dropped.

Split out of ``Profile`` because the two have opposite access patterns. The
profile holds private keys and changes rarely; the ledgers change on every
poll. Keeping them in one file meant each empty ``aya receive`` rewrote the
keystore just to update a cursor — the highest-frequency write against the
highest-value payload, with no lock.

They also have their own retention policy (7-day TTL), which is why ``save()``
had garbage collection wired into the key serializer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aya import paths as _paths
from aya.atomic import atomic_write_json, file_lock

logger = logging.getLogger(__name__)

LEDGER_TTL_DAYS = 7
SCHEMA_VERSION = 1


def _parse_iso(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class Ledger:
    """The three packet logs, persisted together in ``ledger.json``."""

    # {id, ingested_at, from_did?} — inbound dedup
    ingested: list[dict[str, str]] = field(default_factory=list)
    # Entries carry id, sent_at, to_did, to_label, intent, event_id and
    # per-relay delivery outcome.
    sent: list[dict[str, Any]] = field(default_factory=list)
    # Packet IDs the user explicitly suppressed
    dropped: list[str] = field(default_factory=list)

    @staticmethod
    def path() -> Path:
        return _paths.AYA_HOME / "ledger.json"

    @staticmethod
    def lock_path() -> Path:
        return _paths.AYA_HOME / ".ledger.lock"

    def prune(self, *, now: datetime | None = None) -> None:
        """Drop entries past the TTL.

        An entry whose timestamp is missing or unparseable is *kept*, not
        dropped: silently deleting an ``ingested`` entry causes the packet to
        be re-ingested, re-alerted, and re-written on the next poll.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(days=LEDGER_TTL_DAYS)

        def fresh(entry: dict[str, Any], stamp: str) -> bool:
            parsed = _parse_iso(entry.get(stamp))
            return True if parsed is None else parsed >= cutoff

        self.ingested = [e for e in self.ingested if fresh(e, "ingested_at")]
        self.sent = [e for e in self.sent if fresh(e, "sent_at")]

    @classmethod
    def load(cls, path: Path | None = None) -> Ledger:
        target = path or cls.path()
        if not target.exists():
            return cls()
        try:
            with file_lock(cls.lock_path(), shared=True):
                raw = json.loads(target.read_text())
        except (OSError, ValueError):
            logger.warning("Ledger at %s is unreadable; starting empty", target)
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls(
            ingested=[e for e in raw.get("ingested", []) if isinstance(e, dict) and "id" in e],
            sent=[e for e in raw.get("sent", []) if isinstance(e, dict) and "id" in e],
            dropped=[e for e in raw.get("dropped", []) if isinstance(e, str)],
        )

    def save(self, path: Path | None = None, *, now: datetime | None = None) -> None:
        target = path or self.path()
        self.prune(now=now)
        with file_lock(self.lock_path()):
            atomic_write_json(
                target,
                {
                    "schema_version": SCHEMA_VERSION,
                    "ingested": self.ingested,
                    "sent": self.sent,
                    "dropped": self.dropped,
                },
                mode=0o600,
            )
