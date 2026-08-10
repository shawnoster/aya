"""Tests for aya.resolve — the shared name-resolution layer."""

from __future__ import annotations

import pytest

from aya.identity import Identity, InstanceResolutionError, Profile, TrustedKey
from aya.resolve import (
    NoNostrPubkeyError,
    UnknownRecipientError,
    label_for_did,
    nostr_pubkey_for,
    resolve_instance,
    resolve_recipient,
    resolve_relays,
)


@pytest.fixture
def profile() -> Profile:
    p = Profile(alias="Ace", ship_mind_name="", user_name="Shawn")
    p.instances["harbor"] = Identity.generate("harbor")
    beacon = Identity.generate("beacon")
    p.trusted_keys["beacon"] = TrustedKey(
        did=beacon.did, label="beacon", nostr_pubkey=beacon.nostr_public_hex
    )
    return p


class TestResolveRecipient:
    def test_raw_did_passes_through(self, profile: Profile):
        assert resolve_recipient(profile, "did:key:zABC") == ("did:key:zABC", "did:key:zABC")

    def test_known_label(self, profile: Profile):
        did, label = resolve_recipient(profile, "beacon")
        assert label == "beacon"
        assert did == profile.trusted_keys["beacon"].did

    def test_sole_peer_absorbs_any_label(self, profile: Profile):
        did, label = resolve_recipient(profile, "whatever")
        assert label == "beacon"
        assert did == profile.trusted_keys["beacon"].did

    def test_unknown_with_multiple_peers_raises_and_lists(self, profile: Profile):
        other = Identity.generate("sean")
        profile.trusted_keys["sean"] = TrustedKey(did=other.did, label="sean", nostr_pubkey="ab")
        with pytest.raises(UnknownRecipientError) as exc:
            resolve_recipient(profile, "nope")
        assert sorted(exc.value.available) == ["beacon", "sean"]
        assert "beacon" in str(exc.value)

    def test_no_peers_at_all_suggests_trust(self, profile: Profile):
        profile.trusted_keys.clear()
        with pytest.raises(UnknownRecipientError, match="aya trust"):
            resolve_recipient(profile, "nope")


class TestNostrPubkey:
    def test_returns_peer_pubkey(self, profile: Profile):
        did = profile.trusted_keys["beacon"].did
        assert nostr_pubkey_for(profile, did) == profile.trusted_keys["beacon"].nostr_pubkey

    def test_falls_back_to_local_instance(self, profile: Profile):
        harbor = profile.instances["harbor"]
        assert nostr_pubkey_for(profile, harbor.did) == harbor.nostr_public_hex

    def test_raises_rather_than_returning_none(self, profile: Profile):
        """A None here used to reach publish() and address an event to nobody."""
        profile.trusted_keys["beacon"] = TrustedKey(
            did="did:key:zNOKEY", label="beacon", nostr_pubkey=None
        )
        with pytest.raises(NoNostrPubkeyError, match="aya pair"):
            nostr_pubkey_for(profile, "did:key:zNOKEY")


class TestInstanceAndRelays:
    def test_resolve_instance_returns_label(self, profile: Profile):
        _identity, label = resolve_instance(profile, None)
        assert label == "harbor"

    def test_ambiguous_instance_raises(self, profile: Profile):
        profile.instances["work"] = Identity.generate("work")
        with pytest.raises(InstanceResolutionError):
            resolve_instance(profile, None)

    def test_relay_override_wins(self, profile: Profile):
        profile.default_relays = ["wss://a", "wss://b"]
        assert resolve_relays(profile, "wss://x") == ["wss://x"]
        assert resolve_relays(profile, None) == ["wss://a", "wss://b"]

    def test_label_for_did_and_miss(self, profile: Profile):
        did = profile.trusted_keys["beacon"].did
        assert label_for_did(profile, did) == "beacon"
        assert label_for_did(profile, "did:key:zUNKNOWN") is None
