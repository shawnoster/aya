"""Tests for the shared relay operations."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from aya.adapters.ledger import Ledger
from aya.adapters.profile_store import load_profile, save_profile
from aya.entities.identity import Identity, Profile, TrustedKey
from aya.entities.packet import Packet
from aya.usecases.relay_ops import (
    AmbiguousAckRecipientError,
    Decision,
    PacketBody,
    SendFailedError,
    ack,
    inbox,
    receive,
    send,
)
from aya.usecases.resolve import NoNostrPubkeyError


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
    save_profile(p, path)
    return load_profile(path), path


def _incoming(peer: Identity, to: Profile, intent: str = "hello") -> Packet:
    return Packet(
        from_did=peer.did,
        to_did=to.instances["harbor"].did,
        intent=intent,
        content="body",
    ).sign(peer)


class TestLastCheckedOnlyWhenReached:
    """`last_checked` claims a relay was checked, so a failed poll must not stamp it.

    `aya relay status` and MCP `aya_relay_status` both render this as when each
    relay was last checked. Stamped unconditionally, a poll that never reached any
    relay leaves a fresh timestamp behind — the same "looks healthy" failure the
    scheduler's `last_checked_at` has, and equally invisible.
    """

    async def test_an_unreachable_relay_is_not_stamped(self, profile):
        p, path = profile
        FakeClient.fetch_raises = True

        result = await receive(p, path, client_factory=FakeClient)

        assert result.relay_reachable is False, "precondition: the fetch failed"
        assert p.last_checked == {}, (
            f"a poll that reached nothing must leave no check time, got {p.last_checked}"
        )

    async def test_a_reachable_relay_is_stamped(self, profile):
        """The negative case, so the guard is not simply never stamping."""
        p, path = profile

        result = await receive(p, path, client_factory=FakeClient)

        assert result.relay_reachable is True
        assert sorted(p.last_checked) == ["wss://a", "wss://b"]


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
                from_did=stranger.did,
                to_did=p.instances["harbor"].did,
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


class TestPacketSummaryTrust:
    """`trusted` must mean a *verified* trusted sender, not a claimed one.

    `from_did` is an unauthenticated field until the signature over it is
    checked, so `trusted` is gated on `signature_valid` rather than on
    `is_trusted(from_did)` alone.
    """

    @staticmethod
    def _profile_with_trusted_peer():
        from aya.entities.identity import Identity, Profile, TrustedKey

        local = Identity.generate("default")
        peer = Identity.generate("home")
        profile = Profile()
        profile.instances["default"] = local
        profile.trusted_keys["home"] = TrustedKey(
            did=peer.did, label="home", nostr_pubkey=peer.nostr_public_hex
        )
        return profile, peer

    @staticmethod
    def _packet(from_did: str, to_did: str):
        from aya.entities.packet import Packet

        return Packet(from_did=from_did, to_did=to_did, intent="hello", content="body")

    def test_genuine_packet_from_a_trusted_peer_is_trusted(self):
        from aya.usecases.relay_ops import packet_summary

        profile, peer = self._profile_with_trusted_peer()
        pkt = self._packet(peer.did, peer.did).sign(peer)

        summary = packet_summary(profile, pkt, ingested=False)
        assert summary["signature_valid"] is True
        assert summary["trusted"] is True
        assert summary["from_label"] == "home"

    def test_forged_sender_claiming_a_trusted_did_is_not_trusted(self):
        from aya.entities.identity import Identity
        from aya.usecases.relay_ops import packet_summary

        profile, peer = self._profile_with_trusted_peer()
        attacker = Identity.generate("attacker")

        # Validly signed by the attacker, then the sender field is overwritten
        # with the trusted peer's DID — so is_trusted() alone answers True.
        pkt = self._packet(attacker.did, attacker.did).sign(attacker)
        pkt.from_did = peer.did

        assert profile.is_trusted(pkt.from_did) is True, "precondition: the DID looks trusted"
        summary = packet_summary(profile, pkt, ingested=False)
        assert summary["signature_valid"] is False
        assert summary["trusted"] is False
        # A caller reading from_label without also reading signature_valid must
        # not be handed the peer's name; there is no verified identity to name.
        assert summary["from_label"] is None
        assert summary["from_did"] == peer.did, "the raw claim stays visible"

    def test_listing_a_forged_packet_does_not_log_a_warning(self, caplog):
        """Listing must not let a relay flood the log.

        Anyone who can publish can send garbage; a warning per listed packet
        would turn `aya inbox` into an amplifier. The badge carries the fact.
        """
        import logging

        from aya.entities.identity import Identity
        from aya.usecases.relay_ops import packet_summary

        profile, peer = self._profile_with_trusted_peer()
        attacker = Identity.generate("attacker")
        pkt = self._packet(attacker.did, attacker.did).sign(attacker)
        pkt.from_did = peer.did

        with caplog.at_level(logging.WARNING):
            summary = packet_summary(profile, pkt, ingested=False)

        assert summary["signature_valid"] is False, "precondition: verification failed"
        assert caplog.records == [], "a listed bad signature is data, not an operational event"

    def test_receiving_a_forged_packet_still_logs_a_warning(self, caplog):
        """The quiet path is opt-in — the receive flow keeps its only surface.

        `receive` drops bad-signature packets out of its JSON, so the log line
        is how the failure reaches a human at all.
        """
        import logging

        from aya.entities.identity import Identity

        _profile, peer = self._profile_with_trusted_peer()
        attacker = Identity.generate("attacker")
        pkt = self._packet(attacker.did, attacker.did).sign(attacker)
        pkt.from_did = peer.did

        with caplog.at_level(logging.WARNING):
            assert pkt.verify_from_did() is False

        assert any("verification failed" in r.message for r in caplog.records)
        assert all(r.exc_info is None for r in caplog.records), "no traceback on a bad signature"

    def test_unsigned_packet_is_not_trusted(self):
        from aya.usecases.relay_ops import packet_summary

        profile, peer = self._profile_with_trusted_peer()
        pkt = self._packet(peer.did, peer.did)  # never signed

        summary = packet_summary(profile, pkt, ingested=False)
        assert summary["signature_valid"] is False
        assert summary["trusted"] is False

    def test_verified_but_unknown_sender_is_untrusted_not_invalid(self):
        """The two negative states stay distinguishable."""
        from aya.entities.identity import Identity
        from aya.usecases.relay_ops import packet_summary

        profile, _peer = self._profile_with_trusted_peer()
        stranger = Identity.generate("stranger")
        pkt = self._packet(stranger.did, stranger.did).sign(stranger)

        summary = packet_summary(profile, pkt, ingested=False)
        assert summary["signature_valid"] is True
        assert summary["trusted"] is False
