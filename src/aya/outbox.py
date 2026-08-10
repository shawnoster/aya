"""Outbound-send bookkeeping: idempotency cache, delivery outcome, sent log.

These are domain operations, not presentation, but they lived in ``cli.py`` —
so ``mcp_server.py`` reached across and imported four private names from the
CLI. That made the two presentation layers mutually dependent, with the import
cycle only survivable because both directions were lazy in-function imports.

Nothing here renders or exits; callers decide how to show the result.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aya import paths as _paths
from aya.identity import Profile, _assert_valid_ulid
from aya.packet import Packet

logger = logging.getLogger(__name__)

__all__ = [
    "NOT_INGESTED_HINT",
    "check_idempotency",
    "delivery_from_report",
    "delivery_summary",
    "record_idempotency",
    "record_sent",
]

# A packet listed by `aya inbox` is not yet readable, and a bare "not found"
# reads like a wrong ID or a bug when the packet is plainly visible in the
# inbox. Always name the remedy.
NOT_INGESTED_HINT = (
    "Packet '{packet_id}' is not ingested. If `aya inbox` lists it, it is still "
    "pending — run `aya receive --auto-ingest` to ingest it first, then retry."
)


def _idempotency_key_hash(key: str) -> str:
    """Hash the idempotency key so raw secrets aren't stored on disk."""
    return hashlib.sha256(key.encode()).hexdigest()


def check_idempotency(key: str) -> dict[str, Any] | None:
    """Return the cached result for *key* if it was used within 24h, else None."""
    if not _paths.SENT_CACHE.exists():
        return None
    hashed = _idempotency_key_hash(key)
    try:
        with _paths.SENT_CACHE.open() as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            raw = json.loads(f.read())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    entry = raw.get(hashed)
    if not isinstance(entry, dict):
        return None
    try:
        if datetime.fromisoformat(entry["sent_at"]) > datetime.now(UTC) - timedelta(hours=24):
            return entry
    except (KeyError, ValueError, TypeError):
        return None
    return None


def record_idempotency(key: str, packet_id: str, event_id: str) -> None:
    """Record a sent packet for dedup. Atomic write under an exclusive lock."""
    hashed = _idempotency_key_hash(key)
    _paths.SENT_CACHE.parent.mkdir(parents=True, exist_ok=True)

    try:
        with _paths.SENT_CACHE.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                raw = json.loads(f.read() or "{}")
                cache = raw if isinstance(raw, dict) else {}
            except json.JSONDecodeError:
                cache = {}

            cache[hashed] = {
                "packet_id": packet_id,
                "event_id": event_id,
                "sent_at": datetime.now(UTC).isoformat(),
            }
            # Prune entries older than 24 hours
            cutoff = datetime.now(UTC) - timedelta(hours=24)
            pruned: dict[str, object] = {}
            for k, v in cache.items():
                if not isinstance(v, dict):
                    continue
                try:
                    if datetime.fromisoformat(str(v.get("sent_at", ""))) > cutoff:
                        pruned[k] = v
                except (ValueError, TypeError):
                    continue
            cache = pruned

            # Atomic write: temp file → Path.replace
            fd, tmp = tempfile.mkstemp(dir=str(_paths.SENT_CACHE.parent), suffix=".tmp")
            try:
                encoded = json.dumps(cache, indent=2).encode()
                total = 0
                while total < len(encoded):
                    total += os.write(fd, encoded[total:])
                os.fsync(fd)
                os.close(fd)
                Path(tmp).replace(_paths.SENT_CACHE)
                with suppress(OSError):
                    _paths.SENT_CACHE.chmod(0o600)
            except Exception:
                with suppress(OSError):
                    os.close(fd)
                with suppress(OSError):
                    Path(tmp).unlink()
                raise
    except OSError:
        logger.debug("Failed to record idempotency key %s", key, exc_info=True)


def delivery_from_report(
    report: list[dict[str, object]], relay_urls: list[str]
) -> tuple[list[str], list[dict[str, object]]]:
    """Split a RelayClient publish report into (accepted URLs, failures).

    Falls back to "all accepted" for clients that predate the report attribute.
    """
    if not report:
        return list(relay_urls), []
    ok = [str(r["url"]) for r in report if r.get("ok")]
    failed = [{"url": r["url"], "error": r.get("error")} for r in report if not r.get("ok")]
    return ok, failed


def delivery_summary(relays_ok: list[str], attempted: int) -> str:
    """One-line delivery summary that never overstates reach.

    Reads as "<first accepting relay> (N of M relays)" so a partial failure is
    visible in the summary itself, not only in ``relays_failed``.
    """
    if not relays_ok:
        return f"none (0 of {attempted} relays)"
    if len(relays_ok) == attempted == 1:
        return relays_ok[0]
    return f"{relays_ok[0]} ({len(relays_ok)} of {attempted} relays)"


def record_sent(
    p: Profile,
    profile_path: Path,
    packet: Packet,
    *,
    to_did: str,
    to_label: str,
    event_id: str,
    relays_ok: list[str],
    relays_failed: list[dict[str, object]],
) -> None:
    """Append to the outbound log and persist the body for later ``aya read``."""
    p.sent_ids.append(
        {
            "id": packet.id,
            "sent_at": packet.sent_at,
            "to_did": to_did,
            "to_label": to_label,
            "intent": packet.intent,
            "event_id": event_id,
            "relays_ok": relays_ok,
            "relays_failed": relays_failed,
        }
    )
    p.save(profile_path)
    # Best-effort body persistence so `aya read <id>` works on sent packets too.
    try:
        _assert_valid_ulid(packet.id)
        _paths.PACKETS_DIR.mkdir(parents=True, exist_ok=True)
        packet_file = _paths.PACKETS_DIR / f"{packet.id}.json"
        packet_file.write_text(packet.to_json())
        with suppress(OSError):
            packet_file.chmod(0o600)
    except Exception:
        logger.debug("Could not persist sent packet body for %s", packet.id, exc_info=True)
