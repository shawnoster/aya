"""The four relay operations, once.

``send``, ``ack``, ``receive`` and ``inbox`` existed twice — a Typer command
and an MCP handler each carrying its own copy of packet construction, signing,
publishing, cursor advancement and ledger bookkeeping. The copies drifted:
read receipts fired on one of four ingest paths, one surface encrypted acks
and the other didn't, one honoured ``--dismiss`` and the other hardcoded it.

Everything here is surface-agnostic. It never prints, never exits, and raises
typed errors that callers map to their own reporting. What stays above:
argument parsing, rendering, exit codes, and the interactive decision about
whether to ingest an individual packet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aya.adapters import clock
from aya.adapters import relay as _relay
from aya.adapters.outbox import (
    NOT_INGESTED_HINT,
    check_idempotency,
    delivery_from_report,
    record_idempotency,
    record_sent,
)
from aya.adapters.profile_store import save_profile
from aya.adapters.relay import RelayClient
from aya.entities.identity import Profile, _assert_valid_ulid
from aya.entities.packet import ConflictStrategy, ContentType, Packet, human_age
from aya.usecases.ingest import ingest as ingest_packet
from aya.usecases.resolve import (
    NoNostrPubkeyError,
    label_for_authenticated_sender,
    label_for_did,
    nostr_pubkey_for,
    resolve_instance,
    resolve_recipient,
    resolve_relays,
)
from aya.usecases.triage import triage

logger = logging.getLogger(__name__)

__all__ = [
    "AckResult",
    "AmbiguousAckRecipientError",
    "Decision",
    "PacketBody",
    "PollResult",
    "SendFailedError",
    "SendResult",
    "ack",
    "inbox",
    "ingest_if_trusted",
    "receive",
    "send",
]


# ── errors ────────────────────────────────────────────────────────────────────


class RelayOpError(Exception):
    """Base for failures a surface should report rather than crash on."""


class SendFailedError(RelayOpError):
    """No relay accepted the packet."""

    def __init__(self, relays: list[str]) -> None:
        super().__init__("Send failed — event could not be published to relay(s).")
        self.relays = relays


class PacketNotIngestedError(RelayOpError):
    """The packet is not in the local store, so it cannot be acted on."""

    def __init__(self, packet_id: str) -> None:
        super().__init__(NOT_INGESTED_HINT.format(packet_id=packet_id))
        self.packet_id = packet_id


class AmbiguousPrefixError(RelayOpError):
    def __init__(self, prefix: str, matches: int) -> None:
        super().__init__(f"Ambiguous prefix '{prefix}' — matches {matches} packets.")
        self.prefix = prefix
        self.matches = matches


class AmbiguousAckRecipientError(RelayOpError):
    """The original sender is unknown and more than one peer could be meant."""

    def __init__(self, available: list[str]) -> None:
        super().__init__(
            "Cannot determine ACK recipient — the packet has no recorded sender "
            f"and several peers are trusted: {', '.join(available)}."
        )
        self.available = available


class NoTrustedPeerError(RelayOpError):
    def __init__(self) -> None:
        super().__init__("No trusted peers with a Nostr pubkey found. Pair first: 'aya pair'.")


# ── inputs ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PacketBody:
    """What a packet carries, independent of how the surface collected it."""

    kind: str  # "markdown" | "seed" | "files"
    content: str = ""
    opener: str = ""
    context_summary: str = ""
    files: tuple[str, ...] = ()
    context: str | None = None
    conflict: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS

    @classmethod
    def markdown(cls, content: str, *, context: str | None = None, **kw: Any) -> PacketBody:
        return cls(kind="markdown", content=content, context=context, **kw)

    @classmethod
    def seed(cls, opener: str, *, context_summary: str = "", **kw: Any) -> PacketBody:
        return cls(kind="seed", opener=opener, context_summary=context_summary, **kw)

    @classmethod
    def from_files(cls, paths: list[str], *, context: str | None = None) -> PacketBody:
        return cls(kind="files", files=tuple(paths), context=context)

    def build(self, *, from_did: str, to_did: str, intent: str) -> Packet:
        if self.kind == "seed":
            return Packet.as_seed(
                from_did=from_did,
                to_did=to_did,
                intent=intent,
                opener=self.opener,
                context_summary=self.context_summary,
            )
        if self.kind == "files":
            return Packet.from_files(
                paths=list(self.files),
                from_did=from_did,
                to_did=to_did,
                intent=intent,
                context=self.context,
            )
        return Packet(
            from_did=from_did,
            to_did=to_did,
            intent=intent,
            context=self.context,
            content_type=ContentType.MARKDOWN,
            content=self.content,
            conflict_strategy=self.conflict,
        )


class Decision(StrEnum):
    """What a caller wants done with one fetched packet."""

    INGEST = "ingest"
    SKIP_UNTRUSTED = "skip_untrusted"
    DECLINE = "decline"


def ingest_if_trusted(_packet: Packet, trusted: bool) -> Decision:
    """Default policy: take trusted senders, hold everyone else."""
    return Decision.INGEST if trusted else Decision.SKIP_UNTRUSTED


# ── results ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SendResult:
    packet: Packet | None
    event_id: str
    to_did: str
    to_label: str
    relays_ok: list[str] = field(default_factory=list)
    relays_failed: list[dict[str, Any]] = field(default_factory=list)
    cached: bool = False

    @property
    def partial(self) -> bool:
        """True when some relay rejected. `publish` succeeds if *any* accepts."""
        return bool(self.relays_failed)

    @property
    def attempted(self) -> int:
        return len(self.relays_ok) + len(self.relays_failed)


@dataclass(frozen=True)
class AckResult(SendResult):
    in_reply_to: str = ""


@dataclass(frozen=True)
class PollResult:
    packets: list[dict[str, Any]] = field(default_factory=list)
    instance: str = ""
    relays: list[str] = field(default_factory=list)
    relay_reachable: bool = True
    bad_signature: list[Packet] = field(default_factory=list)

    def envelope(self) -> dict[str, Any]:
        """The wire shape both surfaces return."""
        return {
            "packets": self.packets,
            "instance": self.instance,
            "relays": list(self.relays),
            "relay_reachable": self.relay_reachable,
        }


ClientFactory = Callable[..., RelayClient]


def _factory(client_factory: ClientFactory | None) -> ClientFactory:
    """Resolve the relay client at call time.

    Binding ``RelayClient`` as a default argument would freeze it at import,
    so a caller patching ``aya.relay.RelayClient`` would never be seen.
    """
    return client_factory or _relay.RelayClient


def _now_iso(now: datetime | None = None) -> str:
    return (now or clock.now(UTC)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _publish(
    local: Any,
    signed: Packet,
    recipient_pubkey: str,
    relay_urls: list[str],
    *,
    encrypt: bool,
    client_factory: ClientFactory | None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    make = _factory(client_factory)
    client = make(relay_urls, local.nostr_private_hex, local.nostr_public_hex)
    try:
        event_id = await client.publish(signed, recipient_pubkey, encrypt=encrypt)
    except Exception as exc:
        logger.exception("Relay publish failed")
        raise SendFailedError(relay_urls) from exc
    relays_ok, relays_failed = delivery_from_report(
        getattr(client, "last_publish_report", []), relay_urls
    )
    return event_id, relays_ok, relays_failed


# ── operations ────────────────────────────────────────────────────────────────


async def send(
    profile: Profile,
    profile_path: Path,
    *,
    to: str,
    intent: str,
    body: PacketBody,
    instance: str | None = None,
    relay: str | None = None,
    in_reply_to: str | None = None,
    encrypt: bool = True,
    idempotency_key: str | None = None,
    publish: bool = True,
    client_factory: ClientFactory | None = None,
) -> SendResult:
    """Build, sign and publish a packet, then record it in the outbound log.

    With ``publish=False`` the packet is built and signed but not sent — the
    dry-run path, expressed as data rather than as a separate code path.
    """
    local, _label = resolve_instance(profile, instance)
    to_did, to_label = resolve_recipient(profile, to)

    packet = body.build(from_did=local.did, to_did=to_did, intent=intent)
    if in_reply_to:
        packet.in_reply_to = in_reply_to
    # Set before signing so the flag is covered by the signature.
    packet.encrypted = encrypt
    signed = packet.sign(local)

    if not publish:
        return SendResult(packet=signed, event_id="", to_did=to_did, to_label=to_label)

    if idempotency_key:
        cached = check_idempotency(idempotency_key)
        if cached:
            return SendResult(
                packet=None,
                event_id=str(cached.get("event_id", "")),
                to_did=to_did,
                to_label=to_label,
                cached=True,
            )

    recipient_pubkey = nostr_pubkey_for(profile, to_did)
    relay_urls = resolve_relays(profile, relay)
    event_id, relays_ok, relays_failed = await _publish(
        local,
        signed,
        recipient_pubkey,
        relay_urls,
        encrypt=encrypt,
        client_factory=client_factory,
    )

    if idempotency_key:
        record_idempotency(idempotency_key, signed.id, event_id)
    record_sent(
        profile,
        profile_path,
        signed,
        to_did=to_did,
        to_label=to_label,
        event_id=event_id,
        relays_ok=relays_ok,
        relays_failed=relays_failed,
    )
    return SendResult(
        packet=signed,
        event_id=event_id,
        to_did=to_did,
        to_label=to_label,
        relays_ok=relays_ok,
        relays_failed=relays_failed,
    )


def _resolve_ack_recipient(profile: Profile, packet_id: str) -> tuple[str, str]:
    """Return ``(to_did, to_label)`` for the sender of *packet_id*."""
    entry = next((e for e in profile.ingested_ids if e["id"] == packet_id), None)
    sender_did = entry.get("from_did") if entry else None
    if sender_did:
        label = label_for_did(profile, sender_did)
        if label is not None:
            try:
                nostr_pubkey_for(profile, sender_did)
            except NoNostrPubkeyError:
                pass
            else:
                return sender_did, label

    # Pre-#132 entries carry no sender. One trusted peer is unambiguous.
    candidates = [(lbl, tk) for lbl, tk in profile.trusted_keys.items() if tk.nostr_pubkey]
    if not candidates:
        raise NoTrustedPeerError
    if len(candidates) > 1:
        raise AmbiguousAckRecipientError([lbl for lbl, _ in candidates])
    label, key = candidates[0]
    return key.did, label


def resolve_ingested_id(profile: Profile, prefix: str) -> str:
    """Expand a packet-ID prefix against the local store."""
    matched = [e["id"] for e in profile.ingested_ids if e["id"].startswith(prefix)]
    if not matched:
        raise PacketNotIngestedError(prefix)
    if len(matched) > 1:
        raise AmbiguousPrefixError(prefix, len(matched))
    return matched[0]


async def ack(
    profile: Profile,
    profile_path: Path,
    *,
    packet_id: str,
    message: str = "acknowledged",
    dismiss: bool = False,
    instance: str | None = None,
    relay: str | None = None,
    idempotency_key: str | None = None,
    publish: bool = True,
    client_factory: ClientFactory | None = None,
) -> AckResult:
    """Acknowledge an ingested packet, replying to its sender."""
    local, _label = resolve_instance(profile, instance)
    full_id = resolve_ingested_id(profile, packet_id)
    to_did, to_label = _resolve_ack_recipient(profile, full_id)

    packet = Packet(
        from_did=local.did,
        to_did=to_did,
        intent="ack",
        content_type=ContentType.JSON,
        content={"in_reply_to": full_id, "message": message, "dismiss": dismiss},
        in_reply_to=full_id,
    )
    # Acks travel encrypted like any other packet; the CLI used to leave this
    # unset, so its acks were stored claiming plaintext.
    packet.encrypted = True
    signed = packet.sign(local)

    if not publish:
        return AckResult(
            packet=signed, event_id="", to_did=to_did, to_label=to_label, in_reply_to=full_id
        )

    if idempotency_key:
        cached = check_idempotency(idempotency_key)
        if cached:
            return AckResult(
                packet=None,
                event_id=str(cached.get("event_id", "")),
                to_did=to_did,
                to_label=to_label,
                cached=True,
                in_reply_to=full_id,
            )

    recipient_pubkey = nostr_pubkey_for(profile, to_did)
    relay_urls = resolve_relays(profile, relay)
    event_id, relays_ok, relays_failed = await _publish(
        local,
        signed,
        recipient_pubkey,
        relay_urls,
        encrypt=True,
        client_factory=client_factory,
    )

    if idempotency_key:
        record_idempotency(idempotency_key, signed.id, event_id)
    record_sent(
        profile,
        profile_path,
        signed,
        to_did=to_did,
        to_label=to_label,
        event_id=event_id,
        relays_ok=relays_ok,
        relays_failed=relays_failed,
    )
    return AckResult(
        packet=signed,
        event_id=event_id,
        to_did=to_did,
        to_label=to_label,
        relays_ok=relays_ok,
        relays_failed=relays_failed,
        in_reply_to=full_id,
    )


async def _fetch(
    profile: Profile,
    instance: str | None,
    relay: str | None,
    client_factory: ClientFactory | None,
) -> tuple[Any, str, list[str], list[Packet], bool, list[str]]:
    """Poll every configured relay.

    Returns ``(local, label, relay_urls, packets, reachable, reached)``. *reachable*
    is an any-relay-answered summary — the client only raises when every relay
    fails — so it cannot say which relays were reached. *reached* can: the client
    reports its refusals, and anything not refused answered. Callers recording
    per-relay state need *reached*; the poll envelope reports *reachable*.
    """
    local, label = resolve_instance(profile, instance)
    relay_urls = resolve_relays(profile, relay)
    make = _factory(client_factory)
    client = make(relay_urls, local.nostr_private_hex, local.nostr_public_hex)
    try:
        packets = [pkt async for pkt in client.fetch_pending()]
    except Exception:
        logger.exception("Relay fetch failed")
        return local, label, relay_urls, [], False, []
    # getattr: a client that does not report refusals is treated as having reached
    # everything, which matches the pre-existing behaviour for such clients.
    refused = set(getattr(client, "last_fetch_unreachable", []) or [])
    reached = [url for url in relay_urls if url not in refused]
    return local, label, relay_urls, packets, True, reached


async def inbox(
    profile: Profile,
    *,
    instance: str | None = None,
    relay: str | None = None,
    include_ingested: bool = False,
    client_factory: ClientFactory | None = None,
) -> tuple[PollResult, list[Packet]]:
    """List what is waiting, without ingesting.

    Returns ``(result, packets)`` — the envelope plus the Packet objects, so a
    surface can render richer detail than the summary dicts carry.
    """
    _local, label, relay_urls, packets, reachable, _reached = await _fetch(
        profile, instance, relay, client_factory
    )
    dropped = set(profile.dropped_ids)
    ingested = {e["id"] for e in profile.ingested_ids}

    visible = [pkt for pkt in packets if pkt.id not in dropped]
    fresh = triage(visible, ingested=ingested, dropped=dropped, verify=False).fresh
    shown = visible if include_ingested else fresh

    summaries = [packet_summary(profile, pkt, ingested=pkt.id in ingested) for pkt in shown]
    return (
        PollResult(packets=summaries, instance=label, relays=relay_urls, relay_reachable=reachable),
        shown,
    )


async def receive(
    profile: Profile,
    profile_path: Path,
    *,
    instance: str | None = None,
    relay: str | None = None,
    decide: Callable[[Packet, bool], Decision] = ingest_if_trusted,
    on_fresh: Callable[[list[Packet]], None] | None = None,
    send_receipts: bool = True,
    client_factory: ClientFactory | None = None,
) -> PollResult:
    """Poll, ingest what *decide* accepts, and advance the cursor.

    The cursor only advances for packets whose body actually landed: marking
    one ingested without a body on disk makes it unreadable and hides it from
    the inbox, losing it silently.
    """
    local, label, relay_urls, packets, reachable, reached = await _fetch(
        profile, instance, relay, client_factory
    )
    # Needed outside the loop below: the ingest loop stamps ingested_at with it.
    now_iso = _now_iso()
    # Only relays that answered. `aya relay status` and MCP `aya_relay_status`
    # render this as when the relay was last reached, so a relay that refused must
    # keep whatever it had — including nothing. Per-relay rather than gated on the
    # any-relay `reachable` summary, because one dead relay in a multi-relay
    # profile is the common case and would otherwise be stamped as reached.
    for url in reached:
        profile.last_checked[url] = now_iso

    sorted_packets = triage(
        packets,
        ingested={e["id"] for e in profile.ingested_ids},
        dropped=set(profile.dropped_ids),
    )

    if on_fresh is not None and sorted_packets.fresh:
        on_fresh(sorted_packets.fresh)

    summaries: list[dict[str, Any]] = []
    client: RelayClient | None = None
    for packet in sorted_packets.fresh:
        trusted = profile.is_trusted(packet.from_did)
        decision = decide(packet, trusted)

        if decision is Decision.SKIP_UNTRUSTED:
            summaries.append(_summary(packet, ingested=False, skipped=True))
            continue
        if decision is Decision.DECLINE:
            summaries.append(_summary(packet, ingested=False))
            continue

        _assert_valid_ulid(packet.id)
        if not ingest_packet(packet):
            logger.warning("Persistence failed for packet %s; not advancing cursor", packet.id)
            summaries.append(_summary(packet, ingested=False, error="persist_failed"))
            continue

        profile.ingested_ids.append(
            {"id": packet.id, "ingested_at": now_iso, "from_did": packet.from_did}
        )
        summaries.append(_summary(packet, ingested=True))

        # A receipt used to be sent only from the interactive-confirm branch,
        # so whether the sender learned their packet arrived depended on
        # whether a human happened to be at a terminal.
        if send_receipts:
            try:
                sender_pubkey = nostr_pubkey_for(profile, packet.from_did)
            except NoNostrPubkeyError:
                continue
            if client is None:
                client = _factory(client_factory)(
                    relay_urls, local.nostr_private_hex, local.nostr_public_hex
                )
            try:
                await client.send_receipt(packet, sender_pubkey)
            except Exception:
                logger.debug("Read receipt failed for %s", packet.id, exc_info=True)

    save_profile(profile, profile_path)
    return PollResult(
        packets=summaries,
        instance=label,
        relays=relay_urls,
        relay_reachable=reachable,
        bad_signature=sorted_packets.bad_signature,
    )


def packet_summary(profile: Profile, packet: Packet, *, ingested: bool) -> dict[str, Any]:
    """The listing shape both surfaces return for a pending packet.

    The CLI and MCP used to disagree here — one emitted ``from_did`` plus
    ``from_label``, the other a bare ``from`` — so a caller could not read both.

    Carries ``signature_valid`` alongside ``trusted`` so a caller can tell an
    untrusted sender from one whose claimed identity does not hold up.
    ``signature_valid`` False covers forgery and transit corruption alike: it
    says the sender cannot be authenticated, not that an attack occurred.
    """
    signature_valid = packet.verify_from_did(log_failure=False)
    return {
        "id": packet.id,
        "intent": packet.intent,
        "from_did": packet.from_did,
        "from_label": label_for_authenticated_sender(
            profile, packet.from_did, signature_valid=signature_valid
        ),
        "sent_at": packet.sent_at,
        "age": human_age(packet.sent_at),
        "content_type": packet.content_type,
        # from_did is an unauthenticated claim until the signature over it is
        # checked, so trust is gated on that check rather than on the string.
        "signature_valid": signature_valid,
        "trusted": signature_valid and profile.is_trusted(packet.from_did),
        "ingested": ingested,
    }


def _summary(
    packet: Packet, *, ingested: bool, skipped: bool = False, error: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": packet.id,
        "intent": packet.intent,
        "from": packet.from_did,
        "ingested": ingested,
    }
    if skipped:
        out["skipped"] = True
    if error:
        out["error"] = error
    return out
