"""Tests for identity generation, DID derivation, and profile persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ulid import ULID

from aya.adapters.profile_store import (
    _normalize_ingested_ids,
    load_profile,
    save_profile,
)
from aya.entities.identity import (
    PROFILE_SCHEMA_VERSION,
    Identity,
    Profile,
    TrustedKey,
    _assert_valid_ulid,
)


class TestIdentityGeneration:
    def test_generates_unique_keypairs(self) -> None:
        a = Identity.generate("work")
        b = Identity.generate("home")
        assert a.did != b.did
        assert a.private_key_hex != b.private_key_hex

    def test_did_format(self) -> None:
        identity = Identity.generate("test")
        assert identity.did.startswith("did:key:z6Mk")

    def test_sign_produces_bytes(self) -> None:
        identity = Identity.generate("test")
        sig = identity.sign(b"hello world")
        assert isinstance(sig, bytes)
        assert len(sig) == 64  # ed25519 signature length

    def test_private_key_roundtrip(self) -> None:
        identity = Identity.generate("test")
        # Reconstruct private key from hex and verify it produces same public key
        reconstructed = identity.private_key()
        pub = reconstructed.public_key().public_bytes_raw().hex()
        assert pub == identity.public_key_hex

    def test_nostr_pubkey_is_hex(self) -> None:
        identity = Identity.generate("test")
        pubkey = identity.nostr_pubkey()
        assert len(pubkey) == 64  # 32 bytes hex-encoded
        assert all(c in "0123456789abcdef" for c in pubkey)


class TestProfilePersistence:
    def test_save_and_load(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"alias": "Ace", "user_name": "Shawn"}))

        p = load_profile(profile_path)
        p.instances["work"] = Identity.generate("work")
        p.trusted_keys["home"] = TrustedKey(
            did="did:key:z6MkFakeHome", label="home", nostr_pubkey="abc123"
        )
        save_profile(p, profile_path)

        restored = load_profile(profile_path)
        assert "work" in restored.instances
        assert restored.instances["work"].did == p.instances["work"].did
        assert "home" in restored.trusted_keys

    def test_save_does_not_clobber_other_keys(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "alias": "Cipher",
                    "ship_mind_name": "Dramatically Unbothered",
                    "user_name": "Shawn",
                    "movement_reminders": True,
                }
            )
        )

        p = load_profile(profile_path)
        p.instances["work"] = Identity.generate("work")
        save_profile(p, profile_path)

        data = json.loads(profile_path.read_text())
        # Existing keys must survive the save
        assert data["alias"] == "Cipher"
        assert data["ship_mind_name"] == "Dramatically Unbothered"
        assert data["movement_reminders"] is True

    def test_is_trusted(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        home = Identity.generate("home")
        p.trusted_keys["home"] = TrustedKey(did=home.did, label="home")
        save_profile(p, profile_path)

        restored = load_profile(profile_path)
        assert restored.is_trusted(home.did)
        assert not restored.is_trusted("did:key:z6MkStranger")


class TestProfileMultiRelay:
    def test_default_relays_saved_as_list(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        p.default_relays = ["wss://relay1.example.com", "wss://relay2.example.com"]
        save_profile(p, profile_path)

        data = json.loads(profile_path.read_text())
        assert data["aya"]["default_relays"] == [
            "wss://relay1.example.com",
            "wss://relay2.example.com",
        ]
        assert "default_relay" not in data["aya"]

    def test_load_new_default_relays_list(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(
            json.dumps(
                {
                    "aya": {
                        "default_relays": [
                            "wss://relay1.example.com",
                            "wss://relay2.example.com",
                        ]
                    }
                }
            )
        )

        p = load_profile(profile_path)
        assert p.default_relays == ["wss://relay1.example.com", "wss://relay2.example.com"]


class TestIngestedIdsTTL:
    def test_recent_entries_are_kept(self, tmp_path: Path) -> None:
        """Entries ingested within the last 7 days must survive save/load."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        valid_id = str(ULID())
        p.ingested_ids.append({"id": valid_id, "ingested_at": recent_ts})
        save_profile(p, profile_path)

        restored = load_profile(profile_path)
        assert any(e["id"] == valid_id for e in restored.ingested_ids)

    def test_old_entries_are_pruned(self, tmp_path: Path) -> None:
        """Entries older than 7 days must be dropped on save."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        stale_id = str(ULID())
        # Timestamp well beyond the 7-day TTL window
        p.ingested_ids.append({"id": stale_id, "ingested_at": "2020-01-01T00:00:00Z"})
        save_profile(p, profile_path)

        restored = load_profile(profile_path)
        assert not any(e["id"] == stale_id for e in restored.ingested_ids)

    def test_save_stores_dicts_not_strings(self, tmp_path: Path) -> None:
        """Saved ingested_ids must be dicts with 'id' and 'ingested_at' keys."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        valid_id = str(ULID())
        p.ingested_ids.append({"id": valid_id, "ingested_at": recent_ts})
        save_profile(p, profile_path)

        from aya.adapters.ledger import Ledger

        ids = Ledger.load().ingested
        assert len(ids) == 1
        assert ids[0]["id"] == valid_id
        assert ids[0]["ingested_at"] == recent_ts


# ── Issue #123: truncated ULID prefix migration ───────────────────────────────


class TestTruncatedUlidMigration:
    """Guard against truncated 8-char display prefixes being stored in ingested_ids."""

    def test_only_full_ulid_written_to_ingested_ids(self, tmp_path: Path) -> None:
        """Only the full 26-character ULID must appear in ingested_ids after save/load."""
        full_id = str(ULID())
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        p.ingested_ids.append({"id": full_id, "ingested_at": recent_ts})
        save_profile(p, profile_path)

        from aya.adapters.ledger import Ledger

        ids = Ledger.load().ingested
        assert len(ids) == 1
        assert ids[0]["id"] == full_id
        assert len(ids[0]["id"]) == 26

    def test_assert_valid_ulid_accepts_full_id(self) -> None:
        """_assert_valid_ulid must not raise for a valid 26-char ULID."""
        _assert_valid_ulid(str(ULID()))  # must not raise

    def test_assert_valid_ulid_rejects_truncated(self) -> None:
        """_assert_valid_ulid must raise ValueError for an 8-char display prefix."""
        truncated = str(ULID())[:8]
        with pytest.raises(ValueError, match="invalid ULID"):
            _assert_valid_ulid(truncated)

    def test_legacy_bare_string_invalid_ulid_dropped(self, tmp_path: Path) -> None:
        """Legacy bare-string entries that are not valid ULIDs must be dropped, not migrated."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"aya": {"ingested_ids": ["01KMEWBY"]}}))

        p = load_profile(profile_path)
        assert p.ingested_ids == [], "Invalid bare-string ULID must be dropped on load"


# ── _normalize_ingested_ids: from_did preservation ──────────────────────────


class TestNormalizeIngestedIdsFromDid:
    """Verify _normalize_ingested_ids preserves/omits from_did correctly."""

    def test_preserves_from_did_when_present(self) -> None:
        """Entries with from_did must retain that field after normalization."""
        valid_id = str(ULID())
        raw = [
            {"id": valid_id, "ingested_at": "2026-03-30T06:00:00Z", "from_did": "did:key:z6MkFoo"},
        ]
        result = _normalize_ingested_ids(raw)
        assert len(result) == 1
        assert result[0]["from_did"] == "did:key:z6MkFoo"

    def test_old_entries_without_from_did_preserved(self) -> None:
        """Entries without from_did must pass through without adding the field."""
        valid_id = str(ULID())
        raw = [{"id": valid_id, "ingested_at": "2026-03-30T06:00:00Z"}]
        result = _normalize_ingested_ids(raw)
        assert len(result) == 1
        assert "from_did" not in result[0]


# ── Profile schema_version ──────────────────────────────────────────────────


class TestProfileSchemaVersion:
    def test_save_includes_schema_version(self, tmp_path: Path) -> None:
        """Profile.save() writes schema_version into the aya section."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        p = load_profile(profile_path)
        save_profile(p, profile_path)

        data = json.loads(profile_path.read_text())
        assert data["aya"]["schema_version"] == PROFILE_SCHEMA_VERSION

    def test_load_without_schema_version_backward_compat(self, tmp_path: Path) -> None:
        """Profiles without schema_version load successfully (treated as v0)."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"aya": {"instances": {}}}))

        p = load_profile(profile_path)
        assert isinstance(p, Profile)

    def test_load_future_schema_version_warns(self, tmp_path: Path, caplog) -> None:
        """Loading a profile with a higher schema_version logs a warning."""
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"aya": {"schema_version": 999, "instances": {}}}))

        p = load_profile(profile_path)
        assert isinstance(p, Profile)
        assert "schema_version 999" in caplog.text
