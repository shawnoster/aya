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
        **{"from": sender.did, "to": "did:key:zRECIPIENT"},
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
