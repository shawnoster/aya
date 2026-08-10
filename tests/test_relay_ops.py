"""Tests for the shared relay operations."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from aya.identity import Identity, Profile, TrustedKey
from aya.ledger import Ledger
from aya.packet import Packet
from aya.relay_ops import (
    AmbiguousAckRecipientError,
    Decision,
    PacketBody,
    SendFailedError,
    ack,
    inbox,
    receive,
    send,
)
from aya.resolve import NoNostrPubkeyError


class FakeClient:
    """Records what was published; yields what was queued."""

    queued: ClassVar[list[Packet]] = []
    fail_publish = False
    fetch_raises = False
    report: ClassVar[list[dict]] = []
    receipts: ClassVar[list[str]] = []
    published: ClassVar[list[Packet]] = []

    def __init__(self, relay_urls, priv, pub):
        self.relay_urls = list(relay_urls)
        self.last_publish_report = list(type(self).report) or [
            {"url": u, "ok": True, "error": None} for u in relay_urls
        ]

    async def fetch_pending(self):
        if type(self).fetch_raises:
            raise OSError("relay down")
        for pkt in type(self).queued:
            yield pkt

    async def publish(self, packet, pubkey, encrypt=True):
        if type(self).fail_publish:
            raise OSError("rejected")
        type(self).published.append(packet)
        return "evt" + packet.id[-8:]

    async def send_receipt(self, packet, pubkey):
        type(self).receipts.append(packet.id)


@pytest.fixture(autouse=True)
def _reset():
    FakeClient.queued = []
    FakeClient.fail_publish = False
    FakeClient.fetch_raises = False
    FakeClient.report = []
    FakeClient.receipts = []
    FakeClient.published = []


@pytest.fixture
def peer() -> Identity:
    return Identity.generate("beacon")


@pytest.fixture
def profile(tmp_path: Path, peer: Identity) -> tuple[Profile, Path]:
    path = tmp_path / "profile.json"
    path.write_text("{}")
    p = Profile()
    p.instances["harbor"] = Identity.generate("harbor")
    p.trusted_keys["beacon"] = TrustedKey(
        did=peer.did, label="beacon", nostr_pubkey=peer.nostr_public_hex
    )
    p.default_relays = ["wss://a", "wss://b"]
    p.save(path)
    return Profile.load(path), path


def _incoming(peer: Identity, to: Profile, intent: str = "hello") -> Packet:
    return Packet(
        **{"from": peer.did, "to": to.instances["harbor"].did},
        intent=intent,
        content="body",
    ).sign(peer)


class TestSend:
    async def test_publishes_and_logs(self, profile):
        p, path = profile
        result = await send(
            p,
            path,
            to="beacon",
            intent="hi",
            body=PacketBody.markdown("hello"),
            client_factory=FakeClient,
        )
        assert result.to_label == "beacon"
        assert result.relays_ok == ["wss://a", "wss://b"]
        assert not result.partial
        assert Ledger.load().sent[0]["to_label"] == "beacon"

    async def test_partial_delivery_is_reported(self, profile):
        p, path = profile
        FakeClient.report = [
            {"url": "wss://a", "ok": True, "error": None},
            {"url": "wss://b", "ok": False, "error": "503"},
        ]
        result = await send(
            p,
            path,
            to="beacon",
            intent="hi",
            body=PacketBody.markdown("x"),
            client_factory=FakeClient,
        )
        assert result.partial
        assert result.attempted == 2

    async def test_dry_run_signs_without_publishing(self, profile):
        p, path = profile
        result = await send(
            p,
            path,
            to="beacon",
            intent="hi",
            body=PacketBody.markdown("x"),
            publish=False,
            client_factory=FakeClient,
        )
        assert result.packet is not None
        assert FakeClient.published == []
        assert Ledger.load().sent == []

    async def test_packet_is_marked_encrypted_before_signing(self, profile):
        p, path = profile
        result = await send(
            p,
            path,
            to="beacon",
            intent="hi",
            body=PacketBody.markdown("x"),
            publish=False,
            client_factory=FakeClient,
        )
        assert result.packet.encrypted is True
        assert result.packet.verify_from_did(), "flag must be covered by the signature"

    async def test_publish_failure_raises_typed(self, profile):
        p, path = profile
        FakeClient.fail_publish = True
        with pytest.raises(SendFailedError):
            await send(
                p,
                path,
                to="beacon",
                intent="hi",
                body=PacketBody.markdown("x"),
                client_factory=FakeClient,
            )

    async def test_unpaired_recipient_raises_rather_than_addressing_nobody(self, profile):
        p, path = profile
        p.trusted_keys["beacon"] = TrustedKey(did="did:key:zNO", label="beacon", nostr_pubkey=None)
        with pytest.raises(NoNostrPubkeyError):
            await send(
                p,
                path,
                to="beacon",
                intent="hi",
                body=PacketBody.markdown("x"),
                client_factory=FakeClient,
            )

    async def test_seed_body(self, profile):
        p, path = profile
        result = await send(
            p,
            path,
            to="beacon",
            intent="q",
            body=PacketBody.seed("which side?"),
            publish=False,
            client_factory=FakeClient,
        )
        assert result.packet.content["opener"] == "which side?"


class TestReceive:
    async def test_ingests_trusted_and_holds_unknown(self, profile, peer):
        p, path = profile
        stranger = Identity.generate("stranger")
        FakeClient.queued = [
            _incoming(peer, p, "from peer"),
            Packet(
                **{"from": stranger.did, "to": p.instances["harbor"].did},
                intent="who?",
                content="?",
            ).sign(stranger),
        ]
        result = await receive(p, path, client_factory=FakeClient)
        by_intent = {s["intent"]: s for s in result.packets}
        assert by_intent["from peer"]["ingested"] is True
        assert by_intent["who?"]["skipped"] is True

    async def test_receipt_sent_on_every_ingest(self, profile, peer):
        """Receipts used to fire only from the interactive-confirm branch."""
        p, path = profile
        pkt = _incoming(peer, p)
        FakeClient.queued = [pkt]
        await receive(p, path, client_factory=FakeClient)
        assert FakeClient.receipts == [pkt.id]

    async def test_dropped_packet_is_not_reingested(self, profile, peer):
        p, path = profile
        pkt = _incoming(peer, p)
        p.dropped_ids.append(pkt.id)
        FakeClient.queued = [pkt]
        result = await receive(p, path, client_factory=FakeClient)
        assert result.packets == []
        assert p.ingested_ids == []

    async def test_unreachable_relay_is_not_an_empty_inbox(self, profile):
        p, path = profile
        FakeClient.fetch_raises = True
        result = await receive(p, path, client_factory=FakeClient)
        assert result.relay_reachable is False
        assert result.packets == []

    async def test_decline_does_not_advance_cursor(self, profile, peer):
        p, path = profile
        FakeClient.queued = [_incoming(peer, p)]
        result = await receive(
            p, path, decide=lambda _p, _t: Decision.DECLINE, client_factory=FakeClient
        )
        assert result.packets[0]["ingested"] is False
        assert p.ingested_ids == []

    async def test_envelope_names_instance_and_relays(self, profile):
        p, path = profile
        result = await receive(p, path, client_factory=FakeClient)
        env = result.envelope()
        assert env["instance"] == "harbor"
        assert env["relays"] == ["wss://a", "wss://b"]


class TestInbox:
    async def test_lists_without_ingesting(self, profile, peer):
        p, _path = profile
        FakeClient.queued = [_incoming(peer, p)]
        result, packets = await inbox(p, client_factory=FakeClient)
        assert len(packets) == 1
        assert result.packets[0]["from_label"] == "beacon"
        assert p.ingested_ids == []

    async def test_dropped_hidden_from_both_views(self, profile, peer):
        p, _path = profile
        pkt = _incoming(peer, p)
        p.dropped_ids.append(pkt.id)
        FakeClient.queued = [pkt]
        assert (await inbox(p, client_factory=FakeClient))[0].packets == []
        assert (await inbox(p, include_ingested=True, client_factory=FakeClient))[0].packets == []


class TestAck:
    async def _ingest_one(self, p, path, peer):
        pkt = _incoming(peer, p)
        FakeClient.queued = [pkt]
        await receive(p, path, client_factory=FakeClient)
        FakeClient.queued = []
        return pkt

    async def test_replies_to_the_original_sender(self, profile, peer):
        p, path = profile
        pkt = await self._ingest_one(p, path, peer)
        result = await ack(p, path, packet_id=pkt.id, message="got it", client_factory=FakeClient)
        assert result.to_label == "beacon"
        assert result.in_reply_to == pkt.id

    async def test_dismiss_is_carried(self, profile, peer):
        """MCP hardcoded dismiss=False, ignoring the flag entirely."""
        p, path = profile
        pkt = await self._ingest_one(p, path, peer)
        result = await ack(
            p, path, packet_id=pkt.id, dismiss=True, publish=False, client_factory=FakeClient
        )
        assert result.packet.content["dismiss"] is True

    async def test_ack_is_encrypted(self, profile, peer):
        """The CLI never set this, so its acks claimed plaintext."""
        p, path = profile
        pkt = await self._ingest_one(p, path, peer)
        result = await ack(p, path, packet_id=pkt.id, publish=False, client_factory=FakeClient)
        assert result.packet.encrypted is True

    async def test_unknown_packet_names_the_remedy(self, profile):
        p, path = profile
        with pytest.raises(Exception, match="aya receive"):
            await ack(p, path, packet_id="01ZZZZZZZZZZZZZZZZZZZZZZZZ", client_factory=FakeClient)

    async def test_ambiguous_recipient_raises(self, profile, peer):
        p, path = profile
        pkt = await self._ingest_one(p, path, peer)
        # Strip the recorded sender and add a second candidate peer.
        for e in p.ingested_ids:
            e.pop("from_did", None)
        other = Identity.generate("sean")
        p.trusted_keys["sean"] = TrustedKey(
            did=other.did, label="sean", nostr_pubkey=other.nostr_public_hex
        )
        with pytest.raises(AmbiguousAckRecipientError):
            await ack(p, path, packet_id=pkt.id, client_factory=FakeClient)
