"""Tests for packet triage — the shared receive/inbox filter."""

from __future__ import annotations

import pytest

from aya.entities.identity import Identity
from aya.entities.packet import Packet
from aya.usecases.triage import triage


@pytest.fixture
def sender() -> Identity:
    return Identity.generate("peer")


def _packet(sender: Identity, intent: str) -> Packet:
    return Packet(
        from_did=sender.did,
        to_did="did:key:zRECIPIENT",
        intent=intent,
        content="body",
    ).sign(sender)


class TestTriage:
    def test_fresh_packets_pass(self, sender: Identity):
        pkt = _packet(sender, "hello")
        assert triage([pkt], ingested=set(), dropped=set()).fresh == [pkt]

    def test_dropped_packets_never_resurface(self, sender: Identity):
        """`aya drop` used to hide a packet from inbox and still let the very
        next receive re-ingest it — the filter existed in only 2 of 4 paths."""
        pkt = _packet(sender, "spam")
        result = triage([pkt], ingested=set(), dropped={pkt.id})
        assert result.fresh == []
        assert result.bad_signature == []

    def test_already_ingested_is_skipped(self, sender: Identity):
        pkt = _packet(sender, "seen")
        assert triage([pkt], ingested={pkt.id}, dropped=set()).fresh == []

    def test_drop_wins_over_not_yet_ingested(self, sender: Identity):
        pkt = _packet(sender, "spam")
        assert triage([pkt], ingested=set(), dropped={pkt.id}).fresh == []

    def test_bad_signature_is_separated_not_silently_lost(self, sender: Identity):
        pkt = _packet(sender, "tampered")
        pkt.intent = "tampered-after-signing"
        result = triage([pkt], ingested=set(), dropped=set())
        assert result.fresh == []
        assert result.bad_signature == [pkt]

    def test_dropped_bad_signature_stays_quiet(self, sender: Identity):
        """A dropped bad-sig packet must stop being reported, not keep warning."""
        pkt = _packet(sender, "tampered")
        pkt.intent = "tampered-after-signing"
        result = triage([pkt], ingested=set(), dropped={pkt.id})
        assert result.bad_signature == []

    def test_verify_false_skips_signature_check(self, sender: Identity):
        """Listing shows what is waiting without asserting it is trustworthy."""
        pkt = _packet(sender, "tampered")
        pkt.intent = "tampered-after-signing"
        result = triage([pkt], ingested=set(), dropped=set(), verify=False)
        assert result.fresh == [pkt]

    def test_empty_input_is_falsey(self):
        assert not triage([], ingested=set(), dropped=set())


class TestMisrouted:
    """A signature proves who wrote a packet, not who it was for or who sent it."""

    def test_packet_for_someone_else_is_rejected(self, sender: Identity):
        pkt = _packet(sender, "for a third party")  # addressed to did:key:zRECIPIENT
        result = triage([pkt], ingested=set(), dropped=set(), local_did="did:key:zME")
        assert result.fresh == []
        assert result.misrouted == [(pkt, "wrong_recipient")]

    def test_packet_for_this_instance_passes(self, sender: Identity):
        pkt = _packet(sender, "for me")
        result = triage([pkt], ingested=set(), dropped=set(), local_did="did:key:zRECIPIENT")
        assert result.fresh == [pkt]

    def test_known_sender_on_wrong_key_is_rejected(self, sender: Identity):
        pkt = _packet(sender, "relayed by someone else")
        pkt.set_transport_pubkey("ff" * 32)
        result = triage(
            [pkt],
            ingested=set(),
            dropped=set(),
            sender_keys={sender.did: {sender.nostr_public_hex}},
        )
        assert result.misrouted == [(pkt, "wrong_sender_key")]

    def test_known_sender_on_own_key_passes(self, sender: Identity):
        pkt = _packet(sender, "straight from the sender")
        pkt.set_transport_pubkey(sender.nostr_public_hex)
        result = triage(
            [pkt],
            ingested=set(),
            dropped=set(),
            sender_keys={sender.did: {sender.nostr_public_hex}},
        )
        assert result.fresh == [pkt]

    def test_any_known_key_for_the_sender_passes(self, sender: Identity):
        """A peer re-paired under a second label keeps both keys valid."""
        pkt = _packet(sender, "from the newer key")
        pkt.set_transport_pubkey("ee" * 32)
        result = triage(
            [pkt],
            ingested=set(),
            dropped=set(),
            sender_keys={sender.did: {sender.nostr_public_hex, "ee" * 32}},
        )
        assert result.fresh == [pkt]

    def test_republished_copy_does_not_hide_the_real_one(self, sender: Identity):
        copy = _packet(sender, "same packet")
        real = copy.model_copy()
        copy.set_transport_pubkey("cd" * 32)
        real.set_transport_pubkey(sender.nostr_public_hex)
        result = triage(
            [copy, real],
            ingested=set(),
            dropped=set(),
            sender_keys={sender.did: {sender.nostr_public_hex}},
        )
        assert result.fresh == [real]
        assert result.misrouted == [(copy, "wrong_sender_key")]

    def test_two_good_copies_are_accepted_once(self, sender: Identity):
        first = _packet(sender, "same packet")
        first.set_transport_pubkey(sender.nostr_public_hex)
        second = first.model_copy()
        second.set_transport_pubkey(sender.nostr_public_hex)
        result = triage([first, second], ingested=set(), dropped=set())
        assert result.fresh == [first]

    def test_unknown_sender_is_left_to_the_trust_check(self, sender: Identity):
        """No known key to compare against; trust decides what happens next."""
        pkt = _packet(sender, "stranger")
        pkt.set_transport_pubkey("ff" * 32)
        result = triage([pkt], ingested=set(), dropped=set(), sender_keys={})
        assert result.fresh == [pkt]

    def test_bad_signature_wins_over_misrouting(self, sender: Identity):
        pkt = _packet(sender, "tampered")
        pkt.intent = "tampered-after-signing"
        result = triage([pkt], ingested=set(), dropped=set(), local_did="did:key:zME")
        assert result.bad_signature == [pkt]
        assert result.misrouted == []
