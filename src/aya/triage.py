"""Deciding which fetched packets a surface should act on.

Both ``receive`` and ``inbox`` exist twice — once on the CLI, once over MCP —
and each had grown its own filter. The four copies did not agree: the drop
filter was applied in the two ``inbox`` paths and neither ``receive`` path, so
``aya drop`` hid a packet from the listing and then let the very next poll
re-ingest it.

One function, four callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aya.packet import Packet

__all__ = ["Triage", "triage"]


@dataclass(frozen=True)
class Triage:
    """Fetched packets sorted into what a caller should do with them."""

    fresh: list[Packet] = field(default_factory=list)
    """Not seen before, not dropped, signature verified — act on these."""

    bad_signature: list[Packet] = field(default_factory=list)
    """Failed verification. Surface the IDs; never ingest."""

    def __bool__(self) -> bool:
        return bool(self.fresh or self.bad_signature)


def triage(
    packets: list[Packet],
    *,
    ingested: set[str],
    dropped: set[str],
    verify: bool = True,
) -> Triage:
    """Split *packets* into actionable and rejected.

    Already-ingested and explicitly dropped packets are discarded silently:
    both are states the user has already resolved, and re-reporting them is
    what made ``drop`` look like it had not worked.

    *verify* is False for listing-only callers (``inbox``), which show what is
    waiting without asserting it is trustworthy.
    """
    fresh: list[Packet] = []
    bad: list[Packet] = []
    for packet in packets:
        if packet.id in dropped or packet.id in ingested:
            continue
        if verify and not packet.verify_from_did():
            bad.append(packet)
            continue
        fresh.append(packet)
    return Triage(fresh=fresh, bad_signature=bad)
