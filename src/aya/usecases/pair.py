"""Relay-mediated pairing — short-code trust exchange between instances."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import websockets

from aya.adapters import clock
from aya.adapters.relay import (
    _PAIR_TAG_REQ,
    _PAIR_TAG_RESP,
    AYA_KIND,
    _backoff_delay,
    _compute_event_id,
    _is_rate_limited,
    _read_until_eose,
    _sign_hex,
)
from aya.entities.identity import Identity, TrustedKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PairResult:
    """A completed pairing, and the relay that demonstrably carried it.

    ``relay`` is the one relay both sides are known to reach: one end published
    there and the other read it back. Callers promote it to primary, so the
    fact the exchange just proved is not thrown away. Reporting the *configured*
    first relay instead would name a relay that may have failed outright.
    """

    trusted: TrustedKey
    relay: str


PAIR_TTL_SECONDS = 600  # 10 minutes
PAIR_POLL_INTERVAL = 3  # seconds
_PAIR_FETCH_LIMIT = 20  # room for junk events alongside the real one

# The relay sees a tag derived from the code, so that derivation has to be slow
# enough that ~29 bits can't be searched inside the 10-minute window: scrypt at
# 128 MiB costs ~0.4 s per guess. The UTC day in the salt stops anyone building
# one table of every code and reusing it forever.
_KDF_N = 2**17
_KDF_MAXMEM = 256 * 1024 * 1024

# 256 words — easy to read aloud, no homophones, no offensive terms.
# 8 bits per word x 2 words + ~13 bits (4-digit number) ≈ 29 bits.
# Enough for a 10-minute window only because of the slow derivation below.
WORD_LIST: tuple[str, ...] = (
    "AMBER",
    "ANCHOR",
    "ARROW",
    "ATLAS",
    "BADGE",
    "BASIN",
    "BEACH",
    "BIRCH",
    "BLADE",
    "BLAZE",
    "BLOOM",
    "BOARD",
    "BOLT",
    "BOWER",
    "BRAKE",
    "BRAVE",
    "BRICK",
    "BROOK",
    "BRUSH",
    "CAIRN",
    "CALM",
    "CANOE",
    "CARGO",
    "CEDAR",
    "CHAIN",
    "CHALK",
    "CHASE",
    "CHIEF",
    "CLIFF",
    "CLIMB",
    "CLOUD",
    "CLOVER",
    "COBRA",
    "CORAL",
    "CRANE",
    "CREEK",
    "CREST",
    "CROWN",
    "CRUSH",
    "DAGGER",
    "DELTA",
    "DIVER",
    "DOCK",
    "DRAFT",
    "DRIFT",
    "DRUM",
    "DUNE",
    "EAGLE",
    "EARTH",
    "EMBER",
    "FABLE",
    "FALCON",
    "FERN",
    "FIELD",
    "FLAME",
    "FLARE",
    "FLASH",
    "FLINT",
    "FLOOD",
    "FORGE",
    "FROST",
    "GALE",
    "GATE",
    "GAVEL",
    "GHOST",
    "GLADE",
    "GLEAM",
    "GLOBE",
    "GRAIN",
    "GRANT",
    "GRAPE",
    "GROVE",
    "GUARD",
    "GUILD",
    "HAVEN",
    "HAWK",
    "HAZEL",
    "HEART",
    "HEDGE",
    "HERON",
    "HIKER",
    "HONOR",
    "HOVER",
    "INLET",
    "IVORY",
    "JADE",
    "JETTY",
    "JEWEL",
    "KARMA",
    "KAYAK",
    "LANCE",
    "LARCH",
    "LASER",
    "LATCH",
    "LEDGE",
    "LEVER",
    "LIGHT",
    "LILAC",
    "LINEN",
    "LODGE",
    "LUNAR",
    "MAPLE",
    "MARCH",
    "MARSH",
    "MASON",
    "MEDAL",
    "MERGE",
    "MESA",
    "METAL",
    "MIRTH",
    "MIST",
    "MOOSE",
    "MOUNT",
    "NOBLE",
    "NORTH",
    "OASIS",
    "OLIVE",
    "ONYX",
    "ORBIT",
    "OTTER",
    "OXIDE",
    "PANEL",
    "PATCH",
    "PEARL",
    "PERCH",
    "PILOT",
    "PINE",
    "PIXEL",
    "PLAIN",
    "PLANT",
    "PLAZA",
    "PLUMB",
    "PLUME",
    "POLAR",
    "POND",
    "PORTER",
    "PRISM",
    "PULSE",
    "QUAIL",
    "QUARTZ",
    "QUEST",
    "RAPID",
    "RAVEN",
    "REALM",
    "REEF",
    "RIDGE",
    "RIVET",
    "ROOST",
    "ROVER",
    "ROYAL",
    "SAGE",
    "SCALE",
    "SCOUT",
    "SHARD",
    "SHELL",
    "SHORE",
    "SIGMA",
    "SLATE",
    "SLOPE",
    "SOLAR",
    "SPARK",
    "SPIRE",
    "SPOKE",
    "SPRAY",
    "SQUID",
    "STAG",
    "STEAM",
    "STEEL",
    "STONE",
    "STORM",
    "STORK",
    "SURGE",
    "SWIFT",
    "THORN",
    "TIGER",
    "TIMBER",
    "TORCH",
    "TOWER",
    "TRAIL",
    "TROUT",
    "TULIP",
    "TUNDRA",
    "UNITY",
    "VALOR",
    "VAULT",
    "VENOM",
    "VERGE",
    "VIPER",
    "VIVID",
    "VOICE",
    "WALNUT",
    "WARDEN",
    "WATER",
    "WAVE",
    "WHEAT",
    "WILLOW",
    "WINGS",
    "WOLF",
    "WRAITH",
    "YARN",
    "ZENITH",
    "FLICKER",
    "COMET",
    "DEPOT",
    "FINCH",
    "GRAIL",
    "CONDOR",
    "IRIS",
    "KNOLL",
    "THICKET",
    "MANOR",
    "NEXUS",
    "OPAL",
    "PETAL",
    "QUILT",
    "ROBIN",
    "SABLE",
    "TALON",
    "ULTRA",
    "VIGOR",
    "WEDGE",
    "XERUS",
    "YUCCA",
    "ZEPHYR",
    "ASPEN",
    "BASIL",
    "CINDER",
    "DRAKE",
    "MIRAGE",
    "FJORD",
    "GLACIER",
    "HARBOR",
    "ICICLE",
    "JASPER",
    "KESTREL",
    "LANTERN",
    "MAGNET",
    "NECTAR",
    "OSPREY",
    "PEBBLE",
    "QUARRY",
    "RAPIDS",
    "SUMMIT",
    "TRELLIS",
    "UMBER",
    "VALLEY",
    "WANDER",
    "YARROW",
    "PARCEL",
    "ALPINE",
    "BREEZE",
    "COPPER",
    "DAPPLE",
    "ECLIPSE",
    "FATHOM",
    "GARNET",
)

_TAG_PAIR_REQ = _PAIR_TAG_REQ
_TAG_PAIR_RESP = _PAIR_TAG_RESP


def generate_code() -> str:
    """Generate a human-readable pairing code: WORD-WORD-NNNN."""
    w1 = secrets.choice(WORD_LIST)
    w2 = secrets.choice(WORD_LIST)
    num = f"{secrets.randbelow(10000):04d}"
    return f"{w1}-{w2}-{num}"


@dataclass(frozen=True, slots=True)
class PairSecret:
    """What a pairing code turns into.

    ``lookup`` is published as the request's ``d`` tag so the joiner can find
    it. ``mac_key`` never leaves the machine: each side proves it knows the code
    by MACing its own identity with it, which is what stops anyone else who
    reads the relay from answering a request or posting a fake one.
    """

    lookup: str
    mac_key: bytes


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def derive_pair_secret(code: str, day: str | None = None) -> PairSecret:
    """Derive the lookup tag and MAC key for *code* on *day* (UTC, default today)."""
    day = day or _day(clock.now(UTC).timestamp())
    raw = hashlib.scrypt(
        code.strip().upper().encode(),
        salt=f"aya-pair-v1|{day}".encode(),
        n=_KDF_N,
        r=8,
        p=1,
        maxmem=_KDF_MAXMEM,
        dklen=64,
    )
    return PairSecret(lookup=raw[:32].hex(), mac_key=raw[32:])


def _pair_mac(key: bytes, role: str, did: str, label: str, nostr_pubkey: str, ref: str) -> str:
    message = json.dumps([role, did, label, nostr_pubkey, ref], separators=(",", ":"))
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def _authenticate(event: dict[str, Any], key: bytes, role: str, ref: str) -> TrustedKey | None:
    """The peer an event describes, or None unless its MAC proves the code.

    The MAC covers the event's own pubkey, so a response lifted from the relay
    and republished under another key fails here too.
    """
    try:
        content = json.loads(event["content"])
        did, label, mac = content["did"], content["label"], content.get("mac")
        pubkey = event["pubkey"]
    except (KeyError, TypeError, ValueError):
        return None
    if not all(isinstance(v, str) for v in (did, label, pubkey)):
        return None
    if not isinstance(mac, str):
        logger.warning(
            "Ignored a pairing %s with no proof of the code — is the other machine on an "
            "older aya? Both sides need to be upgraded.",
            role,
        )
        return None
    if not hmac.compare_digest(mac, _pair_mac(key, role, did, label, pubkey, ref)):
        logger.warning("Ignored a pairing %s that did not prove the code", role)
        return None
    return TrustedKey(did=did, label=label, nostr_pubkey=pubkey)


async def publish_pair_request(
    identity: Identity,
    label: str,
    secret: PairSecret,
    relay_url: str | list[str],
) -> str:
    """Publish a pair-request event to all configured relays, returns event ID. **ASYNC.**

    Usage::

        # In async context: await
        event_id = await publish_pair_request(identity, label, secret, relay_url)

        # In sync context: asyncio.run()
        event_id = asyncio.run(publish_pair_request(identity, label, secret, relay_url))
    """
    relay_urls = [relay_url] if isinstance(relay_url, str) else relay_url
    request_event = _build_pair_request(identity, label, secret)
    published = False
    last_event_id = request_event["id"]
    for url in relay_urls:
        for attempt in range(3):
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(["EVENT", request_event]))
                    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if resp[0] == "OK" and resp[2]:
                        logger.info("Published pair request %s via %s", last_event_id[:8], url)
                        published = True
                        break
                    if _is_rate_limited(resp) and attempt < 2:
                        delay = _backoff_delay(attempt)
                        logger.warning("Rate-limited by %s, retrying in %.1fs", url, delay)
                        await asyncio.sleep(delay)
                        continue
                    logger.warning("Relay %s rejected pair request: %s", url, resp)
                    break
            except Exception as exc:  # noqa: BLE001 — retried per relay, then reported
                if attempt < 2:
                    delay = _backoff_delay(attempt)
                    logger.warning(
                        "Error publishing pair request to %s: %s — retry in %.1fs",
                        url,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning("Failed to publish pair request to %s: %s", url, exc)
    if not published:
        raise PairingError("All relays rejected the pair request")
    return str(last_event_id)


async def poll_for_pair_response(
    relay_url: str | list[str],
    my_pubkey: str,
    request_event_id: str,
    mac_key: bytes,
    timeout_seconds: int = PAIR_TTL_SECONDS,
) -> PairResult | None:
    """Poll all configured relays for a pair-response. **ASYNC.**

    Polls each relay in turn, returning as soon as any relay yields a response
    that proves the code. Anyone reading the relay can see the request and
    answer it; only an answer MACed with the code is accepted.
    Applies per-relay exponential backoff when a relay has transient failures to
    avoid hammering rate-limited relays on reconnect.

    The returned :class:`PairResult` names the relay the response came back on,
    which is the relay the peer could publish to and we could read from — the
    only one of the configured relays proven to work for this pair.

    Usage::

        # In async context: await
        result = await poll_for_pair_response(relay_url, my_pubkey, event_id, mac_key)

        # In sync context: asyncio.run()
        result = asyncio.run(poll_for_pair_response(relay_url, my_pubkey, event_id, mac_key))
    """
    relay_urls = [relay_url] if isinstance(relay_url, str) else relay_url
    since_ts = int(clock.now(UTC).timestamp()) - 5
    deadline = clock.now(UTC).timestamp() + timeout_seconds
    relay_failures: dict[str, int] = dict.fromkeys(relay_urls, 0)

    while clock.now(UTC).timestamp() < deadline:
        for url in relay_urls:
            failures = relay_failures[url]
            if failures > 0:
                delay = _backoff_delay(failures - 1)
                remaining = deadline - clock.now(UTC).timestamp()
                if remaining <= 0:
                    return None
                await asyncio.sleep(min(delay, remaining))
            result, had_error = await _poll_single_relay(
                url, my_pubkey, request_event_id, mac_key, since_ts, deadline
            )
            if result is not None:
                return PairResult(trusted=result, relay=url)
            relay_failures[url] = (failures + 1) if had_error else 0
        remaining = deadline - clock.now(UTC).timestamp()
        if remaining <= 0:
            break
        await asyncio.sleep(min(PAIR_POLL_INTERVAL, remaining))

    return None


async def _poll_single_relay(
    relay_url: str,
    my_pubkey: str,
    request_event_id: str,
    mac_key: bytes,
    since_ts: int,
    deadline: float,
) -> tuple[TrustedKey | None, bool]:
    """Poll a single relay once for a pair-response.

    Returns ``(TrustedKey, False)`` on success, ``(None, False)`` when no
    response is available yet, and ``(None, True)`` on a connection/transient
    error so the caller can apply backoff before retrying.
    """
    try:
        async with websockets.connect(relay_url) as ws:
            filter_ = {
                "kinds": [AYA_KIND],
                "#t": [_TAG_PAIR_RESP],
                "#p": [my_pubkey],
                "#e": [request_event_id],
                "since": since_ts,
                "limit": _PAIR_FETCH_LIMIT,
            }
            sub_id = f"pair-poll-{clock.now(UTC).timestamp():.0f}"
            await ws.send(json.dumps(["REQ", sub_id, filter_]))
            try:
                eose_timeout = max(1.0, deadline - clock.now(UTC).timestamp())
                async for event in _read_until_eose(ws, sub_id, eose_timeout=eose_timeout):
                    peer = _authenticate(event, mac_key, "response", request_event_id)
                    if peer is not None:
                        await ws.send(json.dumps(["CLOSE", sub_id]))
                        return peer, False
            except TimeoutError:
                logger.debug("EOSE not received within timeout on %s; continuing", relay_url)
            await ws.send(json.dumps(["CLOSE", sub_id]))
    except TimeoutError:
        logger.debug("Pair polling timed out on %s", relay_url)
        return None, True
    except Exception as exc:  # noqa: BLE001 — one relay failing must not end the poll
        logger.warning("Pair polling connection error on %s: %s", relay_url, exc)
        return None, True
    return None, False


async def join_pairing(
    identity: Identity,
    code: str,
    relay_url: str | list[str],
) -> PairResult:
    """Joiner half of pairing flow — join using a pairing code. **ASYNC.**

    Joiner flow:
      1. Derive the lookup tag, find a pair-request on the relay that proves the code
      2. Publish pair-response, MACed with the code
      3. Return the initiator's TrustedKey and the relay it was found on

    Usage::

        # In async context: await
        result = await join_pairing(identity, code, relay_url)

        # In sync context: asyncio.run()
        result = asyncio.run(join_pairing(identity, code, relay_url))
    """
    relay_urls = [relay_url] if isinstance(relay_url, str) else relay_url
    # The request may have been made on the other side of a UTC midnight.
    now = clock.now(UTC).timestamp()
    days = {_day(now), _day(now - PAIR_TTL_SECONDS)}
    secrets_by_lookup = {s.lookup: s for s in (derive_pair_secret(code, d) for d in days)}

    # Find the pair request on any relay, with retry backoff
    found = await _find_pair_request_with_retry(relay_urls, secrets_by_lookup)
    if not found:
        raise PairingError(
            "No matching pairing request found.\n"
            "\n"
            "Possible causes:\n"
            "  • Wrong code — double-check the code and try again\n"
            "  • Expired — pairing codes are valid for 10 minutes\n"
            "  • Relay propagation lag — the request may not have synced yet\n"
            "  • Relay mismatch — both sides must use the same relay\n"
            "  • Version mismatch — both machines need an aya that proves the code\n"
            "\n"
            "Wait a few seconds and retry, or restart the pairing flow."
        )

    initiator, request_event_id, secret, found_on = found

    # Publish response to all relays; succeed if at least one accepts
    # Embed our own label so the initiator knows what to call us
    response_event = _build_pair_response(
        identity, identity.label, initiator.nostr_pubkey or "", request_event_id, secret.mac_key
    )
    published = False
    for url in relay_urls:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(["EVENT", response_event]))
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resp[0] == "OK" and resp[2]:
                    published = True
                else:
                    logger.warning("Relay %s rejected pair response: %s", url, resp)
        except Exception as exc:  # noqa: BLE001 — tried per relay; raises below if all fail
            logger.warning("Failed to publish pair response to %s: %s", url, exc)
    if not published:
        raise PairingError("All relays rejected the pair response")

    # `found_on` — not relay_urls[0] — is the relay the initiator's request
    # actually arrived on, so it is the one both sides are proven to reach.
    return PairResult(trusted=initiator, relay=found_on)


# ── Event builders ───────────────────────────────────────────────────────────


def _build_pair_request(identity: Identity, label: str, secret: PairSecret) -> dict[str, Any]:
    """Build a Nostr event for a pairing request."""
    created_at = int(clock.now(UTC).timestamp())
    expiration = created_at + PAIR_TTL_SECONDS
    mac = _pair_mac(secret.mac_key, "request", identity.did, label, identity.nostr_public_hex, "")
    content = json.dumps({"did": identity.did, "label": label, "mac": mac})
    tags = [
        ["t", _TAG_PAIR_REQ],
        ["d", secret.lookup],
        ["expiration", str(expiration)],
        ["aya-version", "0.2"],
    ]
    event_id = _compute_event_id(
        pubkey=identity.nostr_public_hex,
        created_at=created_at,
        kind=AYA_KIND,
        tags=tags,
        content=content,
    )
    sig = _sign_hex(event_id, identity.nostr_private_hex)
    return {
        "id": event_id,
        "pubkey": identity.nostr_public_hex,
        "created_at": created_at,
        "kind": AYA_KIND,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


def _build_pair_response(
    identity: Identity,
    label: str,
    initiator_pubkey: str,
    request_event_id: str,
    mac_key: bytes,
) -> dict[str, Any]:
    """Build a Nostr event responding to a pairing request."""
    created_at = int(clock.now(UTC).timestamp())
    expiration = created_at + PAIR_TTL_SECONDS
    mac = _pair_mac(
        mac_key, "response", identity.did, label, identity.nostr_public_hex, request_event_id
    )
    content = json.dumps({"did": identity.did, "label": label, "mac": mac})
    tags = [
        ["t", _TAG_PAIR_RESP],
        ["p", initiator_pubkey],
        ["e", request_event_id],
        ["expiration", str(expiration)],
        ["aya-version", "0.2"],
    ]
    event_id = _compute_event_id(
        pubkey=identity.nostr_public_hex,
        created_at=created_at,
        kind=AYA_KIND,
        tags=tags,
        content=content,
    )
    sig = _sign_hex(event_id, identity.nostr_private_hex)
    return {
        "id": event_id,
        "pubkey": identity.nostr_public_hex,
        "created_at": created_at,
        "kind": AYA_KIND,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


# ── Relay queries ────────────────────────────────────────────────────────────


FoundRequest = tuple[TrustedKey, str, PairSecret, str]
"""``(initiator, request_event_id, secret, relay_url)`` for a request that proved the code."""


async def _find_pair_request(
    relay_url: str | list[str], secrets_by_lookup: dict[str, PairSecret]
) -> FoundRequest | None:
    """Find a pair-request on any configured relay that proves the code.

    The relay URL is returned because the initiator published there and we read
    it back, so it is a relay both sides reach, which the caller promotes to
    primary. Requests that carry the lookup tag but fail the MAC are skipped:
    the tag is public once the real request is posted, so anyone can copy it.
    """
    relay_urls = [relay_url] if isinstance(relay_url, str) else relay_url
    since_ts = int(clock.now(UTC).timestamp()) - PAIR_TTL_SECONDS
    filter_ = {
        "kinds": [AYA_KIND],
        "#t": [_TAG_PAIR_REQ],
        "#d": sorted(secrets_by_lookup),
        "since": since_ts,
        "limit": _PAIR_FETCH_LIMIT,
    }
    for url in relay_urls:
        try:
            sub_id = f"pair-find-{clock.now(UTC).timestamp():.0f}"
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(["REQ", sub_id, filter_]))
                async for event in _read_until_eose(ws, sub_id):
                    lookup = next((t[1] for t in event.get("tags", []) if t[:1] == ["d"]), None)
                    secret = secrets_by_lookup.get(lookup) if isinstance(lookup, str) else None
                    if secret is None:
                        continue
                    initiator = _authenticate(event, secret.mac_key, "request", "")
                    if initiator is None:
                        continue
                    await ws.send(json.dumps(["CLOSE", sub_id]))
                    return initiator, event["id"], secret, url
                await ws.send(json.dumps(["CLOSE", sub_id]))
        except Exception as exc:  # noqa: BLE001 — tried per relay; returns None if none answer
            logger.warning("Failed to query %s for pair request: %s", url, exc)
    return None


_FIND_RETRY_DELAYS = (1, 2, 4)  # seconds — exponential backoff for not-found retries


async def _find_pair_request_with_retry(
    relay_urls: list[str],
    secrets_by_lookup: dict[str, PairSecret],
    *,
    _delays: tuple[int, ...] = _FIND_RETRY_DELAYS,
) -> FoundRequest | None:
    """Wrap :func:`_find_pair_request` with exponential backoff for "not found" results.

    Relays may lag behind on propagation, so retry up to ``len(_delays)`` times
    with increasing waits (1 s, 2 s, 4 s) before giving up.  Connection errors
    inside ``_find_pair_request`` are already logged there; here we only retry
    on a clean ``None`` (no matching event found yet).
    """
    result = await _find_pair_request(relay_urls, secrets_by_lookup)
    if result is not None:
        return result
    for attempt, delay in enumerate(_delays, start=1):
        logger.debug(
            "Pair request not found (attempt %d/%d); retrying in %ds",
            attempt,
            len(_delays),
            delay,
        )
        await asyncio.sleep(delay)
        result = await _find_pair_request(relay_urls, secrets_by_lookup)
        if result is not None:
            return result
    return None


class PairingError(Exception):
    pass
