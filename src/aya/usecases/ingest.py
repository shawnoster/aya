"""Packet ingestion, shared by the CLI and the MCP server.

Split three ways so each part is separately testable and reusable:

* :func:`persist_packet` — writes the body and prunes; returns whether it
  landed, instead of swallowing the outcome.
* :func:`record_seed_alert` — the scheduler side effect.
* :func:`ingest` — orchestration, with rendering supplied by the caller.

Rendering is injected rather than performed here: this module used to build
its own ``Console``, which made the output impossible to capture in a test and
pulled a presentation dependency into a data path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from aya.adapters import paths as _paths
from aya.entities.packet import Packet

logger = logging.getLogger(__name__)

SEED_CONTENT_TYPE = "application/aya-seed"
_PACKET_TTL_SECONDS = 7 * 86400


def is_seed(packet: Packet) -> bool:
    return bool(packet.content_type == SEED_CONTENT_TYPE)


def seed_fields(packet: Packet) -> dict[str, Any]:
    """Seed payload as a dict, or empty for non-seed packets."""
    if not is_seed(packet):
        return {}
    return packet.content if isinstance(packet.content, dict) else {}


def persist_packet(packet: Packet, *, now: datetime | None = None) -> bool:
    """Write *packet* to PACKETS_DIR and prune expired bodies.

    Returns True when the body is on disk. Callers use this to decide whether
    to advance their ingest cursor — marking a packet ingested whose body
    failed to write makes it unreadable and invisible to the inbox.
    """
    try:
        from aya.entities.identity import _assert_valid_ulid

        # Defence in depth: packets come from the network. Reject anything that
        # could escape PACKETS_DIR via path separators before building the path.
        _assert_valid_ulid(packet.id)

        _paths.PACKETS_DIR.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            _paths.PACKETS_DIR.chmod(0o700)
        packet_file = _paths.PACKETS_DIR / f"{packet.id}.json"
        packet_file.write_text(packet.to_json())
        with suppress(OSError):
            packet_file.chmod(0o600)

        cutoff = (now or datetime.now(UTC)).timestamp() - _PACKET_TTL_SECONDS
        for old in _paths.PACKETS_DIR.glob("*.json"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
            except OSError:
                continue
        return packet_file.exists()
    except Exception:
        logger.debug("Failed to persist packet %s", packet.id, exc_info=True)
        return False


def record_seed_alert(packet: Packet) -> None:
    """Queue a seed packet as an unseen alert for the next session start.

    Needed because the SessionStart hook ingests asynchronously, where stdout
    is not captured — without this the seed would never surface.
    """
    from aya.scheduler import add_seed_alert

    seed = seed_fields(packet)
    add_seed_alert(
        intent=packet.intent,
        opener=seed.get("opener", ""),
        context_summary=seed.get("context_summary", ""),
        open_questions=seed.get("open_questions", []),
        from_label=packet.from_did[:16],
        packet_id=packet.id,
    )


def ingest(
    packet: Packet,
    *,
    quiet: bool = False,
    render: Callable[[Packet], None] | None = None,
) -> bool:
    """Ingest a packet: surface it, alert on seeds, persist the body.

    Pass ``quiet=True`` to suppress rendering entirely — required on the MCP
    stdio path, where stray stdout corrupts JSON-RPC. *render* supplies the
    presentation; without one, nothing is drawn.

    Returns whether the body was persisted.
    """
    if not quiet and render is not None:
        render(packet)
    if is_seed(packet):
        record_seed_alert(packet)
    return persist_packet(packet)
