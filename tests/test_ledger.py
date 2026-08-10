"""Tests for the packet ledgers and the crash-safe write primitives."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aya.adapters.atomic import atomic_write_json, file_lock, locked_read_json
from aya.adapters.ledger import Ledger
from aya.adapters.profile_store import load_profile, save_profile
from aya.entities.identity import Identity, Profile


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TestAtomicWrite:
    def test_round_trips(self, tmp_path: Path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"a": 1})
        assert json.loads(target.read_text()) == {"a": 1}

    def test_applies_mode_before_the_file_is_visible(self, tmp_path: Path):
        """chmod after write leaves a window at umask default on a key file."""
        target = tmp_path / "secret.json"
        atomic_write_json(target, {"k": "v"}, mode=0o600)
        assert oct(target.stat().st_mode)[-3:] == "600"

    def test_leaves_no_temp_files_behind(self, tmp_path: Path):
        atomic_write_json(tmp_path / "x.json", {"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []

    def test_original_survives_a_failed_write(self, tmp_path: Path, monkeypatch):
        """A crash mid-write must not truncate the existing file.

        This is the failure that could previously destroy the only copy of the
        instance private keys.
        """
        target = tmp_path / "x.json"
        atomic_write_json(target, {"good": True})

        def boom(_fd):
            raise OSError("disk full")

        monkeypatch.setattr("aya.adapters.atomic.os.fsync", boom)
        with pytest.raises(OSError, match="disk full"):
            atomic_write_json(target, {"replacement": True})

        assert json.loads(target.read_text()) == {"good": True}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_locked_read_tolerates_corruption(self, tmp_path: Path):
        target = tmp_path / "x.json"
        target.write_text("not json {{{")
        assert locked_read_json(target, tmp_path / ".l") is None
        assert locked_read_json(tmp_path / "missing.json", tmp_path / ".l") is None

    def test_lock_is_reentrant_across_sequential_holders(self, tmp_path: Path):
        lock = tmp_path / ".l"
        with file_lock(lock):
            pass
        with file_lock(lock, shared=True):
            pass


class TestLedger:
    def test_round_trip(self):
        led = Ledger(ingested=[{"id": "a", "ingested_at": _iso(datetime.now(UTC))}], dropped=["z"])
        led.save()
        assert Ledger.load().dropped == ["z"]
        assert len(Ledger.load().ingested) == 1

    def test_prunes_past_ttl(self):
        old = _iso(datetime.now(UTC) - timedelta(days=8))
        new = _iso(datetime.now(UTC))
        Ledger(
            ingested=[{"id": "old", "ingested_at": old}, {"id": "new", "ingested_at": new}],
            sent=[{"id": "olds", "sent_at": old}, {"id": "news", "sent_at": new}],
        ).save()
        loaded = Ledger.load()
        assert [e["id"] for e in loaded.ingested] == ["new"]
        assert [e["id"] for e in loaded.sent] == ["news"]

    def test_keeps_entries_with_unparseable_timestamps(self):
        """Dropping these silently re-ingests the packet on the next poll."""
        Ledger(ingested=[{"id": "no-stamp"}, {"id": "bad", "ingested_at": "whenever"}]).save()
        assert {e["id"] for e in Ledger.load().ingested} == {"no-stamp", "bad"}

    def test_written_owner_only(self):
        Ledger(dropped=["a"]).save()
        assert oct(Ledger.path().stat().st_mode)[-3:] == "600"

    def test_missing_file_loads_empty(self):
        assert Ledger.load().ingested == []


class TestProfileLedgerSplit:
    def _profile(self, path: Path) -> Profile:
        path.write_text("{}")
        p = Profile()
        p.instances["harbor"] = Identity.generate("harbor")
        save_profile(p, path)
        return load_profile(path)

    def test_poll_does_not_rewrite_the_key_file(self, tmp_path: Path):
        path = tmp_path / "profile.json"
        p = self._profile(path)
        before = path.read_bytes()

        p.ingested_ids.append({"id": "x", "ingested_at": _iso(datetime.now(UTC))})
        save_profile(p, path)

        assert path.read_bytes() == before, "advancing a cursor rewrote the keystore"
        assert len(Ledger.load().ingested) == 1

    def test_real_profile_change_still_writes(self, tmp_path: Path):
        path = tmp_path / "profile.json"
        p = self._profile(path)
        p.primary_instance = "harbor"
        save_profile(p, path)
        assert json.loads(path.read_text())["aya"]["primary_instance"] == "harbor"

    def test_profile_written_owner_only(self, tmp_path: Path):
        path = tmp_path / "profile.json"
        self._profile(path)
        assert oct(path.stat().st_mode)[-3:] == "600"
