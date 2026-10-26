"""Tests for relay.py — event building, receipt building, fetch_pending, helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aya.adapters.relay import (
    _FETCH_PAGE_SIZE,
    _MAX_RETRIES_PUBLISH,
    AYA_KIND,
    AYA_RESULT_KIND,
    RelayClient,
    RelayError,
    _compute_event_id,
    _read_until_eose,
    _sign_hex,
    verify_event,
)
from aya.entities.identity import Identity
from aya.entities.packet import Packet

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def trust_events(monkeypatch):
    """For tests about fetch mechanics (paging, dedup, decryption) built on
    hand-written events: signature checks have their own tests below."""
    monkeypatch.setattr("aya.adapters.relay.verify_event", lambda event: True)


@pytest.fixture
def sender() -> Identity:
    return Identity.generate("work")


@pytest.fixture
def recipient() -> Identity:
    return Identity.generate("home")


@pytest.fixture
def client(sender: Identity) -> RelayClient:
    return RelayClient(
        relay_urls="wss://relay.example.com",
        nostr_private_hex=sender.nostr_private_hex,
        nostr_public_hex=sender.nostr_public_hex,
    )


@pytest.fixture
def packet(sender: Identity, recipient: Identity) -> Packet:
    return Packet(
        from_did=sender.did,
        to_did=recipient.did,
        intent="Test packet for relay",
        content="Hello from work.",
    )


# ── _compute_event_id ─────────────────────────────────────────────────────────


class TestComputeEventId:
    def test_deterministic(self) -> None:
        result1 = _compute_event_id("aabbcc", 1000, 5999, [], "content")
        result2 = _compute_event_id("aabbcc", 1000, 5999, [], "content")
        assert result1 == result2

    def test_returns_64_hex_chars(self) -> None:
        event_id = _compute_event_id("aabbcc", 1000, 5999, [], "hi")
        assert len(event_id) == 64
        assert all(c in "0123456789abcdef" for c in event_id)

    def test_different_pubkeys_give_different_ids(self) -> None:
        id1 = _compute_event_id("aabbcc", 1000, 5999, [], "content")
        id2 = _compute_event_id("ddeeff", 1000, 5999, [], "content")
        assert id1 != id2

    def test_serialisation_nip01_format(self) -> None:
        """Verify NIP-01 canonical serialisation: [0, pubkey, created_at, kind, tags, content]."""
        pubkey = "aabbcc"
        created_at = 1234567890
        kind = 5999
        tags = [["p", "deadbeef"]]
        content = "hello"

        serialised = json.dumps(
            [0, pubkey, created_at, kind, tags, content],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        expected = hashlib.sha256(serialised.encode()).hexdigest()
        assert _compute_event_id(pubkey, created_at, kind, tags, content) == expected


# ── _sign_hex ─────────────────────────────────────────────────────────────────


class TestSignHex:
    def test_returns_128_hex_chars(self, sender: Identity) -> None:
        event_id = "a" * 64  # 32 bytes hex
        sig = _sign_hex(event_id, sender.nostr_private_hex)
        assert len(sig) == 128
        assert all(c in "0123456789abcdef" for c in sig)

    def test_different_keys_give_different_signatures(
        self, sender: Identity, recipient: Identity
    ) -> None:
        event_id = "c" * 64
        sig1 = _sign_hex(event_id, sender.nostr_private_hex)
        sig2 = _sign_hex(event_id, recipient.nostr_private_hex)
        assert sig1 != sig2


# ── _build_event ──────────────────────────────────────────────────────────────


class TestBuildEvent:
    def test_nostr_event_structure(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        assert set(event.keys()) == {"id", "pubkey", "created_at", "kind", "tags", "content", "sig"}

    def test_kind_is_aya(self, client: RelayClient, packet: Packet, recipient: Identity) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        assert event["kind"] == AYA_KIND

    def test_pubkey_is_sender(
        self, client: RelayClient, packet: Packet, sender: Identity, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        assert event["pubkey"] == sender.nostr_public_hex

    def test_content_is_packet_json_plaintext(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex, encrypt=False)
        restored = Packet.from_json(event["content"])
        assert restored.id == packet.id
        assert restored.intent == packet.intent

    def test_content_is_encrypted_by_default(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        import base64

        event = client._build_event(packet, recipient.nostr_public_hex)
        # Encrypted content is base64-encoded NIP-44 — not raw JSON
        raw = base64.b64decode(event["content"], validate=True)
        assert raw[0] == 2  # NIP-44 v2 version byte
        assert not event["content"].startswith("{")  # definitely not JSON

    def test_encrypted_content_decrypts_correctly(
        self, client: RelayClient, packet: Packet, sender: Identity, recipient: Identity
    ) -> None:
        from aya.entities.encryption import nip44_decrypt

        event = client._build_event(packet, recipient.nostr_public_hex)
        plaintext = nip44_decrypt(
            event["content"], recipient.nostr_private_hex, sender.nostr_public_hex
        )
        restored = Packet.from_json(plaintext)
        assert restored.id == packet.id
        assert restored.intent == packet.intent

    def test_has_recipient_p_tag(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        p_tags = [t for t in event["tags"] if t[0] == "p"]
        assert len(p_tags) == 1
        assert p_tags[0][1] == recipient.nostr_public_hex

    def test_has_expiration_tag(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        exp_tags = [t for t in event["tags"] if t[0] == "expiration"]
        assert len(exp_tags) == 1
        assert exp_tags[0][1].isdigit()

    def test_has_packet_id_tag(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        pid_tags = [t for t in event["tags"] if t[0] == "aya-packet-id"]
        assert len(pid_tags) == 1
        assert pid_tags[0][1] == packet.id

    def test_event_id_is_sha256_of_canonical_form(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        expected_id = _compute_event_id(
            pubkey=event["pubkey"],
            created_at=event["created_at"],
            kind=event["kind"],
            tags=event["tags"],
            content=event["content"],
        )
        assert event["id"] == expected_id

    def test_sig_length_is_128_hex_chars(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        event = client._build_event(packet, recipient.nostr_public_hex)
        assert len(event["sig"]) == 128


# ── _build_receipt ────────────────────────────────────────────────────────────


class TestBuildReceipt:
    def test_receipt_structure(self, client: RelayClient, packet: Packet, sender: Identity) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        assert set(receipt.keys()) == {
            "id",
            "pubkey",
            "created_at",
            "kind",
            "tags",
            "content",
            "sig",
        }

    def test_kind_is_result(self, client: RelayClient, packet: Packet, sender: Identity) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        assert receipt["kind"] == AYA_RESULT_KIND

    def test_content_has_packet_id_and_status(
        self, client: RelayClient, packet: Packet, sender: Identity
    ) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        data = json.loads(receipt["content"])
        assert data["packet_id"] == packet.id
        assert data["status"] == "received"

    def test_has_aya_packet_id_tag(
        self, client: RelayClient, packet: Packet, sender: Identity
    ) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        pid_tags = [t for t in receipt["tags"] if t[0] == "aya-packet-id"]
        assert len(pid_tags) == 1
        assert pid_tags[0][1] == packet.id

    def test_has_p_tag_with_sender(
        self, client: RelayClient, packet: Packet, sender: Identity
    ) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        p_tags = [t for t in receipt["tags"] if t[0] == "p"]
        assert len(p_tags) == 1
        assert p_tags[0][1] == sender.nostr_public_hex

    def test_receipt_id_matches_canonical(
        self, client: RelayClient, packet: Packet, sender: Identity
    ) -> None:
        receipt = client._build_receipt(packet, sender.nostr_public_hex)
        expected_id = _compute_event_id(
            pubkey=receipt["pubkey"],
            created_at=receipt["created_at"],
            kind=receipt["kind"],
            tags=receipt["tags"],
            content=receipt["content"],
        )
        assert receipt["id"] == expected_id


# ── _read_until_eose ──────────────────────────────────────────────────────────


class TestReadUntilEose:
    async def test_yields_events_until_eose(self) -> None:
        sub_id = "test-sub"
        event1 = {"id": "e1", "content": "hello"}
        event2 = {"id": "e2", "content": "world"}

        messages = [
            json.dumps(["EVENT", sub_id, event1]),
            json.dumps(["EVENT", sub_id, event2]),
            json.dumps(["EOSE", sub_id]),
        ]

        async def _aiter(msgs: list[str]):
            for m in msgs:
                yield m

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: _aiter(messages)

        collected = []
        async for evt in _read_until_eose(mock_ws, sub_id):
            collected.append(evt)

        assert len(collected) == 2
        assert collected[0]["id"] == "e1"
        assert collected[1]["id"] == "e2"

    async def test_stops_at_eose(self) -> None:
        sub_id = "sub-x"
        messages = [
            json.dumps(["EOSE", sub_id]),
            json.dumps(["EVENT", sub_id, {"id": "after-eose"}]),
        ]

        async def _aiter(msgs: list[str]):
            for m in msgs:
                yield m

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: _aiter(messages)

        collected = []
        async for evt in _read_until_eose(mock_ws, sub_id):
            collected.append(evt)

        assert collected == []

    async def test_ignores_events_for_other_sub_id(self) -> None:
        sub_id = "my-sub"
        messages = [
            json.dumps(["EVENT", "other-sub", {"id": "not-mine"}]),
            json.dumps(["EOSE", sub_id]),
        ]

        async def _aiter(msgs: list[str]):
            for m in msgs:
                yield m

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: _aiter(messages)

        collected = []
        async for evt in _read_until_eose(mock_ws, sub_id):
            collected.append(evt)

        assert collected == []

    async def test_raises_timeout_if_eose_never_arrives(self) -> None:
        """_read_until_eose raises TimeoutError when EOSE is not received in time."""
        sub_id = "hang-sub"

        async def _aiter_infinite():
            while True:
                await asyncio.sleep(10)  # never yields a message
                yield ""  # pragma: no cover

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: _aiter_infinite()

        with pytest.raises(TimeoutError):
            async for _ in _read_until_eose(mock_ws, sub_id, eose_timeout=0.05):
                pass  # pragma: no cover


# ── fetch_pending ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("trust_events")
class TestFetchPending:
    async def test_yields_valid_packets(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """fetch_pending should yield un-expired packets from relay events."""
        p = Packet(
            from_did=sender.did,
            to_did=recipient.did,
            intent="Remote task",
            content="Context data.",
        )
        raw_event = {"id": "evt1", "pubkey": "ab" * 32, "content": p.to_json()}

        async def fake_read_until_eose(ws, sub_id):
            yield raw_event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == 1
        assert packets[0].id == p.id
        assert packets[0].intent == p.intent

    async def test_skips_expired_packets(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        past = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        p = Packet(
            from_did=sender.did,
            to_did=recipient.did,
            intent="Old packet",
            content="Stale.",
            expires_at=past,
        )
        raw_event = {"id": "evt-old", "pubkey": "ab" * 32, "content": p.to_json()}

        async def fake_read_until_eose(ws, sub_id):
            yield raw_event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert packets == []

    async def test_skips_malformed_events(self, client: RelayClient) -> None:
        bad_event = {"id": "bad", "content": "not-json-packet!!!"}

        async def fake_read_until_eose(ws, sub_id):
            yield bad_event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert packets == []

    @pytest.mark.parametrize("pair_tag", ["aya-pair-req", "aya-pair-resp"])
    async def test_skips_pairing_events(self, client: RelayClient, pair_tag: str) -> None:
        """Pairing events (tagged aya-pair-req/resp) must not be parsed as Packets."""
        pairing_event = {
            "id": "pair-evt",
            "tags": [["t", pair_tag], ["p", client.public_key_hex]],
            "content": '{"code": "WORD-WORD-1234"}',
        }

        async def fake_read_until_eose(ws, sub_id):
            yield pairing_event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert packets == []

    async def test_handles_eose_timeout_gracefully(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """fetch_pending should return whatever packets arrived before EOSE timeout."""
        p = Packet(
            from_did=sender.did,
            to_did=recipient.did,
            intent="Partial fetch",
            content="Some data.",
        )
        raw_event = {"id": "evt-partial", "pubkey": "ab" * 32, "content": p.to_json()}

        async def fake_read_timeout(ws, sub_id):
            yield raw_event
            raise TimeoutError

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_timeout):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == 1
        assert packets[0].id == p.id

    async def test_yields_nip44_encrypted_packets(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """fetch_pending must transparently decrypt NIP-44-encrypted Nostr events."""
        from aya.entities.encryption import nip44_encrypt

        p = Packet(
            from_did=sender.did,
            to_did=recipient.did,
            intent="Encrypted handoff",
            content="This is secret.",
            encrypted=True,
        )
        # Encrypt from sender → recipient; client holds recipient keys.
        encrypted_content = nip44_encrypt(
            p.to_json(), sender.nostr_private_hex, recipient.nostr_public_hex
        )
        # The Nostr event carries the sender's pubkey in the envelope.
        raw_event = {
            "id": "evt-enc",
            "pubkey": sender.nostr_public_hex,
            "content": encrypted_content,
        }

        async def fake_read_until_eose(ws, sub_id):
            yield raw_event

        # client was built with sender keys (see fixture); for this test we need a client
        # built with recipient keys so it can decrypt.
        recipient_client = RelayClient(
            relay_urls="wss://relay.example.com",
            nostr_private_hex=recipient.nostr_private_hex,
            nostr_public_hex=recipient.nostr_public_hex,
        )

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in recipient_client.fetch_pending()]

        assert len(packets) == 1
        assert packets[0].id == p.id
        assert packets[0].intent == p.intent
        assert packets[0].encrypted is True
        # The publishing key is recorded so the receiver can bind it to `from`.
        assert packets[0].transport_pubkey == sender.nostr_public_hex

    async def test_records_transport_key_for_plaintext_packets(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """The plaintext path must record the publishing key too, or a forged
        unencrypted packet would skip the sender-key check."""
        p = Packet(from_did=sender.did, to_did=recipient.did, intent="plain", content="x")
        raw_event = {"id": "evt-plain", "pubkey": "ab" * 32, "content": p.to_json()}

        async def fake_read_until_eose(ws, sub_id):
            yield raw_event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)

            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert [pkt.transport_pubkey for pkt in packets] == ["ab" * 32]

    async def _fetch(self, client: RelayClient, events: list[dict]) -> list[Packet]:
        async def fake_read_until_eose(ws, sub_id):
            for event in events:
                yield event

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                return [pkt async for pkt in client.fetch_pending()]

    async def test_republished_copy_does_not_hide_the_original(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """A copy on a stranger's key, fetched first, must not win the dedup."""
        p = Packet(from_did=sender.did, to_did=recipient.did, intent="plain", content="x")
        events = [
            {"id": "evt-copy", "pubkey": "cd" * 32, "content": p.to_json()},
            {"id": "evt-real", "pubkey": sender.nostr_public_hex, "content": p.to_json()},
        ]
        packets = await self._fetch(client, events)
        assert [pkt.transport_pubkey for pkt in packets] == ["cd" * 32, sender.nostr_public_hex]


# ── pagination ────────────────────────────────────────────────────────────────


class FakeRelay:
    """Serves events the way a relay does: newest first, honouring `until`,
    `since` and the smaller of the filter's limit and its own cap."""

    def __init__(self, events: list[dict], cap: int | None = None):
        # NIP-01 order: newest first, and the lowest id first within a second.
        self.events = sorted(events, key=lambda e: (-e["created_at"], e["id"]))
        self.cap = cap
        self.filters: list[dict] = []

    async def _send(self, data):
        msg = json.loads(data)
        if msg[0] == "REQ":
            self.filters.append(msg[2])

    async def _read(self, ws, sub_id):
        f = self.filters[-1]
        limit = f["limit"] if self.cap is None else min(f["limit"], self.cap)
        page = [
            e for e in self.events if f.get("since", 0) <= e["created_at"] <= f.get("until", 2**62)
        ]
        for event in page[:limit]:
            yield event

    def serving(self):
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.send = AsyncMock(side_effect=self._send)
        stack = ExitStack()
        stack.enter_context(patch("aya.adapters.relay._read_until_eose", side_effect=self._read))
        stack.enter_context(patch("aya.adapters.relay.websockets.connect", return_value=mock_ws))
        return stack


async def _aenumerate(items):
    i = 0
    async for item in items:
        yield i, item
        i += 1


def _plain_event(sender: Identity, recipient: Identity, intent: str, created_at: int) -> dict:
    p = Packet(from_did=sender.did, to_did=recipient.did, intent=intent, content="data")
    return {
        "id": f"evt-{intent}",
        "pubkey": "ab" * 32,
        "content": p.to_json(),
        "created_at": created_at,
    }


@pytest.mark.usefixtures("trust_events")
class TestFetchPagination:
    """fetch_pending pages back in time via `until` until a page comes back empty."""

    async def test_paginates_when_full_page_returned(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """A page spanning seconds asks again from its oldest second, inclusive."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [
            _plain_event(sender, recipient, f"p{i}", base_ts - i)
            for i in range(_FETCH_PAGE_SIZE + 1)
        ]
        relay = FakeRelay(events)
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == _FETCH_PAGE_SIZE + 1
        assert "until" not in relay.filters[0]
        assert relay.filters[1]["until"] == base_ts - (_FETCH_PAGE_SIZE - 1)
        # Then the last event's second, a step past it, and the empty end.
        assert len(relay.filters) == 4

    async def test_small_inbox_takes_three_requests(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """A short page isn't the end, and a one-second page is re-asked once."""
        relay = FakeRelay(
            [_plain_event(sender, recipient, "only", int(datetime.now(UTC).timestamp()) - 3600)]
        )
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert [pkt.intent for pkt in packets] == ["only"]
        assert len(relay.filters) == 3  # the page, its second again, then empty

    async def test_stops_when_a_page_has_no_timestamps(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """A full page with no `created_at` fields stops pagination gracefully."""

        def _make_event_no_ts(idx: int) -> dict:
            p = Packet(
                from_did=sender.did,
                to_did=recipient.did,
                intent=f"Packet {idx}",
                content="data",
            )
            return {"id": f"evt-{idx}", "pubkey": "ab" * 32, "content": p.to_json()}

        full_page = [_make_event_no_ts(i) for i in range(_FETCH_PAGE_SIZE)]
        req_count = 0

        async def fake_read_until_eose(ws, sub_id):
            nonlocal req_count
            req_count += 1
            for evt in full_page:
                yield evt

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == _FETCH_PAGE_SIZE
        # Only one REQ: no cursor to advance when created_at is absent.
        assert req_count == 1

    async def test_a_same_second_block_does_not_hide_older_packets(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """#387: a full page of events sharing one second, anywhere in the window."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        newer = [_plain_event(sender, recipient, f"new{i}", base_ts - i) for i in range(5)]
        block = [
            _plain_event(sender, recipient, f"spam{i}", base_ts - 100)
            for i in range(_FETCH_PAGE_SIZE)
        ]
        older = _plain_event(sender, recipient, "older", base_ts - 200)
        relay = FakeRelay([*newer, *block, older])
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert "older" in [pkt.intent for pkt in packets]

    async def test_a_short_page_before_the_end_is_not_the_end(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """Relays drop expired or deleted events after applying `limit`."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [_plain_event(sender, recipient, f"p{i}", base_ts - i) for i in range(6)]
        relay = FakeRelay(events, cap=3)
        original = relay._read

        async def drops_one_on_the_first_page(ws, sub_id):
            first = len(relay.filters) == 1
            async for i, event in _aenumerate(original(ws, sub_id)):
                if first and i == 1:
                    continue  # expired after the limit was applied
                yield event

        relay._read = drops_one_on_the_first_page
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert {pkt.intent for pkt in packets} == {"p0", "p2", "p3", "p4", "p5"}

    async def test_a_page_boundary_inside_one_second_loses_nothing(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """Two honest packets in one second, split by a page boundary."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [_plain_event(sender, recipient, f"p{i}", base_ts - i) for i in range(4)]
        events.append(_plain_event(sender, recipient, "twin", base_ts - 3))
        relay = FakeRelay(events, cap=4)  # p3 ("evt-p3") sorts before "evt-twin"
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert sorted(pkt.intent for pkt in packets) == ["p0", "p1", "p2", "p3", "twin"]

    async def test_events_dropped_after_limit_do_not_split_a_second(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """A page that shrinks to one second because the relay dropped newer
        expired events after applying `limit` must not step past that second."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [
            _plain_event(sender, recipient, "exp1", base_ts),
            _plain_event(sender, recipient, "exp2", base_ts - 1),
            _plain_event(sender, recipient, "a", base_ts - 10),
            _plain_event(sender, recipient, "b", base_ts - 10),
        ]
        relay = FakeRelay(events, cap=3)
        original = relay._read

        async def drops_expired(ws, sub_id):
            async for event in original(ws, sub_id):
                if not event["id"].startswith("evt-exp"):
                    yield event

        relay._read = drops_expired
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert sorted(pkt.intent for pkt in packets) == ["a", "b"]

    async def test_an_event_exactly_at_since_is_fetched(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        since_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [
            _plain_event(sender, recipient, "inside", since_ts + 5),
            _plain_event(sender, recipient, "edge", since_ts),
            _plain_event(sender, recipient, "outside", since_ts - 1),
        ]
        relay = FakeRelay(events)
        with relay.serving():
            since = datetime.fromtimestamp(since_ts, UTC)
            packets = [pkt async for pkt in client.fetch_pending(since=since)]

        assert sorted(pkt.intent for pkt in packets) == ["edge", "inside"]

    async def test_page_order_does_not_matter(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """The cursor uses the page's oldest timestamp, not its last event."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [_plain_event(sender, recipient, f"p{i}", base_ts - i) for i in range(9)]
        relay = FakeRelay(events, cap=3)
        original = relay._read

        async def oldest_first(ws, sub_id):
            page = [event async for event in original(ws, sub_id)]
            for event in reversed(page):
                yield event

        relay._read = oldest_first
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == 9
        # Two seconds of progress per page (one overlaps), then the end: a cursor
        # read off the last event would crawl one second per page instead.
        assert len(relay.filters) == 6

    async def test_a_relay_that_caps_its_limit_is_paged_fully(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ) -> None:
        """#388: pages of 50 from a relay capped at 50 are not 'partial'."""
        base_ts = int(datetime.now(UTC).timestamp()) - 3600
        events = [_plain_event(sender, recipient, f"p{i}", base_ts - i) for i in range(120)]
        relay = FakeRelay(events, cap=50)
        with relay.serving():
            packets = [pkt async for pkt in client.fetch_pending()]

        assert len(packets) == 120

    async def test_a_relay_that_repeats_events_and_ignores_until(
        self, client: RelayClient, sender: Identity, recipient: Identity, caplog
    ) -> None:
        """A relay that repeats an event, then ignores `until`: no duplicate, and stop."""
        base_ts = 1_700_000_000

        def _make_event(idx: int, ts: int) -> dict:
            p = Packet(
                from_did=sender.did,
                to_did=recipient.did,
                intent=f"Packet {idx}",
                content="data",
            )
            return {
                "id": f"evt-{idx}",
                "pubkey": "ab" * 32,
                "content": p.to_json(),
                "created_at": ts,
            }

        # Page 1: _FETCH_PAGE_SIZE events.  The last event has the oldest ts.
        page1_events = [_make_event(i, base_ts - i) for i in range(_FETCH_PAGE_SIZE)]
        boundary_event = page1_events[-1]  # oldest event on page 1

        # Page 2: repeats the oldest event of page 1,
        # then one genuinely new event.
        new_event = _make_event(_FETCH_PAGE_SIZE, base_ts - _FETCH_PAGE_SIZE)
        page2_events = [boundary_event, new_event]

        call_count = 0

        async def fake_read_until_eose(ws, sub_id):
            nonlocal call_count
            events = page1_events if call_count == 0 else page2_events
            call_count += 1
            for evt in events:
                yield evt

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.send = AsyncMock()

        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            packets = [pkt async for pkt in client.fetch_pending()]

        # Total unique events: _FETCH_PAGE_SIZE (page 1) + 1 new (page 2).
        # The repeated event must NOT be yielded twice.
        assert len(packets) == _FETCH_PAGE_SIZE + 1
        # Page 3 repeats page 2, newer than `until`: the relay ignored it.
        assert call_count == 3
        assert "ignored the until cursor" in caplog.text


# ── publish ───────────────────────────────────────────────────────────────────


class TestPublish:
    async def test_publish_returns_event_id(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        fake_event_id = "a" * 64
        mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", fake_event_id, True, ""]))

        with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
            event_id = await client.publish(packet, recipient.nostr_public_hex)

        assert isinstance(event_id, str)
        assert len(event_id) == 64

    async def test_publish_raises_on_relay_rejection(
        self, client: RelayClient, packet: Packet, recipient: Identity
    ) -> None:
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", "x" * 64, False, "rate-limited"]))

        # Inject a no-op sleep: this exercises the full 5-attempt backoff loop
        # without spending the real ~30s of exponential delay.
        slept: list[float] = []

        async def _no_sleep(delay: float) -> None:
            slept.append(delay)

        client._sleep = _no_sleep

        with (
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
            pytest.raises(RelayError),
        ):
            await client.publish(packet, recipient.nostr_public_hex)

        # Retries are exhausted, not abandoned early.
        assert len(slept) == _MAX_RETRIES_PUBLISH - 1
        assert slept == sorted(slept), "backoff must be non-decreasing"


# ── Backoff helpers ───────────────────────────────────────────────────────────


class TestBackoffHelpers:
    def test_backoff_delay_increases_with_attempt(self) -> None:
        from aya.adapters.relay import _backoff_delay

        with patch("aya.adapters.relay.random.random", return_value=0.5):  # no jitter
            d0 = _backoff_delay(0)
            d1 = _backoff_delay(1)
            d2 = _backoff_delay(2)

        assert d0 < d1 < d2

    def test_backoff_delay_caps_at_60s(self) -> None:
        from aya.adapters.relay import _backoff_delay

        with patch("aya.adapters.relay.random.random", return_value=0.5):  # no jitter
            assert _backoff_delay(20) <= 60.0

    def test_backoff_delay_nonnegative(self) -> None:
        from aya.adapters.relay import _backoff_delay

        with patch("aya.adapters.relay.random.random", return_value=0.0):  # max negative jitter
            assert _backoff_delay(0) >= 0.0

    def test_is_rate_limited_true(self) -> None:
        from aya.adapters.relay import _is_rate_limited

        assert _is_rate_limited(["OK", "abc", False, "rate-limited: slow down"])

    def test_is_rate_limited_false_for_ok_accepted(self) -> None:
        from aya.adapters.relay import _is_rate_limited

        assert not _is_rate_limited(["OK", "abc", True, ""])

    def test_is_rate_limited_false_for_other_rejection(self) -> None:
        from aya.adapters.relay import _is_rate_limited

        assert not _is_rate_limited(["OK", "abc", False, "blocked: spam"])


# ── Multi-relay publish ───────────────────────────────────────────────────────


class TestMultiRelayPublish:
    async def test_publish_fans_out_to_all_relays(
        self, sender: Identity, packet: Packet, recipient: Identity
    ) -> None:
        """publish() should attempt both relay URLs."""
        connected_urls: list[str] = []

        def fake_connect(url, **kwargs):
            connected_urls.append(url)
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", "a" * 64, True, ""]))
            return mock_ws

        multi_client = RelayClient(
            relay_urls=["wss://relay1.example.com", "wss://relay2.example.com"],
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )

        with patch("aya.adapters.relay.websockets.connect", side_effect=fake_connect):
            event_id = await multi_client.publish(packet, recipient.nostr_public_hex)

        assert set(connected_urls) == {"wss://relay1.example.com", "wss://relay2.example.com"}
        assert len(event_id) == 64

    async def test_publish_succeeds_if_one_relay_accepts(
        self, sender: Identity, packet: Packet, recipient: Identity
    ) -> None:
        """publish() succeeds even when the first relay rejects."""
        call_count = 0

        def fake_connect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            # First relay rejects; second accepts
            if call_count == 1:
                mock_ws.recv = AsyncMock(
                    return_value=json.dumps(["OK", "a" * 64, False, "blocked"])
                )
            else:
                mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", "b" * 64, True, ""]))
            return mock_ws

        multi_client = RelayClient(
            relay_urls=["wss://relay1.example.com", "wss://relay2.example.com"],
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )

        with patch("aya.adapters.relay.websockets.connect", side_effect=fake_connect):
            event_id = await multi_client.publish(packet, recipient.nostr_public_hex)

        assert len(event_id) == 64

        # The rejecting relay must be recoverable — a bare success would hide
        # that a peer polling only relay1 will never see this packet.
        report = multi_client.last_publish_report
        assert [r["url"] for r in report] == [
            "wss://relay1.example.com",
            "wss://relay2.example.com",
        ]
        assert report[0]["ok"] is False
        assert report[0]["error"] == "blocked"
        assert report[1]["ok"] is True
        assert report[1]["error"] is None

    async def test_publish_raises_when_all_relays_fail(
        self, sender: Identity, packet: Packet, recipient: Identity
    ) -> None:
        """publish() raises RelayError only if all relays fail."""
        multi_client = RelayClient(
            relay_urls=["wss://relay1.example.com", "wss://relay2.example.com"],
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", "a" * 64, False, "blocked"]))

        with (
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
            pytest.raises(RelayError),
        ):
            await multi_client.publish(packet, recipient.nostr_public_hex)

    async def test_publish_retries_on_rate_limit(
        self, sender: Identity, packet: Packet, recipient: Identity
    ) -> None:
        """publish() retries after a rate-limited response."""
        client_single = RelayClient(
            relay_urls="wss://relay.example.com",
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )
        recv_iter = iter(
            [
                json.dumps(["OK", "a" * 64, False, "rate-limited: too fast"]),
                json.dumps(["OK", "a" * 64, True, ""]),
            ]
        )
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=lambda: next(recv_iter))

        with (
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
            patch("aya.adapters.relay.asyncio.sleep"),
        ):
            event_id = await client_single.publish(packet, recipient.nostr_public_hex)

        assert len(event_id) == 64


# ── Multi-relay fetch ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("trust_events")
class TestMultiRelayFetch:
    async def test_fetch_deduplicates_across_relays(
        self, sender: Identity, recipient: Identity
    ) -> None:
        """fetch_pending() deduplicates packets returned by multiple relays."""
        p = Packet(
            from_did=sender.did,
            to_did=recipient.did,
            intent="Dedup test",
            content="Content.",
        )

        async def fake_read_eose(ws, sub_id):
            yield {"id": "evt1", "pubkey": "ab" * 32, "content": p.to_json()}

        multi_client = RelayClient(
            relay_urls=["wss://relay1.example.com", "wss://relay2.example.com"],
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            packets = [pkt async for pkt in multi_client.fetch_pending()]

        # Same packet from two relays → only one copy
        assert len(packets) == 1
        assert packets[0].id == p.id

    async def test_single_url_string_backward_compat(self, sender: Identity) -> None:
        """A single relay may be given as a bare string."""
        c = RelayClient(
            relay_urls="wss://relay.example.com",
            nostr_private_hex=sender.nostr_private_hex,
            nostr_public_hex=sender.nostr_public_hex,
        )
        assert c._relay_urls == ["wss://relay.example.com"]


# ── event verification ────────────────────────────────────────────────────────


def _signed_event(identity: Identity, content: str, created_at: int = 1_700_000_000) -> dict:
    tags = [["p", "00" * 32]]
    event_id = _compute_event_id(identity.nostr_public_hex, created_at, AYA_KIND, tags, content)
    return {
        "id": event_id,
        "pubkey": identity.nostr_public_hex,
        "created_at": created_at,
        "kind": AYA_KIND,
        "tags": tags,
        "content": content,
        "sig": _sign_hex(event_id, identity.nostr_private_hex),
    }


class TestVerifyEvent:
    def test_genuine_event_verifies(self, sender: Identity):
        assert verify_event(_signed_event(sender, "hello")) is True

    def test_relay_cannot_swap_the_pubkey(self, sender: Identity, recipient: Identity):
        """The attack this closes: a relay reporting someone else as publisher."""
        event = {**_signed_event(sender, "hello"), "pubkey": recipient.nostr_public_hex}
        assert verify_event(event) is False

    def test_altered_content_fails(self, sender: Identity):
        event = {**_signed_event(sender, "hello"), "content": "goodbye"}
        assert verify_event(event) is False

    def test_id_recomputed_but_not_resigned_fails(self, sender: Identity, recipient: Identity):
        event = _signed_event(sender, "hello")
        event["pubkey"] = recipient.nostr_public_hex
        event["id"] = _compute_event_id(
            event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]
        )
        assert verify_event(event) is False

    @pytest.mark.parametrize("junk", [{}, {"id": 1}, {"sig": "zz", "pubkey": "not hex"}])
    def test_malformed_events_are_unverified_not_errors(self, junk):
        assert verify_event(junk) is False


class TestFetchVerifiesEvents:
    async def test_forged_event_is_skipped_and_genuine_one_kept(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ):
        real = Packet(from_did=sender.did, to_did=recipient.did, intent="real", content="x")
        forged = Packet(from_did=sender.did, to_did=recipient.did, intent="forged", content="y")
        genuine = _signed_event(sender, real.to_json())
        swapped = {**_signed_event(recipient, forged.to_json()), "pubkey": sender.nostr_public_hex}

        async def fake_read_until_eose(ws, sub_id):
            yield swapped
            yield genuine

        with patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            with patch("aya.adapters.relay.websockets.connect", return_value=mock_ws):
                packets = [pkt async for pkt in client.fetch_pending()]

        assert [pkt.intent for pkt in packets] == ["real"]
        assert packets[0].transport_pubkey == sender.nostr_public_hex


class TestHostileRelayInput:
    async def test_bad_frames_are_skipped_not_fatal(self, sender: Identity):
        good = _signed_event(sender, "hello")
        frames = [
            "not json at all",
            "[" * 20000 + "]" * 20000,  # deep enough to raise RecursionError
            json.dumps(["EVENT", "sub", ["not", "an", "object"]]),
            json.dumps(["EVENT", "sub", good]),
            json.dumps(["EOSE", "sub"]),
        ]

        class FakeWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if frames:
                    return frames.pop(0)
                raise StopAsyncIteration

        events = [event async for event in _read_until_eose(FakeWS(), "sub")]
        assert events == [good]

    async def test_forged_events_still_count_toward_the_page(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ):
        """A full page of forgeries must not stop pagination before the real packet."""
        mallory = Identity.generate("mallory")
        base_ts = 1_700_000_000
        forged = [
            {**_signed_event(mallory, f"junk {i}", base_ts - i), "sig": "00" * 64}
            for i in range(_FETCH_PAGE_SIZE)
        ]
        real = Packet(from_did=sender.did, to_did=recipient.did, intent="older", content="x")
        page2 = [_signed_event(sender, real.to_json(), base_ts - _FETCH_PAGE_SIZE)]
        pages = [forged, page2, []]

        async def fake_read_until_eose(ws, sub_id):
            for event in pages.pop(0) if pages else []:
                yield event

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            since = datetime.fromtimestamp(base_ts - 10_000, UTC)
            packets = [pkt async for pkt in client.fetch_pending(since=since)]

        assert [pkt.intent for pkt in packets] == ["older"]

    async def test_unhashable_event_id_does_not_end_the_fetch(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ):
        real = Packet(from_did=sender.did, to_did=recipient.did, intent="real", content="x")
        junk = {"id": ["x"], "created_at": 1_700_000_001}

        async def fake_read_until_eose(ws, sub_id):
            yield junk
            yield _signed_event(sender, real.to_json())

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            packets = [pkt async for pkt in client.fetch_pending()]

        assert [pkt.intent for pkt in packets] == ["real"]

    async def test_a_boolean_timestamp_is_not_a_cursor(
        self, client: RelayClient, sender: Identity, monkeypatch
    ):
        """JSON true is a bool, and isinstance(True, int) holds; `until` must not become 1."""
        monkeypatch.setattr("aya.adapters.relay._FETCH_PAGE_SIZE", 1)
        sent: list[dict] = []

        async def fake_read_until_eose(ws, sub_id):
            yield {"id": "x", "created_at": True}

        async def record(data):
            msg = json.loads(data)
            if msg[0] == "REQ":
                sent.append(msg[2])

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.send = AsyncMock(side_effect=record)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            assert [pkt async for pkt in client.fetch_pending()] == []

        assert all("until" not in f for f in sent)

    async def test_a_fake_with_a_real_id_does_not_hide_the_real_event(
        self, client: RelayClient, sender: Identity, recipient: Identity
    ):
        real = Packet(from_did=sender.did, to_did=recipient.did, intent="real", content="x")
        genuine = _signed_event(sender, real.to_json())
        fake = {"id": genuine["id"], "created_at": genuine["created_at"]}

        async def fake_read_until_eose(ws, sub_id):
            yield fake
            yield genuine

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            packets = [pkt async for pkt in client.fetch_pending()]

        assert [pkt.intent for pkt in packets] == ["real"]

    async def test_unverifiable_events_at_one_second_end_paging(
        self, client: RelayClient, monkeypatch
    ):
        """Junk at one second: the cursor moves past it and paging ends."""
        monkeypatch.setattr("aya.adapters.relay._FETCH_PAGE_SIZE", 2)
        ts = int(datetime.now(UTC).timestamp()) - 3600
        relay = FakeRelay([{"id": "a" * 64, "created_at": ts}, {"id": "b" * 64, "created_at": ts}])
        with relay.serving():
            assert [pkt async for pkt in client.fetch_pending()] == []

        assert len(relay.filters) == 3  # the junk page, its second again, then empty

    async def test_more_signed_spam_than_the_old_cap_does_not_hide_a_packet(
        self, client: RelayClient, sender: Identity, recipient: Identity, monkeypatch
    ):
        """Anyone can post signed events; enough of them must not push a real one out."""
        monkeypatch.setattr("aya.adapters.relay._FETCH_PAGE_SIZE", 2)
        mallory = Identity.generate("mallory")
        base_ts = 1_700_000_000
        spam = [_signed_event(mallory, f"spam {i}", base_ts - i) for i in range(120)]
        real = Packet(from_did=sender.did, to_did=recipient.did, intent="real", content="x")
        events = [*spam, _signed_event(sender, real.to_json(), base_ts - 500)]

        async def fake_read_until_eose(ws, sub_id):
            # Honour the cursor like a relay: newest first, at or before `until`.
            until = cursor["until"]
            page = [e for e in events if until is None or e["created_at"] <= until][:2]
            for event in page:
                yield event

        cursor: dict = {"until": None}

        async def record(data):
            msg = json.loads(data)
            if msg[0] == "REQ":
                cursor["until"] = msg[2].get("until")

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.send = AsyncMock(side_effect=record)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            since = datetime.fromtimestamp(base_ts - 10_000, UTC)
            packets = [pkt async for pkt in client.fetch_pending(since=since)]

        assert [pkt.intent for pkt in packets] == ["real"]

    async def test_endless_unverifiable_pages_stop_at_the_cap(
        self, client: RelayClient, monkeypatch, caplog
    ):
        """A relay inventing ever-older valid-looking events still stops."""
        monkeypatch.setattr("aya.adapters.relay._FETCH_PAGE_SIZE", 2)
        monkeypatch.setattr("aya.adapters.relay._MAX_FETCH_PAGES", 5)
        monkeypatch.setattr("aya.adapters.relay.verify_event", lambda event: True)
        calls = 0

        async def fake_read_until_eose(ws, sub_id):
            nonlocal calls
            calls += 1
            for i in range(2):
                ts = int(datetime.now(UTC).timestamp()) - calls * 10 - i
                yield {"id": f"{calls}-{i}", "created_at": ts, "content": "{}"}

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("aya.adapters.relay._read_until_eose", side_effect=fake_read_until_eose),
            patch("aya.adapters.relay.websockets.connect", return_value=mock_ws),
        ):
            assert [pkt async for pkt in client.fetch_pending()] == []

        assert calls == 5
        assert "stopped after 5 pages" in caplog.text
