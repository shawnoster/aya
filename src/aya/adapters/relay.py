"""Nostr relay client — send and receive packets via NIP-01 WebSocket protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import websockets
from coincurve import PrivateKey as Secp256k1PrivateKey
from coincurve import PublicKeyXOnly
from websockets.asyncio.client import ClientConnection

from aya.adapters import clock
from aya.entities.encryption import nip44_decrypt, nip44_encrypt
from aya.entities.packet import Packet

logger = logging.getLogger(__name__)

# aya uses kind 5999 — within the NIP-90 Data Vending Machine range
AYA_KIND = 5999
AYA_RESULT_KIND = 6999  # read receipts / replies

# Pairing event type tags — same kind as packets but not Packet-shaped.
# Defined here (not in pair.py) so relay.py can filter them without a
# circular import (pair.py already imports relay.py).
_PAIR_TAG_REQ = "aya-pair-req"
_PAIR_TAG_RESP = "aya-pair-resp"
_PAIR_TAGS: frozenset[str] = frozenset({_PAIR_TAG_REQ, _PAIR_TAG_RESP})

# Retry / backoff configuration
_BACKOFF_BASE = 1.0  # seconds for first retry
_BACKOFF_CAP = 60.0  # maximum sleep between retries
_BACKOFF_JITTER = 0.25  # ±25% random jitter
_MAX_RETRIES_PUBLISH = 5
_MAX_RETRIES_FETCH = 3

# Fetch pagination — events per REQ batch.  Pagination continues with an
# `until` cursor until the relay returns fewer events than this size.
_FETCH_PAGE_SIZE = 200
# Last-resort backstop only; the cursor rule in _fetch_from_relay is what ends
# paging. Someone posting about limit x 1000 events in the window (200k, or 50k
# on a relay capped at 50) could still push older packets past it; that is
# volume spam, logged when hit, and the authors-filter fetch (#390) covers it.
_MAX_FETCH_PAGES = 1000
# Default look-back window used when no `since` is specified.  Matches the
# default packet TTL (7 days) so no live packet can fall outside the window.
_DEFAULT_FETCH_WINDOW_DAYS = 7


def _backoff_delay(attempt: int) -> float:
    """Return exponential-backoff delay with ±25% jitter.

    attempt=0 → ~1 s, attempt=1 → ~2 s, attempt=2 → ~4 s, …, capped at 60 s.
    """
    base = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP)
    jitter = base * _BACKOFF_JITTER * (2 * random.random() - 1)  # noqa: S311
    return float(max(0.0, base + jitter))


def _is_rate_limited(response: list[Any]) -> bool:
    """Return True if an OK response indicates rate-limiting."""
    return (
        len(response) >= 4
        and response[0] == "OK"
        and not response[2]
        and isinstance(response[3], str)
        and response[3].startswith("rate-limited")
    )


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for connection/OS errors worth retrying."""
    return isinstance(exc, (OSError, websockets.exceptions.WebSocketException, TimeoutError))


class RelayClient:
    """
    Minimal Nostr relay client for aya packet delivery.

    Handles:
      - Publishing packets as signed Nostr events (kind 5999)
      - Querying for pending packets addressed to a pubkey
      - Sending read receipts (kind 6999)

    *relay_urls* may be a single URL (str) or a list of URLs.
    Publish fans out to all relays and succeeds if at least one accepts.
    Fetch queries all relays and deduplicates by packet ID.

    Uses secp256k1 (Nostr) keys for transport, not ed25519 (did:key).
    """

    def __init__(
        self,
        relay_urls: str | list[str],
        nostr_private_hex: str,
        nostr_public_hex: str,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if isinstance(relay_urls, str):
            self._relay_urls: list[str] = [relay_urls]
        else:
            self._relay_urls = list(relay_urls)
        if not self._relay_urls or any(
            not isinstance(url, str) or not url.strip() for url in self._relay_urls
        ):
            raise ValueError("relay_urls must contain at least one non-empty string URL")
        self._private_key_hex = nostr_private_hex
        self.public_key_hex = nostr_public_hex
        # Populated by publish(); one entry per relay, in polling order.
        self.last_publish_report: list[dict[str, str | bool | None]] = []
        # Relays that refused the most recent fetch. Reported the same way as
        # last_publish_report because fetch_pending is a generator and cannot
        # return a value alongside what it yields.
        self.last_fetch_unreachable: list[str] = []
        # Injectable so retry/backoff behaviour can be exercised without
        # spending the real delay — the retry matrix is otherwise too slow
        # to cover (one end-to-end rejection test cost 30s of wall clock).
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep

    async def publish(
        self, packet: Packet, recipient_nostr_pubkey: str, encrypt: bool = True
    ) -> str:
        """Publish a packet to all configured relays. **ASYNC.**

        Fans out to every relay regardless of individual results.
        Retries individual relays on transient failures (rate-limit, 503, network)
        with exponential back-off + jitter.  Raises *RelayError* only if all
        relays fail after exhausting retries.

        *encrypt* controls NIP-44 encryption of the Nostr event content (default: True).
        Pass ``encrypt=False`` for debug or private-relay use where transport-level
        security is trusted.

        Usage::

            # In async context: await
            event_id = await client.publish(packet, recipient_pubkey)

            # In sync context: asyncio.run()
            event_id = asyncio.run(client.publish(packet, recipient_pubkey))
        """
        logger.debug("Publishing packet %s to %d relay(s)", packet.id[:8], len(self._relay_urls))
        event = self._build_event(packet, recipient_nostr_pubkey, encrypt=encrypt)
        errors: list[str] = []
        last_event_id: str | None = None
        # Per-relay outcome for the caller to surface. `publish` succeeds when
        # *any* relay accepts, so a bare success hides a peer-visible partial
        # failure: the one relay that rejected may be the only one the
        # recipient polls.
        report: list[dict[str, str | bool | None]] = []

        for relay_url in self._relay_urls:
            event_id, error = await self._publish_to_relay(event, relay_url, packet)
            if event_id is not None:
                last_event_id = event_id
                report.append({"url": relay_url, "ok": True, "error": None})
            else:
                errors.append(relay_url)
                report.append({"url": relay_url, "ok": False, "error": error})

        self.last_publish_report = report

        if last_event_id is not None:
            logger.debug("Packet %s published as event %s", packet.id[:8], last_event_id[:8])
            return last_event_id

        raise RelayError(f"All relays rejected the event: {errors}")

    async def _publish_to_relay(
        self, event: dict[str, Any], relay_url: str, packet: Packet
    ) -> tuple[str | None, str | None]:
        """Try to publish *event* to *relay_url* with retries.

        Returns ``(event_id, None)`` on success or ``(None, reason)`` on failure.
        """
        for attempt in range(_MAX_RETRIES_PUBLISH):
            try:
                async with websockets.connect(relay_url) as ws:
                    await ws.send(json.dumps(["EVENT", event]))
                    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if response[0] == "OK" and response[2]:
                        logger.info(
                            "Published packet %s as event %s via %s",
                            packet.id[:8],
                            event["id"][:8],
                            relay_url,
                        )
                        return event["id"], None
                    if _is_rate_limited(response):
                        # No sleep after the final attempt — there is no retry
                        # left to wait for, and the cap makes that a ~60s delay
                        # on top of an already-failed publish.
                        if attempt == _MAX_RETRIES_PUBLISH - 1:
                            break
                        delay = _backoff_delay(attempt)
                        logger.warning(
                            "Rate-limited by %s (attempt %d/%d), retrying in %.1fs",
                            relay_url,
                            attempt + 1,
                            _MAX_RETRIES_PUBLISH,
                            delay,
                        )
                        await self._sleep(delay)
                        continue
                    logger.warning("Relay %s rejected event: %s", relay_url, response)
                    reason = str(response[3]) if len(response) > 3 and response[3] else "rejected"
                    return None, reason
            except Exception as exc:  # noqa: BLE001 — _is_transient_error triages it below
                if _is_transient_error(exc) and attempt < _MAX_RETRIES_PUBLISH - 1:
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        "Transient error publishing to %s (attempt %d/%d): %s — retry in %.1fs",
                        relay_url,
                        attempt + 1,
                        _MAX_RETRIES_PUBLISH,
                        exc,
                        delay,
                    )
                    await self._sleep(delay)
                else:
                    logger.warning("Failed to publish to %s: %s", relay_url, exc)
                    return None, f"{type(exc).__name__}: {exc}"
        return None, "rate-limited (retries exhausted)"

    async def fetch_pending(
        self,
        since: datetime | None = None,
    ) -> AsyncIterator[Packet]:
        """Yield packets addressed to this instance's pubkey, querying all relays. **ASYNC.**

        Results are deduplicated by (packet ID, publishing key) across relays:
        a copy republished under another key is passed on for the receiver to
        judge, so it cannot displace the original.  When *since* is
        omitted a default look-back window of ``_DEFAULT_FETCH_WINDOW_DAYS``
        (matching the packet TTL) is applied so the scan is bounded to the
        live-packet window.  Pass an explicit *since* to override that lower
        bound.

        Usage::

            # In async context: use `async for` in an async function
            async for packet in client.fetch_pending():
                print(packet)

            # In sync context: asyncio.run with async generator wrapper
            async def fetch_all():
                packets = []
                async for p in client.fetch_pending():
                    packets.append(p)
                return packets
            packets = asyncio.run(fetch_all())
        """
        logger.debug("Fetching pending packets from %d relay(s)", len(self._relay_urls))
        # Keyed on the carrying key too: anyone can republish a plaintext packet
        # under their own key, and if their copy arrived first and won the
        # dedup, the receiver would reject it and never see the real one.
        seen: set[tuple[str, str | None]] = set()
        unreachable: list[str] = []
        self.last_fetch_unreachable = unreachable
        for relay_url in self._relay_urls:
            try:
                async for packet in self._fetch_from_relay(relay_url, since):
                    key = (packet.id, packet.transport_pubkey)
                    if key not in seen:
                        seen.add(key)
                        yield packet
            except RelayUnreachableError:
                unreachable.append(relay_url)
        if unreachable and len(unreachable) == len(self._relay_urls):
            raise RelayUnreachableError(
                f"All {len(self._relay_urls)} relay(s) unreachable: {unreachable}"
            )
        logger.debug("Fetch complete, %d unique packet(s) found", len(seen))

    async def _fetch_from_relay(
        self,
        relay_url: str,
        since: datetime | None,
    ) -> AsyncIterator[Packet]:
        """Fetch all matching packets from a single relay, paginating via `until`.

        Sends REQ filters with ``limit=_FETCH_PAGE_SIZE``. After each page the
        cursor moves to the page's oldest second (inclusive, repeats dropped),
        or one second before it when the whole page is that one second, and
        another REQ is issued. Paging stops on an empty page (or one with no usable
        timestamp), when the relay ignores ``until``, or at the
        ``_MAX_FETCH_PAGES`` backstop. A short page is not the end: relays cap
        ``limit`` and drop expired or deleted events after applying it.

        Known limit: events sharing one second can't be paged within that
        second using since/until/limit. Someone who posts a page's worth of
        events at a real packet's second, with lower ids, can push it out.

        When *since* is omitted a default look-back window of
        ``_DEFAULT_FETCH_WINDOW_DAYS`` is applied (matching the packet TTL) so
        the scan is bounded to the live-packet window.  Pass an explicit *since*
        to override this lower bound.
        """
        now = clock.now(UTC)
        effective_since = (
            since if since is not None else (now - timedelta(days=_DEFAULT_FETCH_WINDOW_DAYS))
        )
        until: int | None = None
        seen_event_ids: set[str] = set()  # a relay may repeat an event across pages

        for _page in range(_MAX_FETCH_PAGES):
            filter_: dict[str, Any] = {
                "kinds": [AYA_KIND],
                "#p": [self.public_key_hex],
                "limit": _FETCH_PAGE_SIZE,
                "since": int(effective_since.timestamp()),
            }
            if until is not None:
                filter_["until"] = until

            sub_id = f"aya-{now.timestamp():.0f}-{until or 'first'}"

            # Collect the raw events for this page so we can
            # determine the oldest timestamp before deciding whether to paginate.
            page_events: list[dict[str, Any]] = []
            fetch_ok = False

            for attempt in range(_MAX_RETRIES_FETCH):
                page_events = []
                try:
                    logger.debug("Connecting to %s (page cursor until=%s)", relay_url, until)
                    async with websockets.connect(relay_url) as ws:
                        await ws.send(json.dumps(["REQ", sub_id, filter_]))
                        try:
                            async for raw in _read_until_eose(ws, sub_id):
                                page_events.append(raw)
                        except TimeoutError:
                            logger.warning(
                                "Relay %s did not send EOSE within timeout; closing subscription",
                                relay_url,
                            )
                        await ws.send(json.dumps(["CLOSE", sub_id]))
                    fetch_ok = True
                    break  # page fetched successfully
                except Exception as exc:  # noqa: BLE001 — _is_transient_error triages it below
                    if _is_transient_error(exc) and attempt < _MAX_RETRIES_FETCH - 1:
                        delay = _backoff_delay(attempt)
                        logger.warning(
                            "Transient error fetching from %s (attempt %d/%d): %s — retry in %.1fs",
                            relay_url,
                            attempt + 1,
                            _MAX_RETRIES_FETCH,
                            exc,
                            delay,
                        )
                        await self._sleep(delay)
                    else:
                        logger.warning("Failed to fetch from %s: %s", relay_url, exc)

            if not fetch_ok:
                raise RelayUnreachableError(relay_url)

            # Process events and track the page's time span for the cursor.
            oldest_ts: int | None = None
            newest_ts: int | None = None
            for raw in page_events:
                raw_ts = raw.get("created_at")
                # `type is int`, not isinstance: JSON true is a bool, and a bool
                # cursor would jump the page window back to 1970.
                if type(raw_ts) is int:
                    if oldest_ts is None or raw_ts < oldest_ts:
                        oldest_ts = raw_ts
                    if newest_ts is None or raw_ts > newest_ts:
                        newest_ts = raw_ts
                event_id = raw.get("id")
                # Only string ids dedup: an unhashable id (a list, say) would
                # otherwise raise here and end the fetch for every relay.
                if isinstance(event_id, str) and event_id in seen_event_ids:
                    continue  # already yielded from an earlier page
                # After the cursor bookkeeping, so forged events still give the
                # page a timestamp and can't make it look empty.
                if not verify_event(raw):
                    logger.debug("Skipping an event with a bad id or signature")
                    continue
                # Only verified ids claim a slot: a fake carrying a real event's
                # id must not make the real one look already seen.
                seen_event_ids.add(raw["id"])
                try:
                    # Skip pairing events — same kind (5999) but not
                    # Packet-shaped. Constants live in relay.py to avoid
                    # a circular import with pair.py.
                    event_tags = raw.get("tags", [])
                    pairing_tag = next(
                        (
                            t
                            for t in event_tags
                            if len(t) >= 2 and t[0] == "t" and t[1] in _PAIR_TAGS
                        ),
                        None,
                    )
                    if pairing_tag is not None:
                        logger.debug("Skipping pairing event (tag=%s)", pairing_tag[1])
                        continue
                    content = raw["content"]
                    # Route on content shape: JSON → parse directly; anything else
                    # (base64 NIP-44 payload) → decrypt first.  Checking the leading
                    # character avoids masking parse/validation errors in malformed
                    # JSON packets by misattributing them as decryption failures.
                    if content.lstrip().startswith("{"):
                        packet = Packet.from_json(content)
                    else:
                        # NIP-44 decryption with the publisher's key from the envelope.
                        sender_pub = raw["pubkey"]
                        try:
                            plaintext = nip44_decrypt(content, self._private_key_hex, sender_pub)
                        except ValueError as crypto_exc:
                            logger.warning(
                                "Skipping event %s: NIP-44 decryption failed — %s",
                                raw["id"][:8],  # a string: verify_event checked it
                                crypto_exc,
                            )
                            continue
                        packet = Packet.from_json(plaintext)
                    # Both paths: the receiver checks this against the key it
                    # knows for the packet's sender, plaintext or not.
                    packet.set_transport_pubkey(raw.get("pubkey"))
                    if not packet.is_expired():
                        yield packet
                except Exception as exc:  # noqa: BLE001 — one bad event must not end the poll
                    logger.warning("Skipping malformed event: %s", exc)

            if oldest_ts is None:
                break  # empty: nothing older is left

            # An honest relay never returns anything newer than `until`. Without
            # this check, the inclusive cursor below could repeat forever.
            if until is not None and newest_ts is not None and newest_ts > until:
                logger.warning("Relay %s ignored the until cursor; stopping", relay_url)
                break
            # Either branch moves the cursor strictly back in time, so paging
            # always ends.
            if until is None or oldest_ts < until:  # noqa: SIM108 — two cases, two comments
                # Re-ask from the page's oldest second, inclusive: a page boundary
                # (or events the relay dropped after applying `limit`) may have
                # split that second. Repeats are dropped as seen.
                until = oldest_ts
            else:
                # Already asked from this second and got only this second back:
                # a page-long block there (anyone can post one). Step past it;
                # any further events at exactly that second are skipped.
                until = oldest_ts - 1
            logger.debug(
                "Relay %s: fetched %d events, advancing cursor to until=%d",
                relay_url,
                len(page_events),
                until,
            )
        else:
            logger.warning("Relay %s: stopped after %d pages", relay_url, _MAX_FETCH_PAGES)

    async def send_receipt(self, packet: Packet, sender_nostr_pubkey: str) -> None:
        """Publish a read receipt for the given packet to all configured relays. **ASYNC.**

        Usage::

            # In async context: await
            await client.send_receipt(packet, sender_pubkey)

            # In sync context: asyncio.run()
            asyncio.run(client.send_receipt(packet, sender_pubkey))
        """
        event = self._build_receipt(packet, sender_nostr_pubkey)
        for relay_url in self._relay_urls:
            try:
                async with websockets.connect(relay_url) as ws:
                    await ws.send(json.dumps(["EVENT", event]))
                    await asyncio.wait_for(ws.recv(), timeout=10)
            except Exception as exc:  # noqa: BLE001 — receipts are best-effort, per relay
                logger.warning("Failed to send receipt to %s: %s", relay_url, exc)

    def _build_event(
        self, packet: Packet, recipient_nostr_pubkey: str, encrypt: bool = True
    ) -> dict[str, Any]:
        """Build a NIP-01 compliant Nostr event wrapping the Assistant Sync packet.

        When *encrypt* is True (default), the packet JSON is NIP-44 encrypted to the
        recipient's Nostr pubkey before embedding in the event content.
        """
        recipient_pubkey = recipient_nostr_pubkey

        if encrypt:
            content = nip44_encrypt(packet.to_json(), self._private_key_hex, recipient_pubkey)
        else:
            content = packet.to_json()
        tags = [
            ["p", recipient_pubkey],
            [
                "expiration",
                str(int(datetime.fromisoformat(packet.expires_at or packet.sent_at).timestamp())),
            ],
            ["aya-version", "0.2"],
            ["aya-packet-id", packet.id],
        ]

        created_at = int(clock.now(UTC).timestamp())
        event_id = _compute_event_id(
            pubkey=self.public_key_hex,
            created_at=created_at,
            kind=AYA_KIND,
            tags=tags,
            content=content,
        )
        sig = _sign_hex(event_id, self._private_key_hex)

        return {
            "id": event_id,
            "pubkey": self.public_key_hex,
            "created_at": created_at,
            "kind": AYA_KIND,
            "tags": tags,
            "content": content,
            "sig": sig,
        }

    def _build_receipt(self, packet: Packet, sender_nostr_pubkey: str) -> dict[str, Any]:
        content = json.dumps({"packet_id": packet.id, "status": "received"})
        recipient_pubkey = sender_nostr_pubkey
        tags = [
            ["p", recipient_pubkey],
            ["aya-packet-id", packet.id],
            ["aya-version", "0.2"],
        ]
        created_at = int(clock.now(UTC).timestamp())
        event_id = _compute_event_id(
            pubkey=self.public_key_hex,
            created_at=created_at,
            kind=AYA_RESULT_KIND,
            tags=tags,
            content=content,
        )
        sig = _sign_hex(event_id, self._private_key_hex)
        return {
            "id": event_id,
            "pubkey": self.public_key_hex,
            "created_at": created_at,
            "kind": AYA_RESULT_KIND,
            "tags": tags,
            "content": content,
            "sig": sig,
        }


_EOSE_TIMEOUT = 30.0  # seconds to wait for EOSE before giving up


async def _read_until_eose(
    ws: ClientConnection, sub_id: str, eose_timeout: float = _EOSE_TIMEOUT
) -> AsyncIterator[dict[str, Any]]:
    """Yield EVENT payloads until EOSE (end of stored events) from the relay.

    Raises `TimeoutError` if EOSE is not received within *eose_timeout* seconds.
    """
    async with asyncio.timeout(eose_timeout):
        async for raw_msg in ws:
            # One malformed frame (or JSON nested deep enough to blow the
            # recursion limit) must not end the subscription.
            try:
                msg = json.loads(raw_msg)
            except Exception:  # noqa: BLE001 — skip the frame, keep reading
                logger.debug("Skipping unparseable relay message")
                continue
            match msg:
                case ["EVENT", sid, dict() as event] if sid == sub_id:
                    yield event
                case ["EOSE", sid] if sid == sub_id:
                    return
                case ["NOTICE", notice]:
                    logger.debug("Relay notice: %s", notice)
                case _:
                    logger.debug("Unexpected relay message: %s", msg)


def _compute_event_id(
    pubkey: str,
    created_at: int,
    kind: int,
    tags: list[Any],
    content: str,
) -> str:
    """NIP-01: event ID is SHA-256 of canonical serialisation."""
    serialised = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialised.encode()).hexdigest()


def verify_event(event: dict[str, Any]) -> bool:
    """True if *event*'s id matches its content and its signature is the pubkey's.

    Without this, the pubkey on an event is whatever the relay says it is. With
    it, a relay can still withhold events but cannot forge or alter them.
    """
    try:
        expected = _compute_event_id(
            pubkey=event["pubkey"],
            created_at=event["created_at"],
            kind=event["kind"],
            tags=event["tags"],
            content=event["content"],
        )
        if event["id"] != expected:
            return False
        key = PublicKeyXOnly(bytes.fromhex(event["pubkey"]))
        return bool(key.verify(bytes.fromhex(event["sig"]), bytes.fromhex(expected)))
    except Exception:  # noqa: BLE001 — anything malformed is simply unverified
        return False


def _sign_hex(event_id_hex: str, private_key_hex: str) -> str:
    """Sign a Nostr event ID with secp256k1 Schnorr (BIP-340) and return hex signature."""
    key = Secp256k1PrivateKey(bytes.fromhex(private_key_hex))
    sig_bytes = key.sign_schnorr(bytes.fromhex(event_id_hex))
    return sig_bytes.hex()


class RelayError(Exception):
    pass


class RelayUnreachableError(RelayError):
    """Raised when all retries to connect to a relay are exhausted."""
