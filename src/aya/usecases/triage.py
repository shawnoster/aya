"""Deciding which fetched packets a surface should act on.

Both ``receive`` and ``inbox`` exist twice — once on the CLI, once over MCP —
and each had grown its own filter. The four copies did not agree: the drop
filter was applied in the two ``inbox`` paths and neither ``receive`` path, so
``aya drop`` hid a packet from the listing and then let the very next poll
re-ingest it.

One function, four callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from aya.entities.packet import Packet

__all__ = ["Triage", "triage"]


@dataclass(frozen=True)
class Triage:
    """Fetched packets sorted into what a caller should do with them."""

    fresh: list[Packet] = field(default_factory=list)
    """Not seen before, not dropped, signature verified — act on these."""

    bad_signature: list[Packet] = field(default_factory=list)
    """Failed verification. Surface the IDs; never ingest."""

    misrouted: list[tuple[Packet, str]] = field(default_factory=list)
    """Validly signed, but addressed to someone else or carried by a key that
    is not the sender's, each with the reason. Surface them; never ingest."""

    def __bool__(self) -> bool:
        return bool(self.fresh or self.bad_signature or self.misrouted)


def triage(
    packets: list[Packet],
    *,
    ingested: set[str],
    dropped: set[str],
    verify: bool = True,
    local_did: str | None = None,
    sender_keys: Mapping[str, set[str]] | None = None,
) -> Triage:
    """Split *packets* into actionable and rejected.

    Already-ingested and explicitly dropped packets are discarded silently:
    both are states the user has already resolved, and re-reporting them is
    what made ``drop`` look like it had not worked.

    *verify* is False for listing-only callers (``inbox``), which show what is
    waiting without asserting it is trustworthy.

    *local_did* rejects packets addressed to anyone else. A signature proves who
    wrote a packet, not who it was for, so without this any peer could re-send
    a packet meant for a third party and have it accepted from the original
    author.

    *sender_keys* maps a DID to the Nostr keys known for it. A packet from a
    known DID that arrived on any other key is rejected: the signature still
    holds, but someone other than the sender published it. Packets with no
    transport key recorded (built in memory rather than read from a relay) are
    not checked; the relay adapter always records one.

    The transport key is what the relay reported. For encrypted packets that
    is sound, because decryption fails under any other key. For plaintext
    packets it is only as honest as the relay until event signatures are
    verified on fetch.
    """
    fresh: list[Packet] = []
    bad: list[Packet] = []
    misrouted: list[tuple[Packet, str]] = []
    for packet in packets:
        if packet.id in dropped or packet.id in ingested:
            continue
        if verify and not packet.verify_from_did():
            bad.append(packet)
            continue
        reason = _misrouted(packet, local_did, sender_keys)
        if reason is not None:
            misrouted.append((packet, reason))
            continue
        fresh.append(packet)
    return Triage(fresh=fresh, bad_signature=bad, misrouted=misrouted)


def _misrouted(
    packet: Packet, local_did: str | None, sender_keys: Mapping[str, set[str]] | None
) -> str | None:
    """Why *packet* must not be accepted here, or None if it may be."""
    if local_did is not None and packet.to_did != local_did:
        return "addressed to another instance"
    if sender_keys is None or packet.transport_pubkey is None:
        return None
    known = sender_keys.get(packet.from_did)
    if known is None:
        return None
    if packet.transport_pubkey not in known:
        return "published by a key that isn't the sender's"
    return None
