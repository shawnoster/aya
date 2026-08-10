"""Tests for cli.py — smoke tests using typer.testing.CliRunner."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from aya.adapters.cli import app
from aya.adapters.profile_store import load_profile, save_profile
from aya.entities.identity import Identity, Profile, TrustedKey
from aya.entities.packet import Packet
from aya.scheduler import add_reminder

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(output: str) -> str:
    """Help text with styling removed.

    Rich styles the two dashes of a long option separately, so ``--message``
    is not a literal substring of coloured output. CI forces colour; local
    runs usually do not, which is exactly the kind of difference that passes
    here and fails there.
    """
    return _ANSI.sub("", output)


# ── TestVersion ───────────────────────────────────────────────────────────────


class TestVersion:
    def test_outputs_version(self) -> None:
        from importlib.metadata import version

        expected = version("aya-ai-assist")
        result = runner.invoke(app, ["version", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert f"aya {expected}" in result.output


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    return tmp_path / "assistant_profile.json"


@pytest.fixture
def profile_with_instance(profile_path: Path) -> Path:
    """Create a minimal profile with a 'default' instance already initialised."""
    identity = Identity.generate("default")
    profile = Profile()
    profile.instances["default"] = identity
    save_profile(profile, profile_path)
    return profile_path


@pytest.fixture
def profile_with_trusted(profile_with_instance: Path) -> Path:
    """Profile that also has a trusted 'home' key."""
    p = load_profile(profile_with_instance)
    home = Identity.generate("home")
    p.trusted_keys["home"] = TrustedKey(
        did=home.did, label="home", nostr_pubkey=home.nostr_public_hex
    )
    save_profile(p, profile_with_instance)
    return profile_with_instance


@pytest.fixture
def profile_with_named_instance(profile_path: Path) -> Path:
    """Profile with a single 'work' instance — no 'default' instance."""
    identity = Identity.generate("work")
    profile = Profile()
    profile.instances["work"] = identity
    save_profile(profile, profile_path)
    return profile_path


@pytest.fixture
def profile_with_multiple_instances(profile_path: Path) -> Path:
    """Profile with 'work' and 'laptop' instances — no 'default' instance."""
    profile = Profile()
    profile.instances["work"] = Identity.generate("work")
    profile.instances["laptop"] = Identity.generate("laptop")
    save_profile(profile, profile_path)
    return profile_path


@pytest.fixture
def profile_with_no_instances(profile_path: Path) -> Path:
    """Profile with no instances registered — simulates pre-init state."""
    profile = Profile()
    save_profile(profile, profile_path)
    return profile_path


@pytest.fixture
def profile_with_multiple_trusted(profile_with_instance: Path) -> Path:
    """Profile with two trusted keys — for testing ambiguous recipient errors."""
    p = load_profile(profile_with_instance)
    home = Identity.generate("home")
    laptop = Identity.generate("laptop")
    p.trusted_keys["home"] = TrustedKey(
        did=home.did, label="home", nostr_pubkey=home.nostr_public_hex
    )
    p.trusted_keys["laptop"] = TrustedKey(
        did=laptop.did, label="laptop", nostr_pubkey=laptop.nostr_public_hex
    )
    save_profile(p, profile_with_instance)
    return profile_with_instance


# ── init ─────────────────────────────────────────────────────────────────────


class TestInit:
    def test_creates_profile(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        result = runner.invoke(app, ["init", "--profile", str(path), "--label", "work"])
        assert result.exit_code == 0, result.output
        assert path.exists()

        data = json.loads(path.read_text())
        assert "work" in data["aya"]["instances"]

    def test_adds_instance_to_existing_profile(self, profile_with_instance: Path) -> None:
        result = runner.invoke(
            app, ["init", "--profile", str(profile_with_instance), "--label", "laptop"]
        )
        assert result.exit_code == 0, result.output

        data = json.loads(profile_with_instance.read_text())
        assert "laptop" in data["aya"]["instances"]
        assert "default" in data["aya"]["instances"]  # original still present

    def test_shows_did_in_output(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        result = runner.invoke(app, ["init", "--profile", str(path), "--label", "test"])
        assert result.exit_code == 0
        # Verify the DID was saved to the profile (Rich may escape the colon)
        data = json.loads(path.read_text())
        did = data["aya"]["instances"]["test"]["did"]
        assert did.startswith("did:key:")

    def test_saves_relay_url(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        relay = "wss://custom.relay.example.com"
        result = runner.invoke(app, ["init", "--profile", str(path), "--relay", relay])
        assert result.exit_code == 0
        data = json.loads(path.read_text())
        assert data["aya"]["default_relays"] == [relay]


# ── trust ─────────────────────────────────────────────────────────────────────


class TestTrust:
    def test_adds_trusted_key(self, profile_with_instance: Path) -> None:
        home = Identity.generate("home")
        result = runner.invoke(
            app,
            [
                "trust",
                home.did,
                "--peer",
                "home",
                "--profile",
                str(profile_with_instance),
            ],
        )
        assert result.exit_code == 0, result.output

        data = json.loads(profile_with_instance.read_text())
        assert "home" in data["aya"]["trusted_keys"]
        assert data["aya"]["trusted_keys"]["home"]["did"] == home.did

    def test_trust_requires_profile(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_profile.json"
        home = Identity.generate("home")
        result = runner.invoke(
            app,
            [
                "trust",
                home.did,
                "--peer",
                "home",
                "--profile",
                str(missing),
            ],
        )
        assert result.exit_code != 0

    def test_trust_warns_without_nostr_pubkey(self, profile_with_instance: Path) -> None:
        home = Identity.generate("home")
        result = runner.invoke(
            app,
            [
                "trust",
                home.did,
                "--peer",
                "home",
                "--profile",
                str(profile_with_instance),
                "--format",
                "text",
            ],
        )
        assert result.exit_code == 0
        assert "No Nostr pubkey" in result.output

    def test_trust_with_nostr_pubkey(self, profile_with_instance: Path) -> None:
        home = Identity.generate("home")
        result = runner.invoke(
            app,
            [
                "trust",
                home.did,
                "--peer",
                "home",
                "--nostr-pubkey",
                home.nostr_public_hex,
                "--profile",
                str(profile_with_instance),
            ],
        )
        assert result.exit_code == 0
        # Should NOT warn about missing nostr pubkey
        assert "No Nostr pubkey" not in result.output


# ── pair ──────────────────────────────────────────────────────────────────────


class TestPair:
    def test_initiator_stores_peer_under_peer_label(self, profile_with_instance: Path) -> None:
        """Initiator must store the peer DID under --peer label, not the local label.

        Regression test: before the fix, p.trusted_keys[trusted.label] used the
        label from the response content (which was the initiator's own label), so
        the peer DID overwrote the local self-trust entry.
        """
        from aya.usecases.pair import TrustedKey as PairTrustedKey

        local_identity = Identity.generate("guild-shawnoster")
        peer_identity = Identity.generate("sean-okeefe")

        p = load_profile(profile_with_instance)
        p.instances["guild-shawnoster"] = local_identity
        save_profile(p, profile_with_instance)

        # Simulate what poll_for_pair_response returns: TrustedKey whose label
        # is the initiator's own name (the bug: content["label"] was local label)
        buggy_trusted = PairTrustedKey(
            did=peer_identity.did,
            label="guild-shawnoster",  # wrong label — the old bug
            nostr_pubkey=peer_identity.nostr_public_hex,
        )

        with (
            patch("aya.adapters.cli.pair_cmds.generate_code", return_value="TEST-CODE-0001"),
            patch("aya.adapters.cli.pair_cmds.hash_code", return_value="deadbeef"),
            patch("aya.adapters.cli.pair_cmds.publish_pair_request", return_value="req_event_id"),
            patch("aya.adapters.cli.pair_cmds.poll_for_pair_response", return_value=buggy_trusted),
        ):
            result = runner.invoke(
                app,
                [
                    "pair",
                    "--peer",
                    "sean-okeefe",
                    "--as",
                    "guild-shawnoster",
                    "--profile",
                    str(profile_with_instance),
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(profile_with_instance.read_text())
        trusted_keys = data["aya"]["trusted_keys"]

        # Peer DID must be stored under the --peer label
        assert "sean-okeefe" in trusted_keys, "Peer not stored under --peer label"
        assert trusted_keys["sean-okeefe"]["did"] == peer_identity.did

        # Local label must NOT be overwritten with the peer DID
        assert (
            "guild-shawnoster" not in trusted_keys
            or trusted_keys.get("guild-shawnoster", {}).get("did") != peer_identity.did
        ), "Peer DID must not overwrite local label entry"

    def test_joiner_stores_peer_under_peer_label(self, profile_with_instance: Path) -> None:
        """Joiner must store the initiator DID under --peer label."""
        from aya.usecases.pair import TrustedKey as PairTrustedKey

        local_identity = Identity.generate("sean-okeefe")
        initiator_identity = Identity.generate("guild-shawnoster")

        p = load_profile(profile_with_instance)
        p.instances["sean-okeefe"] = local_identity
        save_profile(p, profile_with_instance)

        # join_pairing returns TrustedKey with the initiator's label from request content
        initiator_trusted = PairTrustedKey(
            did=initiator_identity.did,
            label="guild-shawnoster",
            nostr_pubkey=initiator_identity.nostr_public_hex,
        )

        with patch("aya.adapters.cli.pair_cmds.join_pairing", return_value=initiator_trusted):
            result = runner.invoke(
                app,
                [
                    "pair",
                    "--code",
                    "CRUSH-BASIL-9046",
                    "--peer",
                    "guild-shawnoster",
                    "--as",
                    "sean-okeefe",
                    "--profile",
                    str(profile_with_instance),
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(profile_with_instance.read_text())
        trusted_keys = data["aya"]["trusted_keys"]

        assert "guild-shawnoster" in trusted_keys, "Initiator not stored under --peer label"
        assert trusted_keys["guild-shawnoster"]["did"] == initiator_identity.did


# ── schedule remind ──────────────────────────────────────────────────────────


class TestScheduleRemind:
    def test_creates_reminder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))

        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "remind",
                "--message",
                "Stand up and stretch",
                "--due",
                "in 1 hour",
            ],
        )
        assert result.exit_code == 0, result.output

        data = json.loads(scheduler_file.read_text())
        assert len(data["items"]) == 1
        assert data["items"][0]["message"] == "Stand up and stretch"
        assert data["items"][0]["type"] == "reminder"

    def test_remind_requires_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler_file = tmp_path / "scheduler.json"
        scheduler_file.write_text(json.dumps({"items": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "remind",
                "--due",
                "in 1 hour",
            ],
        )
        assert result.exit_code != 0


# ── schedule dismiss ─────────────────────────────────────────────────────────


class TestScheduleDismiss:
    def test_dismiss_by_prefix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))

        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        item = add_reminder("Dismiss me via CLI", "in 1 hour")
        prefix = item["id"][:8]

        result = runner.invoke(app, ["schedule", "dismiss", prefix, "--format", "text"])
        assert result.exit_code == 0, result.output
        assert "Dismissed" in result.output

        data = json.loads(scheduler_file.read_text())
        assert data["items"][0]["status"] == "dismissed"

    def test_dismiss_not_found_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))

        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        result = runner.invoke(app, ["schedule", "dismiss", "nonexistent"])
        assert result.exit_code != 0


# ── send ──────────────────────────────────────────────────────────────────────


class TestSend:
    def test_send_sends_stdin_content(
        self, profile_with_trusted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_publish = AsyncMock(return_value="a" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "End of day notes",
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "text",
                ],
                input="Today I worked on useAlgolia error handling.\n",
            )
        assert result.exit_code == 0, result.output
        assert "Sent" in result.output
        assert "End of day notes" in result.output
        mock_publish.assert_awaited_once()

    def test_send_seed(self, profile_with_trusted: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_publish = AsyncMock(return_value="b" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "Pick up dinner party thread",
                    "--seed",
                    "--opener",
                    "Ask about the guest count decision",
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "text",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Sent" in result.output
        mock_publish.assert_awaited_once()

    def test_send_seed_requires_opener(self, profile_with_trusted: Path) -> None:
        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "home",
                "--intent",
                "seed without opener",
                "--seed",
                "--profile",
                str(profile_with_trusted),
            ],
        )
        assert result.exit_code != 0

    def test_send_unknown_recipient_fails(self, profile_with_instance: Path) -> None:
        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "nobody",
                "--intent",
                "fail",
                "--profile",
                str(profile_with_instance),
            ],
            input="data\n",
        )
        assert result.exit_code != 0

    def test_send_default_resolves_to_single_trusted_key(self, profile_with_trusted: Path) -> None:
        """'--to default' should succeed when exactly one trusted key exists."""
        mock_publish = AsyncMock(return_value="b" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "default",
                    "--intent",
                    "test",
                    "--profile",
                    str(profile_with_trusted),
                ],
                input="hello\n",
            )
        assert result.exit_code == 0, result.output
        assert "Unknown recipient" not in (result.output or "")
        mock_publish.assert_awaited_once()

    def test_send_unknown_recipient_lists_available(
        self, profile_with_multiple_trusted: Path
    ) -> None:
        """Error for unknown --to should list available recipient labels."""
        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "nobody",
                "--intent",
                "fail",
                "--profile",
                str(profile_with_multiple_trusted),
            ],
            input="data\n",
        )
        assert result.exit_code != 0
        assert "home" in result.output
        assert "laptop" in result.output

    def test_send_missing_instance_fails(self, profile_with_multiple_instances: Path) -> None:
        """When multiple instances exist and requested one is absent, send must fail.

        Uses a multi-instance profile so the smart single-instance fallback doesn't
        silently succeed — the non-existent name must produce a non-zero exit.
        """
        p = load_profile(profile_with_multiple_instances)
        home = Identity.generate("home")
        p.trusted_keys["home"] = TrustedKey(
            did=home.did, label="home", nostr_pubkey=home.nostr_public_hex
        )
        save_profile(p, profile_with_multiple_instances)

        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "home",
                "--intent",
                "fail",
                "--as",
                "nonexistent",
                "--profile",
                str(profile_with_multiple_instances),
            ],
            input="data\n",
        )
        assert result.exit_code != 0

    def test_send_missing_nostr_pubkey_fails(self, profile_with_instance: Path) -> None:
        """Trusted key without a Nostr pubkey should exit with a clear message."""
        p = load_profile(profile_with_instance)
        home = Identity.generate("home")
        p.trusted_keys["home"] = TrustedKey(did=home.did, label="home", nostr_pubkey=None)
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "home",
                "--intent",
                "no pubkey",
                "--profile",
                str(profile_with_instance),
            ],
            input="data\n",
        )
        assert result.exit_code != 0
        assert "Nostr pubkey" in result.output

    def test_send_relay_error_exits_cleanly(self, profile_with_trusted: Path) -> None:
        """Relay connection failure should print a friendly message, not a traceback."""
        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = AsyncMock(side_effect=Exception("conn refused"))
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "relay down",
                    "--profile",
                    str(profile_with_trusted),
                ],
                input="data\n",
            )
        assert result.exit_code != 0
        assert "Send failed" in result.output

    def test_send_in_reply_to(self, profile_with_trusted: Path) -> None:
        """--in-reply-to sets in_reply_to on the published packet."""
        captured_packet = None

        async def _capture_publish(signed, *a, **kw):
            nonlocal captured_packet
            captured_packet = signed
            return "c" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = AsyncMock(side_effect=_capture_publish)
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "follow-up notes",
                    "--in-reply-to",
                    "01JABC1234PARENT00000",
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "text",
                ],
                input="This is a reply.\n",
            )
        assert result.exit_code == 0, result.output
        assert captured_packet is not None
        assert captured_packet.in_reply_to == "01JABC1234PARENT00000"

    def test_send_in_reply_to_json(self, profile_with_trusted: Path) -> None:
        """--in-reply-to with --format json includes in_reply_to in output."""

        async def _capture_publish(signed, *a, **kw):
            return "d" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = AsyncMock(side_effect=_capture_publish)
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "threaded reply",
                    "--in-reply-to",
                    "01JABC1234PARENT00000",
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "json",
                    "--dry-run",
                ],
                input="Reply content.\n",
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["in_reply_to"] == "01JABC1234PARENT00000"


# ── schedule status ──────────────────────────────────────────────────────────


@pytest.fixture
def _isolate_scheduler(tmp_path, monkeypatch):
    """Point scheduler at a temp directory for CLI tests."""
    scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
    alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
    scheduler_file.parent.mkdir(parents=True)
    scheduler_file.write_text(json.dumps({"items": []}))
    alerts_file.write_text(json.dumps({"alerts": []}))
    monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
    monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)


@pytest.mark.usefixtures("_isolate_scheduler")
class TestHookCrons:
    @pytest.fixture
    def isolated_scheduler(self, tmp_path, monkeypatch):
        """Patch SCHEDULER_FILE, ALERTS_FILE, and REGISTERED_CRONS_FILE to a tmp dir.

        Without REGISTERED_CRONS_FILE patching the tests would leak writes to
        the real ~/.aya/session_registered_crons.json across the test suite.
        """
        sched_dir = tmp_path / "sched"
        sched_dir.mkdir()
        scheduler_file = sched_dir / "scheduler.json"
        alerts_file = sched_dir / "alerts.json"
        registered_file = sched_dir / "session_registered_crons.json"
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)
        monkeypatch.setattr("aya.scheduler.REGISTERED_CRONS_FILE", registered_file)
        return sched_dir

    def test_no_crons_exits_silently(self, isolated_scheduler):
        result = runner.invoke(app, ["hook", "crons"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_outputs_valid_json_with_crons(self, isolated_scheduler):
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "test-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "*/20 * * * *",
                            "prompt": "Do the thing.",
                        }
                    ]
                }
            )
        )

        result = runner.invoke(app, ["hook", "crons"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "hookSpecificOutput" in data
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "CronCreate" in ctx
        assert "test-cron" in ctx

    def test_multiple_crons_emit_separate_lines(self, isolated_scheduler):
        """Each session cron must produce its own JSON line so Claude Code
        creates a separate system reminder per cron — prevents truncation
        when multiple crons are bundled into a single hookSpecificOutput."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "cron-health",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "health-break",
                            "session_required": True,
                            "cron": "*/20 * * * *",
                            "prompt": "Take a break.",
                        },
                        {
                            "id": "cron-relay",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "relay-poll",
                            "session_required": True,
                            "cron": "*/10 * * * *",
                            "prompt": "Poll the relay.",
                        },
                    ]
                }
            )
        )

        result = runner.invoke(app, ["hook", "crons"])
        assert result.exit_code == 0

        lines = [ln for ln in result.output.strip().splitlines() if ln.strip()]
        assert len(lines) == 2, f"Expected 2 JSON lines, got {len(lines)}: {lines}"

        parsed = [json.loads(ln) for ln in lines]
        ids = set()
        for obj in parsed:
            assert "hookSpecificOutput" in obj
            ctx = obj["hookSpecificOutput"]["additionalContext"]
            assert "REQUIRED ACTION" in ctx
            assert "CronCreate" in ctx
            # Extract the cron id from the context
            for cron_id in ("cron-health", "cron-relay"):
                if cron_id in ctx:
                    ids.add(cron_id)

        assert ids == {"cron-health", "cron-relay"}, f"Missing cron IDs: {ids}"

    def test_escapes_double_quotes_in_prompt(self, isolated_scheduler):
        """Prompts with double quotes must be escaped to avoid malformed output."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "cron-quotes",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "*/5 * * * *",
                            "prompt": 'Say "hello" to the user.',
                        }
                    ]
                }
            )
        )

        result = runner.invoke(app, ["hook", "crons"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        # Quotes in the prompt must be escaped
        assert r"\"hello\"" in ctx
        # Must not contain unescaped quotes that would break parsing
        assert 'prompt="Say \\"hello\\" to the user."' in ctx

    def test_does_not_claim_alerts(self, isolated_scheduler):
        """hook crons must not consume alerts — they belong to schedule pending."""
        alerts_file = isolated_scheduler / "alerts.json"
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "alert-1",
                            "source_item_id": "watch-1",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "PR merged",
                            "details": {},
                            "seen": False,
                        }
                    ]
                }
            )
        )

        # Run hook crons
        runner.invoke(app, ["hook", "crons"])

        # Alerts must still be unseen
        alerts = json.loads(alerts_file.read_text())["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["seen"] is False
        assert "delivered_at" not in alerts[0]

    def test_second_call_emits_nothing_when_already_registered(self, isolated_scheduler):
        """The mid-session re-registration guard: hook crons should track
        which IDs it has emitted and skip them on subsequent calls."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "tracker-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "Tick.",
                        }
                    ]
                }
            )
        )

        first = runner.invoke(app, ["hook", "crons"])
        assert first.exit_code == 0
        assert "tracker-cron" in first.output

        second = runner.invoke(app, ["hook", "crons"])
        assert second.exit_code == 0
        assert second.output.strip() == ""  # already registered, nothing new

    def test_reset_flag_clears_tracker_and_re_emits(self, isolated_scheduler):
        """--reset (used at SessionStart) should clear the tracker so a fresh
        session re-registers everything from scratch."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "reset-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "Tick.",
                        }
                    ]
                }
            )
        )

        first = runner.invoke(app, ["hook", "crons"])
        assert "reset-cron" in first.output

        second = runner.invoke(app, ["hook", "crons", "--reset"])
        assert second.exit_code == 0
        # After --reset the tracker is empty, so the cron is re-emitted
        assert "reset-cron" in second.output

    def test_new_cron_added_mid_session_is_picked_up(self, isolated_scheduler):
        """Add a cron after the first hook crons call, then re-run — only
        the new cron should be emitted on the second call. This is the
        end-to-end behavior the PostToolUse hook relies on."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "old-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "old",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "Old.",
                        }
                    ]
                }
            )
        )

        first = runner.invoke(app, ["hook", "crons"])
        assert "old-cron" in first.output
        assert "new-cron" not in first.output

        # Mid-session: add a new cron
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "old-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "old",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "Old.",
                        },
                        {
                            "id": "new-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "new",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "New.",
                        },
                    ]
                }
            )
        )

        second = runner.invoke(app, ["hook", "crons"])
        assert second.exit_code == 0
        assert "new-cron" in second.output
        assert "old-cron" not in second.output  # already in tracker

    def test_event_flag_changes_hook_event_name(self, isolated_scheduler):
        """--event PostToolUse routes the additionalContext through the
        PostToolUse hook channel instead of SessionStart."""
        scheduler_file = isolated_scheduler / "scheduler.json"
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "event-cron",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "* * * * *",
                            "prompt": "Tick.",
                        }
                    ]
                }
            )
        )

        result = runner.invoke(app, ["hook", "crons", "--event", "PostToolUse"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


class TestHookWatchPushUpdates:
    def _isolate_scheduler(self, tmp_path: Path, monkeypatch):
        scheduler_file = tmp_path / "sched" / "scheduler.json"
        alerts_file = tmp_path / "sched" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)
        return scheduler_file, alerts_file

    def test_push_update_triggers_matching_watch_without_polling(self, tmp_path: Path, monkeypatch):
        scheduler_file, alerts_file = self._isolate_scheduler(tmp_path, monkeypatch)
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-pr-1",
                            "type": "watch",
                            "status": "active",
                            "message": "Review ready",
                            "provider": "github-pr",
                            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
                            "condition": "approved_or_merged",
                            "poll_interval_minutes": 30,
                            "last_checked_at": None,
                            "last_state": {
                                "pr_state": "open",
                                "merged": False,
                                "draft": False,
                                "title": "PR",
                                "reviews": [],
                                "has_approval": False,
                                "comment_count": 0,
                            },
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "session_required": False,
                            "tags": [],
                            "remove_when": "",
                        }
                    ]
                }
            )
        )

        payload = {
            "watch_update": {
                "provider": "github-pr",
                "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
                "state": {
                    "pr_state": "open",
                    "merged": False,
                    "draft": False,
                    "title": "PR",
                    "reviews": [{"user": "alice", "state": "APPROVED"}],
                    "has_approval": True,
                    "comment_count": 0,
                },
            }
        }

        with (
            patch("aya.usecases.watch_chains.poll_watch") as mock_poll,
            patch("aya.usecases.watch_chains.rewake_emit") as mock_rewake,
        ):
            from aya.usecases.watch_chains import _hook_watch_impl

            result = _hook_watch_impl(payload)

        assert result == 2
        mock_poll.assert_not_called()
        mock_rewake.assert_called_once()

        alerts = json.loads(alerts_file.read_text())["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["source_item_id"] == "watch-pr-1"
        assert "APPROVED by alice" in alerts[0]["message"]

        item = json.loads(scheduler_file.read_text())["items"][0]
        assert item["last_state"]["has_approval"] is True
        assert item["last_checked_at"] is not None

    def test_non_matching_push_update_falls_back_to_polling(self, tmp_path: Path, monkeypatch):
        scheduler_file, alerts_file = self._isolate_scheduler(tmp_path, monkeypatch)
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-pr-2",
                            "type": "watch",
                            "status": "active",
                            "message": "Review ready",
                            "provider": "github-pr",
                            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
                            "condition": "approved_or_merged",
                            "poll_interval_minutes": 30,
                            "last_checked_at": None,
                            "last_state": None,
                            "created_at": "2026-01-01T00:00:00+00:00",
                            "session_required": False,
                            "tags": [],
                            "remove_when": "",
                        }
                    ]
                }
            )
        )

        payload = {
            "watch_update": {
                "provider": "github-pr",
                "watch_config": {"owner": "acme", "repo": "widget", "pr": 99},
                "state": {
                    "pr_state": "open",
                    "merged": False,
                    "draft": False,
                    "title": "Other PR",
                    "reviews": [{"user": "alice", "state": "APPROVED"}],
                    "has_approval": True,
                    "comment_count": 0,
                },
            }
        }

        with (
            patch("aya.usecases.watch_chains.poll_watch", return_value=(None, False)) as mock_poll,
            patch("aya.usecases.watch_chains.rewake_emit") as mock_rewake,
        ):
            from aya.usecases.watch_chains import _hook_watch_impl

            result = _hook_watch_impl(payload)

        assert result == 0
        mock_poll.assert_called_once()
        mock_rewake.assert_not_called()
        assert json.loads(alerts_file.read_text())["alerts"] == []


@pytest.mark.usefixtures("_isolate_scheduler")
class TestScheduleStatusCLI:
    def test_status_exits_zero(self):
        result = runner.invoke(app, ["schedule", "status"])
        assert result.exit_code == 0

    def test_status_json_is_valid(self):
        result = runner.invoke(app, ["schedule", "status", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "active_watches" in data
        assert "pending_reminders" in data
        assert "total_items" in data

    def test_status_text_has_summary(self):
        result = runner.invoke(app, ["schedule", "status"])
        assert result.exit_code == 0
        assert "items" in result.output

    def test_pending_exits_zero(self):
        result = runner.invoke(app, ["schedule", "pending"])
        assert result.exit_code == 0

    def test_pending_json_is_valid(self):
        result = runner.invoke(app, ["schedule", "pending", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "alerts" in data
        assert "session_crons" in data

    def test_pending_json_long_prompt_no_wrapping(self, tmp_path, monkeypatch):
        """Regression: Rich console.print() wraps at 80 cols, injecting literal
        newlines inside JSON string values.  console.out() must be used instead.
        See https://github.com/shawnoster/aya/issues/66"""
        scheduler_file = tmp_path / "sched" / "scheduler.json"
        alerts_file = tmp_path / "sched" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        long_prompt = "A" * 200  # well past any terminal width
        scheduler_file.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "test-long",
                            "type": "recurring",
                            "status": "active",
                            "created_at": "2026-01-01T00:00:00-07:00",
                            "message": "test",
                            "session_required": True,
                            "cron": "*/20 * * * *",
                            "prompt": long_prompt,
                        }
                    ]
                }
            )
        )
        alerts_file.write_text(json.dumps({"alerts": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        result = runner.invoke(app, ["schedule", "pending", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)  # must not raise
        crons = data["session_crons"]
        assert len(crons) == 1
        assert crons[0]["prompt"] == long_prompt

    def test_tick_exits_zero(self):
        result = runner.invoke(app, ["schedule", "tick", "--quiet"])
        assert result.exit_code == 0


# ── receive ───────────────────────────────────────────────────────────────────


class TestReceive:
    @pytest.fixture
    def sender(self) -> Identity:
        return Identity.generate("work")

    @pytest.fixture
    def profile_with_sender(self, profile_with_instance: Path, sender: Identity) -> Path:
        """Profile with a 'default' instance and 'work' registered as a trusted sender."""
        p = load_profile(profile_with_instance)
        p.trusted_keys["work"] = TrustedKey(
            did=sender.did, label="work", nostr_pubkey=sender.nostr_public_hex
        )
        save_profile(p, profile_with_instance)
        return profile_with_instance

    def _signed_packet(self, sender: Identity, to_did: str, intent: str = "Test packet") -> Packet:
        pkt = Packet(
            from_did=sender.did,
            to_did=to_did,
            intent=intent,
            content="Test content.",
        )
        return pkt.sign(sender)

    def test_fetch_pending_called_without_since(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """receive must call fetch_pending() with no since argument."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)

        fetch_calls: list[tuple] = []

        async def mock_fetch(*args, **kwargs):
            fetch_calls.append((args, kwargs))
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            runner.invoke(
                app,
                ["receive", "--auto-ingest", "--quiet", "--profile", str(profile_with_sender)],
            )

        assert len(fetch_calls) == 1
        assert fetch_calls[0] == ((), {})  # called with no positional or keyword args

    def test_skips_already_ingested_packets(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """Packets whose IDs are already in ingested_ids must be silently skipped."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Already seen")
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        p.ingested_ids.append({"id": packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["receive", "--auto-ingest", "--profile", str(profile_with_sender)],
            )

        assert "Already seen" not in result.output

    def test_auto_ingest_persists_packet_id(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """After auto-ingesting a trusted packet, its ID must be saved to ingested_ids."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="New packet")

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["receive", "--auto-ingest", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        saved = load_profile(profile_with_sender)
        assert any(e["id"] == packet.id for e in saved.ingested_ids)

    def test_relay_error_shows_friendly_message(self, profile_with_sender: Path) -> None:
        """A relay connection failure must print a friendly message, not raise."""

        async def mock_fetch(*args, **kwargs):
            if False:  # pragma: no cover
                yield  # makes this an async generator
            raise OSError("connection refused")

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["receive", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert "Could not reach relay" in result.output

        # Under --format json the same failure is machine-readable instead, so
        # a caller can tell an unreachable relay from a genuinely empty inbox.
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["receive", "--format", "json", "--profile", str(profile_with_sender)],
            )

        assert json.loads(result.output)["relay_reachable"] is False

    def test_yes_flag_ingests_untrusted_packet_without_prompt(
        self, profile_with_instance: Path
    ) -> None:
        """--yes must ingest packets from untrusted senders without prompting."""
        unknown_sender = Identity.generate("unknown")
        p = load_profile(profile_with_instance)
        packet = self._signed_packet(unknown_sender, p.instances["default"].did, intent="Untrusted")

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            mock_cls.return_value.send_receipt = AsyncMock()
            result = runner.invoke(
                app,
                ["receive", "--yes", "--profile", str(profile_with_instance)],
            )

        assert result.exit_code == 0, result.output
        saved = load_profile(profile_with_instance)
        assert any(e["id"] == packet.id for e in saved.ingested_ids)

    def test_yes_short_flag_works(self, profile_with_instance: Path) -> None:
        """-y must behave identically to --yes for untrusted senders and skip prompts."""
        unknown_sender = Identity.generate("unknown")
        p = load_profile(profile_with_instance)
        packet = self._signed_packet(
            unknown_sender, p.instances["default"].did, intent="Short flag"
        )

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("typer.confirm") as mock_confirm:
            mock_confirm.side_effect = AssertionError(
                "typer.confirm should not be called when -y is used"
            )
            with patch("aya.adapters.relay.RelayClient") as mock_cls:
                mock_cls.return_value.fetch_pending = mock_fetch
                mock_cls.return_value.send_receipt = AsyncMock()
                result = runner.invoke(
                    app,
                    ["receive", "-y", "--profile", str(profile_with_instance)],
                )

        assert result.exit_code == 0, result.output
        saved = load_profile(profile_with_instance)
        assert any(e["id"] == packet.id for e in saved.ingested_ids)

    def test_receive_no_since_filter(self, profile_with_sender: Path, sender: Identity) -> None:
        """receive always calls fetch_pending() with no since, even when last_checked is set.

        The since cursor was removed in issue #246 because it permanently excluded
        packets that landed before last_checked - 60s but were never ingested.
        ingested_ids is the authoritative dedup mechanism; the relay's 7-day TTL
        window is the correct bound.
        """
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)

        relay_url = p.default_relays[0]
        last_check_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
        p.last_checked[relay_url] = (
            last_check_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        save_profile(p, profile_with_sender)

        fetch_calls: list[tuple] = []

        async def mock_fetch(*args, **kwargs):
            fetch_calls.append((args, kwargs))
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            runner.invoke(
                app,
                ["receive", "--auto-ingest", "--quiet", "--profile", str(profile_with_sender)],
            )

        assert len(fetch_calls) == 1
        assert fetch_calls[0][1].get("since") is None

    def test_receive_last_checked_persistence(self, profile_with_sender: Path) -> None:
        """receive saves last_checked for each relay even when inbox is empty."""
        p = load_profile(profile_with_sender)
        relay_url = p.default_relays[0]
        assert relay_url not in p.last_checked  # clean slate

        async def mock_fetch(*args, **kwargs):
            if False:  # pragma: no cover
                yield  # makes this an async generator

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["receive", "--quiet", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        saved = load_profile(profile_with_sender)
        assert relay_url in saved.last_checked
        assert saved.last_checked[relay_url]  # non-empty ISO timestamp

    def test_receive_skip_untrusted(self, profile_with_sender: Path, sender: Identity) -> None:
        """--skip-untrusted must silently skip untrusted packets and ingest trusted ones."""
        p = load_profile(profile_with_sender)
        to_did = p.instances["default"].did

        trusted_packet = self._signed_packet(sender, to_did, intent="Trusted msg")
        untrusted_sender = Identity.generate("stranger")
        untrusted_packet = self._signed_packet(untrusted_sender, to_did, intent="Untrusted msg")

        async def mock_fetch(*args, **kwargs):
            yield trusted_packet
            yield untrusted_packet

        with patch("typer.confirm") as mock_confirm:
            mock_confirm.side_effect = AssertionError(
                "typer.confirm should not be called with --skip-untrusted"
            )
            with patch("aya.adapters.relay.RelayClient") as mock_cls:
                mock_cls.return_value.fetch_pending = mock_fetch
                result = runner.invoke(
                    app,
                    [
                        "receive",
                        "--auto-ingest",
                        "--skip-untrusted",
                        "--profile",
                        str(profile_with_sender),
                    ],
                )

        assert result.exit_code == 0, result.output
        saved = load_profile(profile_with_sender)
        assert any(e["id"] == trusted_packet.id for e in saved.ingested_ids)
        assert not any(e["id"] == untrusted_packet.id for e in saved.ingested_ids)

    def test_receive_skip_untrusted_json(self, profile_with_sender: Path, sender: Identity) -> None:
        """--skip-untrusted with --format json must include skipped=true for untrusted packets."""
        p = load_profile(profile_with_sender)
        to_did = p.instances["default"].did

        trusted_packet = self._signed_packet(sender, to_did, intent="Trusted json")
        untrusted_sender = Identity.generate("stranger")
        untrusted_packet = self._signed_packet(untrusted_sender, to_did, intent="Untrusted json")

        async def mock_fetch(*args, **kwargs):
            yield trusted_packet
            yield untrusted_packet

        with patch("typer.confirm") as mock_confirm:
            mock_confirm.side_effect = AssertionError(
                "typer.confirm should not be called with --skip-untrusted"
            )
            with patch("aya.adapters.relay.RelayClient") as mock_cls:
                mock_cls.return_value.fetch_pending = mock_fetch
                result = runner.invoke(
                    app,
                    [
                        "receive",
                        "--auto-ingest",
                        "--skip-untrusted",
                        "--format",
                        "json",
                        "--profile",
                        str(profile_with_sender),
                    ],
                )

        assert result.exit_code == 0, result.output
        import json

        data = json.loads(result.output)
        packets = data["packets"]
        assert len(packets) == 2

        trusted_entry = next(p for p in packets if p["id"] == trusted_packet.id)
        assert trusted_entry["ingested"] is True
        assert "skipped" not in trusted_entry

        untrusted_entry = next(p for p in packets if p["id"] == untrusted_packet.id)
        assert untrusted_entry["ingested"] is False
        assert untrusted_entry["skipped"] is True

    def test_receive_auto_ingest_prints_summary(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """receive --auto-ingest must print a text summary showing ingested count."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            mock_cls.return_value.send_receipt = AsyncMock()
            result = runner.invoke(
                app,
                [
                    "receive",
                    "--auto-ingest",
                    "--format",
                    "text",
                    "--profile",
                    str(profile_with_sender),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Ingested 1 of 1" in result.output


# ── inbox ─────────────────────────────────────────────────────────────────────


class TestInbox:
    @pytest.fixture
    def sender(self) -> Identity:
        return Identity.generate("work")

    @pytest.fixture
    def profile_with_sender(self, profile_with_instance: Path, sender: Identity) -> Path:
        p = load_profile(profile_with_instance)
        p.trusted_keys["work"] = TrustedKey(
            did=sender.did, label="work", nostr_pubkey=sender.nostr_public_hex
        )
        save_profile(p, profile_with_instance)
        return profile_with_instance

    def _signed_packet(self, sender: Identity, to_did: str, intent: str = "Test packet") -> Packet:
        pkt = Packet(
            from_did=sender.did,
            to_did=to_did,
            intent=intent,
            content="Test content.",
        )
        return pkt.sign(sender)

    def test_filters_ingested_packets_by_default(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """inbox must hide already-ingested packets unless --all is passed."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Old packet")
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        p.ingested_ids.append({"id": packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        assert "Old packet" not in result.output
        assert "Inbox empty" in result.output

    def test_shows_new_packets(self, profile_with_sender: Path, sender: Identity) -> None:
        """inbox must show packets not yet in ingested_ids."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Fresh packet")

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        assert "Fresh packet" in result.output

    def test_all_flag_shows_ingested_packets(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """inbox --all must show ingested packets marked as [ingested]."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Old packet")
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        p.ingested_ids.append({"id": packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--all", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        assert "Old packet" in result.output
        assert "[ingested]" in result.output

    def test_all_flag_shows_count_summary(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """inbox --all with some ingested packets must show a 'N total, M new' summary."""
        p = load_profile(profile_with_sender)
        ingested_packet = self._signed_packet(sender, p.instances["default"].did, intent="Ingested")
        new_packet = self._signed_packet(sender, p.instances["default"].did, intent="New")
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        p.ingested_ids.append({"id": ingested_packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield ingested_packet
            yield new_packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--all", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        assert "2 total, 1 new" in result.output

    def test_json_output_includes_ingested_field_with_all_flag(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """inbox --all --format json must include an 'ingested' field for each packet."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Already seen")
        recent_ts = (
            (datetime.now(UTC) - timedelta(days=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        p.ingested_ids.append({"id": packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--all", "--format", "json", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "packets" in data
        assert len(data["packets"]) == 1
        assert data["packets"][0]["ingested"] is True

    def test_json_output_reports_ingested_for_every_packet(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """inbox --format json reports `ingested` for every packet.

        Both surfaces now return the same listing shape; the field used to be
        omitted here and absent entirely over MCP, so a caller could not read
        both.
        """
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Fresh")

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "json", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "packets" in data
        assert len(data["packets"]) == 1
        assert data["packets"][0]["ingested"] is False


class TestAutoFormat:
    def test_auto_resolves_to_text_in_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When stdout is a TTY, AUTO should produce text output."""
        from aya.adapters.cli._kernel import OutputFormat, resolve_format

        monkeypatch.delenv("AYA_FORMAT", raising=False)
        with patch("aya.adapters.cli._kernel.sys") as mock_sys:
            mock_sys.stdout.isatty.return_value = True
            assert resolve_format(OutputFormat.AUTO) == OutputFormat.TEXT

        # And verify via CLI with explicit --format text
        result = runner.invoke(app, ["version", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("aya ")

    def test_auto_resolves_to_json_when_not_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When stdout.isatty() returns False, AUTO should resolve to JSON.
        CliRunner provides a non-TTY stdout, so the default should be JSON."""
        monkeypatch.delenv("AYA_FORMAT", raising=False)
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "version" in data

    def test_aya_format_env_overrides_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AYA_FORMAT=json should force JSON even in a TTY context."""
        monkeypatch.setenv("AYA_FORMAT", "json")
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "version" in data

    def test_aya_format_env_text_overrides_non_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AYA_FORMAT=text should force text even in a non-TTY context."""
        monkeypatch.setenv("AYA_FORMAT", "text")
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("aya ")

    def test_explicit_format_text_overrides_auto(self) -> None:
        """--format text must always produce text, regardless of TTY."""
        result = runner.invoke(app, ["version", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("aya ")

    def test_explicit_format_json_overrides_auto(self) -> None:
        """--format json must always produce JSON, regardless of TTY."""
        result = runner.invoke(app, ["version", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "version" in data

    def test_auto_can_be_passed_explicitly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--format auto should be accepted and resolve to JSON under non-TTY."""
        monkeypatch.delenv("AYA_FORMAT", raising=False)
        result = runner.invoke(app, ["version", "--format", "auto"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "version" in data


# ── ack ───────────────────────────────────────────────────────────────────────


class TestAck:
    """Tests for the `aya ack` command."""

    @pytest.fixture
    def profile_with_ingested(self, tmp_path: Path) -> tuple[Path, str, Identity]:
        """Profile with a 'default' instance, a trusted 'home' peer, and one ingested packet ID."""
        local = Identity.generate("default")
        home = Identity.generate("home")

        profile = Profile()
        profile.instances["default"] = local
        profile.trusted_keys["home"] = TrustedKey(
            did=home.did, label="home", nostr_pubkey=home.nostr_public_hex
        )

        # Add a fake ingested packet ID
        from datetime import UTC, datetime

        pkt = Packet(
            from_did=home.did,
            to_did=local.did,
            intent="seed from home",
        )
        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        profile.ingested_ids.append({"id": pkt.id, "ingested_at": now_iso, "from_did": home.did})

        profile_path = tmp_path / "profile.json"
        save_profile(profile, profile_path)
        return profile_path, pkt.id, home

    def test_ack_happy_path(self, profile_with_ingested: tuple) -> None:
        """ack sends an ACK packet and prints confirmation."""
        profile_path, packet_id, _home = profile_with_ingested
        mock_publish = AsyncMock(return_value="c" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "ack",
                    packet_id,
                    "looks good",
                    "--profile",
                    str(profile_path),
                    "--format",
                    "text",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "ACK sent" in result.output
        assert packet_id[:8] in result.output
        mock_publish.assert_awaited_once()

    def test_ack_prefix_match(self, profile_with_ingested: tuple) -> None:
        """ack resolves the full packet ID from a short prefix."""
        profile_path, packet_id, _home = profile_with_ingested
        prefix = packet_id[:8]
        mock_publish = AsyncMock(return_value="d" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                ["ack", prefix, "--profile", str(profile_path), "--format", "text"],
            )
        assert result.exit_code == 0, result.output
        assert "ACK sent" in result.output

    def test_ack_dismiss_flag(self, profile_with_ingested: tuple) -> None:
        """--dismiss sets the dismiss flag in the ACK content and uses default message."""
        profile_path, packet_id, _home = profile_with_ingested
        mock_publish = AsyncMock(return_value="e" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "ack",
                    packet_id,
                    "--dismiss",
                    "--profile",
                    str(profile_path),
                    "--format",
                    "text",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "ACK sent" in result.output
        # Verify ACK packet content has dismiss=True
        call_args = mock_publish.call_args
        ack_pkt: Packet = call_args[0][0]
        assert ack_pkt.intent == "ack"
        assert isinstance(ack_pkt.content, dict)
        assert ack_pkt.content["dismiss"] is True
        assert ack_pkt.content["message"] == "acknowledged"

    def test_ack_packet_has_correct_intent_and_reply_fields(
        self, profile_with_ingested: tuple
    ) -> None:
        """ACK packet must have intent='ack' and in_reply_to set to the original packet ID."""
        profile_path, packet_id, _home = profile_with_ingested
        mock_publish = AsyncMock(return_value="f" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            runner.invoke(
                app,
                ["ack", packet_id, "got it", "--profile", str(profile_path)],
            )
        ack_pkt: Packet = mock_publish.call_args[0][0]
        assert ack_pkt.intent == "ack"
        assert ack_pkt.in_reply_to == packet_id
        assert ack_pkt.content["in_reply_to"] == packet_id
        assert ack_pkt.content["message"] == "got it"

    def test_ack_unknown_packet_id_exits_nonzero(self, profile_with_ingested: tuple) -> None:
        """ack with an ID not in ingested_ids must exit non-zero."""
        profile_path, _packet_id, _home = profile_with_ingested
        result = runner.invoke(
            app,
            ["ack", "00000000000000000000000000", "--profile", str(profile_path)],
        )
        assert result.exit_code != 0

    def test_ack_no_trusted_peers_exits_nonzero(self, tmp_path: Path) -> None:
        """ack with no trusted peers (no Nostr pubkey) must exit non-zero."""
        local = Identity.generate("default")
        profile = Profile()
        profile.instances["default"] = local
        # A trusted key without a Nostr pubkey
        other = Identity.generate("other")
        profile.trusted_keys["other"] = TrustedKey(did=other.did, label="other", nostr_pubkey=None)

        from datetime import UTC, datetime

        pkt = Packet(from_did=other.did, to_did=local.did, intent="test")
        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        profile.ingested_ids.append({"id": pkt.id, "ingested_at": now_iso})

        profile_path = tmp_path / "profile.json"
        save_profile(profile, profile_path)

        result = runner.invoke(
            app,
            ["ack", pkt.id, "--profile", str(profile_path)],
        )
        assert result.exit_code != 0

    def test_ack_relay_error_exits_nonzero(self, profile_with_ingested: tuple) -> None:
        """ack must exit non-zero when the relay publish fails."""
        profile_path, packet_id, _home = profile_with_ingested
        mock_publish = AsyncMock(side_effect=Exception("relay down"))
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                ["ack", packet_id, "--profile", str(profile_path)],
            )
        assert result.exit_code != 0

    def test_ack_routes_to_correct_sender_with_multiple_peers(self, tmp_path: Path) -> None:
        """With two trusted peers, ack routes to the peer that sent the packet (via from_did)."""
        from datetime import UTC, datetime

        local = Identity.generate("default")
        peer_a = Identity.generate("peer_a")
        peer_b = Identity.generate("peer_b")

        profile = Profile()
        profile.instances["default"] = local
        profile.trusted_keys["peer_a"] = TrustedKey(
            did=peer_a.did, label="peer_a", nostr_pubkey=peer_a.nostr_public_hex
        )
        profile.trusted_keys["peer_b"] = TrustedKey(
            did=peer_b.did, label="peer_b", nostr_pubkey=peer_b.nostr_public_hex
        )

        # Ingest a packet from peer_a
        pkt = Packet(from_did=peer_a.did, to_did=local.did, intent="seed from A")
        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        profile.ingested_ids.append({"id": pkt.id, "ingested_at": now_iso, "from_did": peer_a.did})

        profile_path = tmp_path / "profile.json"
        save_profile(profile, profile_path)

        mock_publish = AsyncMock(return_value="a" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                ["ack", pkt.id, "thanks", "--profile", str(profile_path)],
            )
        assert result.exit_code == 0, result.output
        ack_pkt: Packet = mock_publish.call_args[0][0]
        assert ack_pkt.to_did == peer_a.did, "ACK must route to the original sender (peer_a)"

    def test_ack_falls_back_without_from_did(self, tmp_path: Path) -> None:
        """Old-style ingested entry (no from_did) falls back to sole trusted peer logic."""
        from datetime import UTC, datetime

        local = Identity.generate("default")
        peer = Identity.generate("peer")

        profile = Profile()
        profile.instances["default"] = local
        profile.trusted_keys["peer"] = TrustedKey(
            did=peer.did, label="peer", nostr_pubkey=peer.nostr_public_hex
        )

        # Old-style entry without from_did
        pkt = Packet(from_did=peer.did, to_did=local.did, intent="old seed")
        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        profile.ingested_ids.append({"id": pkt.id, "ingested_at": now_iso})

        profile_path = tmp_path / "profile.json"
        save_profile(profile, profile_path)

        mock_publish = AsyncMock(return_value="b" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                ["ack", pkt.id, "got it", "--profile", str(profile_path)],
            )
        assert result.exit_code == 0, result.output
        ack_pkt: Packet = mock_publish.call_args[0][0]
        assert ack_pkt.to_did == peer.did


# ── dry-run ─────────────────────────────────────────────────────────────────


class TestDryRun:
    """Tests for --dry-run flag across relay-publishing and state-mutating commands."""

    def test_send_raw_dry_run(self, profile_with_trusted: Path, tmp_path: Path) -> None:
        """--dry-run prints packet JSON and does not call publish."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]
        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="dry run test",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_publish = AsyncMock(return_value="a" * 64)
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--dry-run",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert output_data["id"] == pkt.id
        assert output_data["intent"] == "dry run test"
        mock_publish.assert_not_awaited()

    def test_send_dry_run(
        self, profile_with_trusted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--dry-run prints signed packet JSON and does not call publish."""
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_publish = AsyncMock(return_value="a" * 64)
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "dry send test",
                    "--dry-run",
                    "--profile",
                    str(profile_with_trusted),
                ],
                input="Some content for send.\n",
            )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert output_data["intent"] == "dry send test"
        assert "id" in output_data
        mock_publish.assert_not_awaited()

    def test_ack_dry_run(self, tmp_path: Path) -> None:
        """--dry-run prints ACK packet JSON and does not call publish."""
        from datetime import UTC, datetime

        local = Identity.generate("default")
        home = Identity.generate("home")

        profile = Profile()
        profile.instances["default"] = local
        profile.trusted_keys["home"] = TrustedKey(
            did=home.did, label="home", nostr_pubkey=home.nostr_public_hex
        )

        pkt = Packet(from_did=home.did, to_did=local.did, intent="seed from home")
        now_iso = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        profile.ingested_ids.append({"id": pkt.id, "ingested_at": now_iso, "from_did": home.did})

        profile_path = tmp_path / "profile.json"
        save_profile(profile, profile_path)

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_publish = AsyncMock(return_value="c" * 64)
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                ["ack", pkt.id, "looks good", "--dry-run", "--profile", str(profile_path)],
            )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert output_data["intent"] == "ack"
        assert "id" in output_data
        mock_publish.assert_not_awaited()

    def test_schedule_remind_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--dry-run prints reminder item and does not write to scheduler file."""
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))

        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "remind",
                "--message",
                "Stand up and stretch",
                "--due",
                "in 1 hour",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert "item" in output_data
        output_data = output_data["item"]
        assert output_data["type"] == "reminder"
        assert output_data["message"] == "Stand up and stretch"
        # Scheduler file should still be empty
        data = json.loads(scheduler_file.read_text())
        assert len(data["items"]) == 0

    def test_schedule_watch_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--dry-run prints watch preview and does not write to scheduler file."""
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "watch",
                "github-pr",
                "owner/repo#42",
                "--message",
                "PR ready",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert "item" in output_data
        output_data = output_data["item"]
        assert output_data["type"] == "watch"
        assert output_data["provider"] == "github-pr"
        assert output_data["target"] == "owner/repo#42"
        assert output_data["condition"] == "approved_or_merged"
        assert output_data["message"] == "PR ready"
        assert output_data["status"] == "active"
        assert output_data["poll_interval_minutes"] == 30
        data = json.loads(scheduler_file.read_text())
        assert len(data["items"]) == 0

    def test_schedule_watch_dry_run_invalid_target(self) -> None:
        """--dry-run with an invalid github-pr target is an argument error."""
        result = runner.invoke(
            app,
            ["schedule", "watch", "github-pr", "bad-format", "-m", "test", "--dry-run"],
        )
        assert result.exit_code == 2
        assert "owner/repo#123" in result.output

    def test_schedule_watch_accepts_ci_checks(self, tmp_path: Path) -> None:
        """The CLI must accept every provider the scheduler supports.

        A second, narrower gate in the CLI used to reject ci-checks while the
        MCP surface accepted it — same input, opposite outcome.
        """
        result = runner.invoke(
            app,
            ["schedule", "watch", "ci-checks", "o/r#1", "-m", "test", "--dry-run"],
        )
        assert result.exit_code == 0, result.output

    def test_schedule_watch_rejects_unknown_condition(self) -> None:
        """Condition validation reaches the CLI now that it shares the validator."""
        result = runner.invoke(
            app,
            [
                "schedule",
                "watch",
                "ci-checks",
                "o/r#1",
                "-m",
                "t",
                "--condition",
                "nonsense",
                "--dry-run",
            ],
        )
        assert result.exit_code == 2
        assert "checks_failed" in result.output

    def test_schedule_recurring_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--dry-run prints cron preview and does not write to scheduler file."""
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "recurring",
                "--message",
                "health check",
                "--cron",
                "*/15 * * * *",
                "--prompt",
                "Take a break",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert "item" in output_data
        output_data = output_data["item"]
        assert output_data["type"] == "recurring"
        assert output_data["cron"] == "*/15 * * * *"
        assert output_data["prompt"] == "Take a break"
        assert output_data["message"] == "health check"
        assert output_data["status"] == "active"
        assert output_data["session_required"] is True
        data = json.loads(scheduler_file.read_text())
        assert len(data["items"]) == 0

    def test_pair_dry_run(self, profile_with_instance: Path) -> None:
        """--dry-run prints pairing intent JSON without relay interaction."""
        result = runner.invoke(
            app,
            [
                "pair",
                "--peer",
                "work",
                "--dry-run",
                "--profile",
                str(profile_with_instance),
            ],
        )
        assert result.exit_code == 0, result.output
        output_data = json.loads(result.output)
        assert output_data["action"] == "initiate_pairing"
        assert output_data["peer_label"] == "work"


# ── TestStructuredErrors ────────────────────────────────────────────────────


class TestStructuredErrors:
    """Structured JSON errors on stderr when not a TTY."""

    def test_profile_not_found_json_error(self, tmp_path: Path) -> None:
        """Non-TTY stderr emits JSON with PROFILE_NOT_FOUND code."""
        bad_path = tmp_path / "nonexistent.json"
        result = runner.invoke(app, ["inbox", "--profile", str(bad_path)])
        assert result.exit_code == 1
        # CliRunner captures stderr; parse JSON from output
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "PROFILE_NOT_FOUND"
        assert str(bad_path) in payload["error"]["message"]
        assert payload["error"]["context"]["path"] == str(bad_path)

    def test_profile_not_found_tty_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TTY stderr emits Rich-formatted text, not JSON."""
        import io

        from aya.adapters.cli._kernel import ErrorCode, _emit_error

        fake_stderr = io.StringIO()
        fake_stderr.isatty = lambda: True  # type: ignore[attr-defined]
        monkeypatch.setattr("aya.adapters.cli._kernel.sys.stderr", fake_stderr)

        # _emit_error writes to the module-level `err` Console, which
        # resolves sys.stderr lazily — so we also redirect the Console's
        # output to our fake stream for capture.
        monkeypatch.setattr("aya.adapters.cli._kernel.err", Console(file=fake_stderr))

        with pytest.raises(typer.Exit):
            _emit_error(
                ErrorCode.PROFILE_NOT_FOUND,
                "Profile not found at /tmp/x. Run 'aya init' first.",
                {"path": "/tmp/x"},
            )
        output = fake_stderr.getvalue()
        # Should NOT be valid JSON — Rich text instead
        with pytest.raises(json.JSONDecodeError):
            json.loads(output)
        assert "Profile not found" in output

    def test_instance_not_found_json_error(self, profile_with_multiple_instances: Path) -> None:
        """Non-TTY stderr emits JSON with INSTANCE_NOT_FOUND code."""
        result = runner.invoke(
            app,
            ["inbox", "--as", "nosuch", "--profile", str(profile_with_multiple_instances)],
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "INSTANCE_NOT_FOUND"
        assert payload["error"]["context"]["instance"] == "nosuch"

    def test_packet_not_found_json_error(self, profile_with_instance: Path) -> None:
        """Non-TTY stderr emits JSON with PACKET_NOT_FOUND code for unknown ack ID."""
        fake_id = "01AAAAAA00000000000000ZZZZ"
        result = runner.invoke(
            app,
            ["ack", fake_id, "--profile", str(profile_with_instance)],
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "PACKET_NOT_FOUND"
        assert payload["error"]["context"]["packet_id"] == fake_id


# ── JSON format for mutating commands ────────────────────────────────────────


class TestJsonFormat:
    """Tests for --format json on mutating CLI commands (#137)."""

    def test_init_json_format(self, tmp_path: Path) -> None:
        """init --format json outputs JSON with profile_path and did."""
        path = tmp_path / "profile.json"
        result = runner.invoke(
            app, ["init", "--profile", str(path), "--label", "test", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["profile_path"] == str(path)
        assert data["did"].startswith("did:key:")
        assert data["instance"] == "test"

    def test_trust_json_format(self, profile_with_instance: Path) -> None:
        """trust --format json outputs JSON with did and label."""
        home = Identity.generate("home")
        result = runner.invoke(
            app,
            [
                "trust",
                home.did,
                "--peer",
                "home",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["did"] == home.did
        assert data["label"] == "home"
        assert data["nostr_pubkey"] is None

    def test_send_raw_json_format(self, profile_with_trusted: Path, tmp_path: Path) -> None:
        """send-raw --format json outputs JSON with packet_id and event_id."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]
        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="json format test",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        mock_event_id = "e" * 64
        mock_publish = AsyncMock(return_value=mock_event_id)
        with patch("aya.adapters.relay.RelayClient") as mock_client_cls:
            mock_client_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "json",
                ],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["packet_id"] == pkt.id
        assert data["event_id"] == mock_event_id
        assert "relay" in data

    def test_schedule_remind_json_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """schedule remind --format json outputs {"item": ...} wrapper."""
        scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
        alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
        scheduler_file.parent.mkdir(parents=True)
        scheduler_file.write_text(json.dumps({"items": []}))
        alerts_file.write_text(json.dumps({"alerts": []}))

        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
        monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)

        result = runner.invoke(
            app,
            [
                "schedule",
                "remind",
                "--message",
                "Test reminder",
                "--due",
                "in 1 hour",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "item" in data
        data = data["item"]
        assert data["message"] == "Test reminder"
        assert data["type"] == "reminder"
        assert "id" in data


# ── TestPacketPersistence ────────────────────────────────────────────────────


class TestPacketPersistence:
    """Tests for packet persistence, show, and packets commands."""

    @pytest.fixture
    def packets_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Set up a packets directory and patch PACKETS_DIR to point to it."""
        packets = tmp_path / "packets"
        packets.mkdir()
        import aya.adapters.paths

        monkeypatch.setattr(aya.adapters.paths, "PACKETS_DIR", packets)
        return packets

    @pytest.fixture
    def sample_packet(self) -> Packet:
        local = Identity.generate("default")
        home = Identity.generate("home")
        return Packet(
            from_did=home.did,
            to_did=local.did,
            intent="daily handoff",
            content="Here is today's summary.",
        )

    def test_ingest_persists_packet(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After _ingest, a packet JSON file should exist in PACKETS_DIR."""
        packets = tmp_path / "packets"
        import aya.adapters.paths

        monkeypatch.setattr(aya.adapters.paths, "PACKETS_DIR", packets)

        local = Identity.generate("default")
        home = Identity.generate("home")
        pkt = Packet(
            from_did=home.did,
            to_did=local.did,
            intent="seed from home",
            content="test content",
        )

        from aya.usecases.ingest import ingest as _ingest

        _ingest(pkt, quiet=True)

        assert packets.exists()
        packet_files = list(packets.glob("*.json"))
        assert len(packet_files) == 1
        assert packet_files[0].stem == pkt.id

    def test_read_panel_displays_body(self, packets_dir: Path, sample_packet: Packet) -> None:
        """read --panel renders body in a Rich panel with title."""
        packet_file = packets_dir / f"{sample_packet.id}.json"
        packet_file.write_text(sample_packet.to_json())

        result = runner.invoke(app, ["read", sample_packet.id[:8], "--panel", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert "daily handoff" in result.output

    def test_read_panel_preserves_bracket_sequences(self, packets_dir: Path) -> None:
        """read --panel must not interpret [...] in the body as Rich markup."""
        local = Identity.generate("default")
        home = Identity.generate("home")
        # Body contains text that Rich would normally treat as markup.
        body_with_markup = "log line: [error] something [bold]important[/bold] happened"
        pkt = Packet(
            from_did=home.did,
            to_did=local.did,
            intent="log",
            content=body_with_markup,
        )
        (packets_dir / f"{pkt.id}.json").write_text(pkt.to_json())

        result = runner.invoke(app, ["read", pkt.id[:8], "--panel", "--format", "text"])
        assert result.exit_code == 0, result.output
        # The literal [error] / [bold] text must survive — it should NOT be
        # consumed or applied as markup.
        assert "[error]" in result.output
        assert "[bold]" in result.output

    def test_packets_list(
        self,
        packets_dir: Path,
    ) -> None:
        """packets command lists stored packets."""
        local = Identity.generate("default")
        home = Identity.generate("home")
        for i in range(3):
            pkt = Packet(
                from_did=home.did,
                to_did=local.did,
                intent=f"packet {i}",
                content=f"content {i}",
            )
            (packets_dir / f"{pkt.id}.json").write_text(pkt.to_json())

        result = runner.invoke(app, ["packets", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["packets"]) == 3

    def test_read_unknown_id(self, packets_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """read with an unknown ID exits nonzero."""
        monkeypatch.setenv("AYA_FORMAT", "json")
        result = runner.invoke(app, ["read", "00000000unknown"])
        assert result.exit_code != 0


# ── Idempotency ─────────────────────────────────────────────────────────────


class TestIdempotency:
    """Tests for --idempotency-key dedup on send-raw, send, and ack."""

    def test_send_raw_idempotency_key_dedup(
        self, profile_with_trusted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second send-raw with same key returns cached result without calling publish."""
        monkeypatch.setenv("AYA_HOME", str(tmp_path / "aya_home"))
        monkeypatch.setenv("AYA_FORMAT", "json")

        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="idempotent test",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        mock_publish = AsyncMock(return_value="e" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            # First send
            result1 = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--idempotency-key",
                    "key-1",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result1.exit_code == 0, result1.output
        data1 = json.loads(result1.output)
        assert "cached" not in data1
        mock_publish.assert_awaited_once()

        # Second send with same key — should be cached
        mock_publish2 = AsyncMock(return_value="f" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls2:
            mock_cls2.return_value.publish = mock_publish2
            result2 = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--idempotency-key",
                    "key-1",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result2.exit_code == 0, result2.output
        data2 = json.loads(result2.output)
        assert data2["cached"] is True
        assert data2["event_id"] == "e" * 64
        mock_publish2.assert_not_awaited()

    def test_send_raw_different_key_sends(
        self, profile_with_trusted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different idempotency keys both trigger publish."""
        monkeypatch.setenv("AYA_HOME", str(tmp_path / "aya_home"))
        monkeypatch.setenv("AYA_FORMAT", "json")

        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="test",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        for key_name in ("key-a", "key-b"):
            mock_publish = AsyncMock(return_value="a" * 64)
            with patch("aya.adapters.relay.RelayClient") as mock_cls:
                mock_cls.return_value.publish = mock_publish
                result = runner.invoke(
                    app,
                    [
                        "send-raw",
                        str(packet_file),
                        "--idempotency-key",
                        key_name,
                        "--profile",
                        str(profile_with_trusted),
                    ],
                )
            assert result.exit_code == 0, result.output
            mock_publish.assert_awaited_once()

    def test_send_idempotency_key(
        self, profile_with_trusted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Send with --idempotency-key dedup works the same as send-raw."""
        monkeypatch.setenv("AYA_HOME", str(tmp_path / "aya_home"))
        monkeypatch.setenv("AYA_FORMAT", "json")

        mock_publish = AsyncMock(return_value="d" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result1 = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "test send",
                    "--idempotency-key",
                    "send-key-1",
                    "--profile",
                    str(profile_with_trusted),
                ],
                input="send content\n",
            )
        assert result1.exit_code == 0, result1.output
        data1 = json.loads(result1.output)
        assert "cached" not in data1
        mock_publish.assert_awaited_once()

        # Second send with same key — cached
        mock_publish2 = AsyncMock(return_value="e" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls2:
            mock_cls2.return_value.publish = mock_publish2
            result2 = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "test send",
                    "--idempotency-key",
                    "send-key-1",
                    "--profile",
                    str(profile_with_trusted),
                ],
                input="send content\n",
            )
        assert result2.exit_code == 0, result2.output
        data2 = json.loads(result2.output)
        assert data2["cached"] is True
        mock_publish2.assert_not_awaited()

    def test_idempotency_cache_expires(
        self, profile_with_trusted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cache entries older than 24h are treated as expired — publish fires again."""
        aya_home = tmp_path / "aya_home"
        monkeypatch.setenv("AYA_HOME", str(aya_home))
        monkeypatch.setenv("AYA_FORMAT", "json")

        # Write an expired cache entry manually
        aya_home.mkdir(parents=True, exist_ok=True)
        expired_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        cache = {
            "expired-key": {
                "packet_id": "old_packet_id",
                "event_id": "old_event_id",
                "sent_at": expired_time,
            }
        }
        (aya_home / "sent_cache.json").write_text(json.dumps(cache))

        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="after expiry",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        mock_publish = AsyncMock(return_value="n" * 64)
        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = mock_publish
            result = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--idempotency-key",
                    "expired-key",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "cached" not in data  # should not be cached — expired
        mock_publish.assert_awaited_once()

    def test_send_raw_without_key_always_sends(
        self, profile_with_trusted: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --idempotency-key, every send-raw calls publish."""
        monkeypatch.setenv("AYA_HOME", str(tmp_path / "aya_home"))
        monkeypatch.setenv("AYA_FORMAT", "json")

        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="no key test",
            content="hello",
        )
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        for _ in range(2):
            mock_publish = AsyncMock(return_value="a" * 64)
            with patch("aya.adapters.relay.RelayClient") as mock_cls:
                mock_cls.return_value.publish = mock_publish
                result = runner.invoke(
                    app,
                    [
                        "send-raw",
                        str(packet_file),
                        "--profile",
                        str(profile_with_trusted),
                    ],
                )
            assert result.exit_code == 0, result.output
            mock_publish.assert_awaited_once()


# ── TestRead ──────────────────────────────────────────────────────────────────


class TestRead:
    """Tests for the `aya read` command."""

    @pytest.fixture
    def packets_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        packets = tmp_path / "packets"
        packets.mkdir()
        import aya.adapters.paths

        monkeypatch.setattr(aya.adapters.paths, "PACKETS_DIR", packets)
        return packets

    @pytest.fixture
    def seed_packet(self) -> Packet:
        local = Identity.generate("default")
        home = Identity.generate("home")
        return Packet.as_seed(
            from_did=home.did,
            to_did=local.did,
            intent="seed test",
            opener="What's the plan for tomorrow?",
            context_summary="Wrapping up the relay project.",
            open_questions=["who reviews?", "merge target?"],
        )

    @pytest.fixture
    def content_packet(self) -> Packet:
        local = Identity.generate("default")
        home = Identity.generate("home")
        return Packet(
            from_did=home.did,
            to_did=local.did,
            intent="markdown body",
            content="# Notes\n\nA short markdown body.",
        )

    def test_extracts_seed_opener_and_context(self, packets_dir: Path, seed_packet: Packet) -> None:
        (packets_dir / f"{seed_packet.id}.json").write_text(seed_packet.to_json())
        result = runner.invoke(app, ["read", seed_packet.id, "--format", "text"])
        assert result.exit_code == 0, result.output
        assert "What's the plan for tomorrow?" in result.output
        assert "Wrapping up the relay project." in result.output
        assert "who reviews?" in result.output
        assert "merge target?" in result.output

    def test_extracts_content_string(self, packets_dir: Path, content_packet: Packet) -> None:
        (packets_dir / f"{content_packet.id}.json").write_text(content_packet.to_json())
        result = runner.invoke(app, ["read", content_packet.id, "--format", "text"])
        assert result.exit_code == 0, result.output
        assert "A short markdown body." in result.output

    def test_meta_flag_adds_header(self, packets_dir: Path, seed_packet: Packet) -> None:
        (packets_dir / f"{seed_packet.id}.json").write_text(seed_packet.to_json())
        result = runner.invoke(app, ["read", seed_packet.id, "--meta", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert "seed test" in result.output  # intent
        assert seed_packet.id[:12] in result.output

    def test_json_format_returns_id_and_body(self, packets_dir: Path, seed_packet: Packet) -> None:
        (packets_dir / f"{seed_packet.id}.json").write_text(seed_packet.to_json())
        result = runner.invoke(app, ["read", seed_packet.id, "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == seed_packet.id
        assert "What's the plan" in data["body"]
        # No metadata fields without --meta
        assert "from" not in data

    def test_json_meta_includes_metadata_fields(
        self, packets_dir: Path, seed_packet: Packet
    ) -> None:
        (packets_dir / f"{seed_packet.id}.json").write_text(seed_packet.to_json())
        result = runner.invoke(app, ["read", seed_packet.id, "--meta", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["from"].startswith("did:key:")
        assert data["intent"] == "seed test"
        assert "sent_at" in data

    def test_prefix_match_resolves_full_id(self, packets_dir: Path, seed_packet: Packet) -> None:
        (packets_dir / f"{seed_packet.id}.json").write_text(seed_packet.to_json())
        prefix = seed_packet.id[:10]
        result = runner.invoke(app, ["read", prefix, "--format", "text"])
        assert result.exit_code == 0, result.output

    def test_packet_not_found_errors(self, packets_dir: Path) -> None:
        result = runner.invoke(app, ["read", "01XXXXXXXXXX", "--format", "text"])
        assert result.exit_code != 0

    def test_prefix_too_short_errors(self, packets_dir: Path) -> None:
        result = runner.invoke(app, ["read", "01XX", "--format", "text"])
        assert result.exit_code != 0

    def test_json_format_preserves_structured_body_for_json_content(
        self, packets_dir: Path
    ) -> None:
        """Non-seed dict content must pass through as a structured object
        in JSON output mode, not be stringified. Callers that pipe
        ``aya read --format json | jq`` should get a real object back."""
        from aya.entities.packet import ContentType

        local = Identity.generate("default")
        home = Identity.generate("home")
        pkt = Packet(
            from_did=home.did,
            to_did=local.did,
            intent="structured payload",
            content_type=ContentType.JSON,
            content={
                "event": "deployed",
                "version": "1.2.3",
                "checks": ["lint", "test"],
            },
        )
        (packets_dir / f"{pkt.id}.json").write_text(pkt.to_json())

        result = runner.invoke(app, ["read", pkt.id, "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # body is a dict, not a string containing pretty-printed JSON
        assert isinstance(data["body"], dict)
        assert data["body"]["event"] == "deployed"
        assert data["body"]["version"] == "1.2.3"
        assert data["body"]["checks"] == ["lint", "test"]

    def test_text_format_still_stringifies_json_content(self, packets_dir: Path) -> None:
        """Text mode output hasn't regressed: non-seed dicts still render as
        pretty-printed JSON for human reading."""
        from aya.entities.packet import ContentType

        local = Identity.generate("default")
        home = Identity.generate("home")
        pkt = Packet(
            from_did=home.did,
            to_did=local.did,
            intent="structured payload",
            content_type=ContentType.JSON,
            content={"event": "deployed", "version": "1.2.3"},
        )
        (packets_dir / f"{pkt.id}.json").write_text(pkt.to_json())

        result = runner.invoke(app, ["read", pkt.id, "--format", "text"])
        assert result.exit_code == 0, result.output
        # Text mode prints the pretty-printed JSON body
        assert '"event": "deployed"' in result.output
        assert '"version": "1.2.3"' in result.output


# ── TestDrop ──────────────────────────────────────────────────────────────────


class TestDrop:
    """Tests for the `aya drop` command and inbox filtering of dropped IDs."""

    @pytest.fixture
    def sender(self) -> Identity:
        return Identity.generate("work")

    @pytest.fixture
    def profile_with_sender(self, profile_with_instance: Path, sender: Identity) -> Path:
        p = load_profile(profile_with_instance)
        p.trusted_keys["work"] = TrustedKey(
            did=sender.did, label="work", nostr_pubkey=sender.nostr_public_hex
        )
        save_profile(p, profile_with_instance)
        return profile_with_instance

    def _signed_packet(self, sender: Identity, to_did: str, intent: str = "Test packet") -> Packet:
        pkt = Packet(
            from_did=sender.did,
            to_did=to_did,
            intent=intent,
            content="Test content.",
        )
        return pkt.sign(sender)

    def test_drop_full_id_persists_to_profile(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["drop", packet.id, "--profile", str(profile_with_sender), "--format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["dropped"] == packet.id
        assert data["already_dropped"] is False

        reloaded = load_profile(profile_with_sender)
        assert packet.id in reloaded.dropped_ids

    def test_drop_is_idempotent(self, profile_with_sender: Path, sender: Identity) -> None:
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)
        p.dropped_ids.append(packet.id)
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["drop", packet.id, "--profile", str(profile_with_sender), "--format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["already_dropped"] is True

        reloaded = load_profile(profile_with_sender)
        assert reloaded.dropped_ids.count(packet.id) == 1

    def test_drop_resolves_prefix_from_ingested_ids(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)
        recent_ts = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        p.ingested_ids.append({"id": packet.id, "ingested_at": recent_ts})
        save_profile(p, profile_with_sender)

        # No relay mock — should resolve from ingested_ids without hitting the network
        result = runner.invoke(
            app,
            ["drop", packet.id[:10], "--profile", str(profile_with_sender), "--format", "json"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["dropped"] == packet.id

    def test_drop_resolves_prefix_from_relay_when_not_ingested(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                [
                    "drop",
                    packet.id[:10],
                    "--profile",
                    str(profile_with_sender),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["dropped"] == packet.id

    def test_drop_packet_not_found_errors(self, profile_with_sender: Path) -> None:
        async def mock_fetch(*args, **kwargs):
            if False:  # pragma: no cover
                yield

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                [
                    "drop",
                    "01XXXXXXXXXX",
                    "--profile",
                    str(profile_with_sender),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code != 0

    def test_drop_prefix_too_short_errors(self, profile_with_sender: Path) -> None:
        result = runner.invoke(
            app,
            ["drop", "01XX", "--profile", str(profile_with_sender), "--format", "json"],
        )
        assert result.exit_code != 0

    def test_inbox_filters_dropped_packets(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Stuck packet")
        p.dropped_ids.append(packet.id)
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "text", "--profile", str(profile_with_sender)],
            )

        assert result.exit_code == 0, result.output
        assert "Stuck packet" not in result.output
        assert "Inbox empty" in result.output

    def test_inbox_all_also_filters_dropped(
        self, profile_with_sender: Path, sender: Identity
    ) -> None:
        """--all should also exclude dropped packets — drop is permanent ignore."""
        p = load_profile(profile_with_sender)
        packet = self._signed_packet(sender, p.instances["default"].did, intent="Dropped packet")
        p.dropped_ids.append(packet.id)
        save_profile(p, profile_with_sender)

        async def mock_fetch(*args, **kwargs):
            yield packet

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = mock_fetch
            result = runner.invoke(
                app,
                [
                    "inbox",
                    "--all",
                    "--format",
                    "text",
                    "--profile",
                    str(profile_with_sender),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Dropped packet" not in result.output

    def test_drop_relay_fetch_times_out(
        self,
        profile_with_sender: Path,
        sender: Identity,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A slow/large relay should not wedge `aya drop` indefinitely.

        Mocks `fetch_pending` as an async generator that sleeps longer
        than the configured timeout. The command should exit non-zero
        with a RELAY_TIMEOUT error. Uses a tiny timeout (0.1s) patched
        onto the cli module so the test is fast.
        """
        import asyncio as _asyncio

        monkeypatch.setattr("aya.adapters.cli.packet_cmds._RELAY_FETCH_TIMEOUT_SECONDS", 0.1)

        async def slow_fetch(*args, **kwargs):
            # Simulate a relay that keeps sending packets but each one
            # takes longer than the timeout window. In practice this
            # could be network latency, a large inbox, or a stalled
            # subscription.
            await _asyncio.sleep(2.0)
            # pragma: no cover — never reached because the timeout fires first
            if False:  # pragma: no cover
                yield

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = slow_fetch
            result = runner.invoke(
                app,
                [
                    "drop",
                    "01ABCDEFGH",  # prefix not in ingested/dropped — forces relay
                    "--profile",
                    str(profile_with_sender),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code != 0
        # Error payload includes the RELAY_TIMEOUT code + timeout duration
        assert "RELAY_TIMEOUT" in result.output
        assert "timed out" in result.output

    def test_drop_relay_unreachable(
        self,
        profile_with_sender: Path,
    ) -> None:
        """An unreachable relay should emit RELAY_UNREACHABLE, not PACKET_NOT_FOUND.

        Mocks `fetch_pending` to raise `RelayUnreachableError` — the error
        that `RelayClient` raises when all connection retries are exhausted.
        The command should exit non-zero with RELAY_UNREACHABLE in the output.
        """
        from aya.adapters.relay import RelayUnreachableError

        async def unreachable_fetch(*args, **kwargs):
            raise RelayUnreachableError("wss://relay.example.com")
            if False:  # pragma: no cover
                yield

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = unreachable_fetch
            result = runner.invoke(
                app,
                [
                    "drop",
                    "01ABCDEFGH",  # prefix not in ingested/dropped — forces relay
                    "--profile",
                    str(profile_with_sender),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code != 0
        assert "RELAY_UNREACHABLE" in result.output
        # Must NOT fall through to PACKET_NOT_FOUND
        assert "PACKET_NOT_FOUND" not in result.output


# ── TestSendSignatureValidation ───────────────────────────────────────────────


class TestSendSignatureValidation:
    """Tests for signature validation in `aya send`.

    Three paths:
      - Missing/invalid signature, from_did matches local → re-sign + send
      - Missing/invalid signature, from_did is external → reject
      - Valid signature → pass through unchanged
    """

    def test_resigns_when_signature_missing_and_local_is_sender(
        self, profile_with_trusted: Path, tmp_path: Path
    ) -> None:
        """Empty-sig packet authored by local instance is auto-signed before send."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="hand-edited packet",
            content="hello",
        )
        # Note: no .sign() call — signature is None
        assert pkt.signature is None
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        captured: dict = {}

        async def fake_publish(packet, *args, **kwargs):
            captured["packet"] = packet
            return "e" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = fake_publish
            result = runner.invoke(
                app,
                ["send-raw", str(packet_file), "--profile", str(profile_with_trusted)],
            )

        assert result.exit_code == 0, result.output
        assert captured["packet"].signature is not None
        # And the freshly applied signature is valid
        assert captured["packet"].verify_from_did()

    def test_resigns_when_signature_invalid_and_local_is_sender(
        self, profile_with_trusted: Path, tmp_path: Path
    ) -> None:
        """Garbage-sig packet authored by local instance is auto-resigned."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="bad sig packet",
            content="hello",
        )
        # Inject a bogus base64 signature so verify_from_did() returns False
        pkt.signature = "A" * 100
        assert not pkt.verify_from_did()
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        captured: dict = {}

        async def fake_publish(packet, *args, **kwargs):
            captured["packet"] = packet
            return "e" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = fake_publish
            result = runner.invoke(
                app,
                ["send-raw", str(packet_file), "--profile", str(profile_with_trusted)],
            )

        assert result.exit_code == 0, result.output
        # Signature replaced with a valid one
        assert captured["packet"].verify_from_did()

    def test_rejects_when_signature_missing_and_sender_is_external(
        self, profile_with_trusted: Path, tmp_path: Path
    ) -> None:
        """Empty-sig packet claiming to be from a different sender is refused."""
        p = load_profile(profile_with_trusted)
        home_key = p.trusted_keys["home"]
        other_sender = Identity.generate("offline")

        pkt = Packet(
            from_did=other_sender.did,
            to_did=home_key.did,
            intent="forged-looking packet",
            content="hello",
        )
        assert pkt.signature is None
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        publish_calls = 0

        async def fake_publish(*args, **kwargs):
            nonlocal publish_calls
            publish_calls += 1
            return "e" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = fake_publish
            result = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code != 0
        assert publish_calls == 0  # never reached the relay

    def test_passes_through_valid_signature(
        self, profile_with_trusted: Path, tmp_path: Path
    ) -> None:
        """Properly-signed packet sends without modification."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="properly signed",
            content="hello",
        ).sign(local)
        original_sig = pkt.signature
        assert pkt.verify_from_did()
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        captured: dict = {}

        async def fake_publish(packet, *args, **kwargs):
            captured["packet"] = packet
            return "e" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = fake_publish
            result = runner.invoke(
                app,
                ["send-raw", str(packet_file), "--profile", str(profile_with_trusted)],
            )

        assert result.exit_code == 0, result.output
        # Signature unchanged — pass-through, not re-signed
        assert captured["packet"].signature == original_sig

    def test_resign_surfaces_console_notice_in_text_mode(
        self, profile_with_trusted: Path, tmp_path: Path
    ) -> None:
        """When aya send-raw re-signs in interactive/text mode, the user
        should see a visible notice. Silent mutation is surprising."""
        p = load_profile(profile_with_trusted)
        local = p.instances["default"]
        home_key = p.trusted_keys["home"]

        pkt = Packet(
            from_did=local.did,
            to_did=home_key.did,
            intent="silent resign",
            content="hello",
        )
        assert pkt.signature is None
        packet_file = tmp_path / "packet.json"
        packet_file.write_text(pkt.to_json())

        async def fake_publish(packet, *args, **kwargs):
            return "e" * 64

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.publish = fake_publish
            result = runner.invoke(
                app,
                [
                    "send-raw",
                    str(packet_file),
                    "--profile",
                    str(profile_with_trusted),
                    "--format",
                    "text",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Re-signed packet" in result.output


# ── TestRelaySubcommand ───────────────────────────────────────────────────────


class TestRelayList:
    def test_list_text_shows_relays_in_order(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://relay.damus.io", "wss://nos.lol"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            ["relay", "list", "--profile", str(profile_with_instance), "--format", "text"],
        )
        assert result.exit_code == 0, result.output
        assert "wss://relay.damus.io" in result.output
        assert "wss://nos.lol" in result.output
        # Order check: damus appears before nos.lol
        assert result.output.index("wss://relay.damus.io") < result.output.index("wss://nos.lol")

    def test_list_json_shape(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example", "wss://b.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            ["relay", "list", "--profile", str(profile_with_instance), "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload == {"relays": ["wss://a.example", "wss://b.example"], "count": 2}

    def test_list_missing_profile_emits_structured_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(
            app,
            ["relay", "list", "--profile", str(missing), "--format", "json"],
        )
        assert result.exit_code == 1
        # Structured error goes to stderr, but CliRunner merges by default.
        # The error code should be recognizable either way.
        combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
        assert "PROFILE_NOT_FOUND" in combined or "not found" in combined.lower()


class TestRelayAdd:
    def test_add_appends_by_default(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://first.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://second.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "text",
            ],
        )
        assert result.exit_code == 0, result.output

        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://first.example", "wss://second.example"]

    def test_add_first_prepends(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://existing.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://new.example",
                "--first",
                "--profile",
                str(profile_with_instance),
                "--format",
                "text",
            ],
        )
        assert result.exit_code == 0, result.output

        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://new.example", "wss://existing.example"]

    def test_add_duplicate_is_noop(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://dup.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://dup.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["already_present"] is True
        assert payload["relays"] == ["wss://dup.example"]

        # Profile unchanged
        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://dup.example"]

    def test_add_rejects_non_websocket_scheme(self, profile_with_instance: Path) -> None:
        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "https://not-a-relay.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output

    def test_add_rejects_bare_scheme(self, profile_with_instance: Path) -> None:
        """wss:// with no host must not persist (Copilot review catch on #213)."""
        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output
        reloaded = load_profile(profile_with_instance)
        assert "wss://" not in reloaded.default_relays

    def test_add_rejects_internal_whitespace(self, profile_with_instance: Path) -> None:
        """urlparse accepts 'wss://relay .example' silently; the CLI must not."""
        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://relay .example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output


class TestRelayRemove:
    def test_remove_by_url(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example", "wss://b.example", "wss://c.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "wss://b.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "text",
            ],
        )
        assert result.exit_code == 0, result.output

        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://a.example", "wss://c.example"]

    def test_remove_by_index(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example", "wss://b.example", "wss://c.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "2",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["removed"] == "wss://b.example"

        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://a.example", "wss://c.example"]

    def test_remove_unknown_url_errors(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "wss://nope.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output

        # Profile unchanged
        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://a.example"]

    def test_remove_index_out_of_range_errors(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://only.example"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "5",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output

    def test_remove_last_requires_force(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://only.example"]
        save_profile(p, profile_with_instance)

        # Without --force: refuses
        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "wss://only.example",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2, result.output
        reloaded = load_profile(profile_with_instance)
        assert reloaded.default_relays == ["wss://only.example"]

        # With --force: allowed. The CLI response reports an empty list,
        # but load_profile() auto-refills from _DEFAULT_RELAYS on next read
        # (safety net in identity.py), so the disk state effectively resets
        # to the bootstrap defaults. We assert on the CLI response directly.
        result = runner.invoke(
            app,
            [
                "relay",
                "remove",
                "wss://only.example",
                "--force",
                "--profile",
                str(profile_with_instance),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["removed"] == "wss://only.example"
        assert payload["relays"] == []


class TestRelayStatus:
    def test_status_text_shows_instance_and_peers(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://relay.damus.io", "wss://nos.lol"]
        p.trusted_keys["home"] = TrustedKey(did="did:key:test123", label="home", nostr_pubkey=None)
        p.last_checked = {"wss://relay.damus.io": "2026-04-16T12:00:00Z"}
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            ["relay", "status", "--profile", str(profile_with_instance), "--format", "text"],
        )
        assert result.exit_code == 0, result.output
        assert "Instance:" in result.output
        assert "default" in result.output
        assert "Trusted peers:" in result.output
        assert "home" in result.output
        assert "wss://relay.damus.io" in result.output
        assert "Last poll:" in result.output
        assert "2026-04-16T12:00:00Z" in result.output

    def test_status_json_shape(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://relay.damus.io"]
        p.trusted_keys["home"] = TrustedKey(did="did:key:test456", label="home", nostr_pubkey=None)
        p.last_checked = {"wss://relay.damus.io": "2026-04-16T12:00:00Z"}
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            ["relay", "status", "--profile", str(profile_with_instance), "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["instance"] == "default"
        assert payload["trusted_peers"] == ["home"]
        assert payload["relays"] == ["wss://relay.damus.io"]
        assert payload["last_checked"] == {"wss://relay.damus.io": "2026-04-16T12:00:00Z"}

    def test_status_with_named_instance(self, profile_path: Path) -> None:
        profile = Profile()
        profile.instances["work"] = Identity.generate("work")
        profile.default_relays = ["wss://relay.example"]
        save_profile(profile, profile_path)

        result = runner.invoke(
            app,
            ["relay", "status", "--profile", str(profile_path), "--as", "work", "--format", "text"],
        )
        assert result.exit_code == 0, result.output
        assert "work" in result.output
        assert "wss://relay.example" in result.output

    def test_status_with_unknown_instance_errors(self, profile_path: Path) -> None:
        profile = Profile()
        profile.instances["work"] = Identity.generate("work")
        profile.instances["home"] = Identity.generate("home")
        save_profile(profile, profile_path)

        result = runner.invoke(
            app,
            ["relay", "status", "--profile", str(profile_path), "--as", "nope", "--format", "text"],
        )
        assert result.exit_code != 0

    def test_status_text_no_peers_no_poll(self, profile_with_instance: Path) -> None:
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://relay.damus.io"]
        save_profile(p, profile_with_instance)

        result = runner.invoke(
            app,
            ["relay", "status", "--profile", str(profile_with_instance), "--format", "text"],
        )
        assert result.exit_code == 0, result.output
        assert "(none)" in result.output
        assert "(never)" in result.output


# ── _maybe_create_ci_watch gh repo view parsing ─────────────────────────────


class TestMaybeCreateCiWatchRepoParsing:
    """Tests for gh-repo-view-based owner/repo parsing in _maybe_create_ci_watch."""

    def _make_subprocess_side_effect(self, responses: dict[str, tuple[int, str]]):
        """Return a side_effect function for subprocess.run that dispatches by command."""

        def _side_effect(cmd, **_kwargs):
            # Match by first 3 tokens, e.g. "git remote get-url"
            key = " ".join(cmd[:3])
            if key not in responses:
                # Try longer key for disambiguation
                key = " ".join(cmd[:4])
            rc, out = responses.get(key, (1, ""))
            return type("FakeResult", (), {"returncode": rc, "stdout": out})()

        return _side_effect

    def test_happy_path_parses_owner_repo(self):
        """gh repo view returns owner/repo -> proceeds to PR check and creates watch."""
        responses = {
            "git remote get-url": (0, "git@github.com:myorg/myrepo.git"),
            "git branch --show-current": (0, "fix/my-feature"),
            "gh repo view": (0, "myorg/myrepo"),
            "gh pr view": (0, "42"),
        }
        with (
            patch("subprocess.run", side_effect=self._make_subprocess_side_effect(responses)),
            patch("aya.usecases.watch_chains.get_active_watches", return_value=[]),
            patch("aya.usecases.watch_chains.add_watch") as mock_add,
        ):
            from aya.usecases.watch_chains import _maybe_create_ci_watch

            _maybe_create_ci_watch()
            mock_add.assert_called_once()
            call_kwargs = mock_add.call_args[1]
            assert call_kwargs["target"] == "myorg/myrepo#42"

    def test_dots_in_repo_name(self):
        """Repo names with dots are correctly parsed via split instead of regex."""
        responses = {
            "git remote get-url": (0, "git@github.com:owner/my.repo.name.git"),
            "git branch --show-current": (0, "feature/x"),
            "gh repo view": (0, "owner/my.repo.name"),
            "gh pr view": (0, "7"),
        }
        with (
            patch("subprocess.run", side_effect=self._make_subprocess_side_effect(responses)),
            patch("aya.usecases.watch_chains.get_active_watches", return_value=[]),
            patch("aya.usecases.watch_chains.add_watch") as mock_add,
        ):
            from aya.usecases.watch_chains import _maybe_create_ci_watch

            _maybe_create_ci_watch()
            mock_add.assert_called_once()
            call_kwargs = mock_add.call_args[1]
            assert call_kwargs["target"] == "owner/my.repo.name#7"

    def test_gh_not_available_returns_early(self):
        """When gh CLI fails (rc != 0), function returns without creating a watch."""
        responses = {
            "git remote get-url": (0, "git@github.com:org/repo.git"),
            "git branch --show-current": (0, "feature/x"),
            "gh repo view": (1, ""),
        }
        with (
            patch("subprocess.run", side_effect=self._make_subprocess_side_effect(responses)),
            patch("aya.usecases.watch_chains.get_active_watches", return_value=[]) as mock_watches,
            patch("aya.usecases.watch_chains.add_watch") as mock_add,
        ):
            from aya.usecases.watch_chains import _maybe_create_ci_watch

            _maybe_create_ci_watch()
            mock_add.assert_not_called()
            mock_watches.assert_not_called()

    def test_malformed_output_returns_early(self):
        """When gh repo view returns output without a slash, function returns early."""
        responses = {
            "git remote get-url": (0, "git@github.com:org/repo.git"),
            "git branch --show-current": (0, "feature/x"),
            "gh repo view": (0, "no-slash-here"),
        }
        with (
            patch("subprocess.run", side_effect=self._make_subprocess_side_effect(responses)),
            patch("aya.usecases.watch_chains.get_active_watches", return_value=[]) as mock_watches,
            patch("aya.usecases.watch_chains.add_watch") as mock_add,
        ):
            from aya.usecases.watch_chains import _maybe_create_ci_watch

            _maybe_create_ci_watch()
            mock_add.assert_not_called()
            mock_watches.assert_not_called()


# ── send/send-raw help text cross-references ─────────────────────────────────


class TestCommandHelpCrossReferences:
    """Verify that send and send-raw help text cross-reference each other."""

    def test_send_raw_help_mentions_send(self):
        result = runner.invoke(app, ["send-raw", "--help"])
        assert result.exit_code == 0, result.output
        assert "aya send" in result.output

    def test_send_help_mentions_send_raw(self):
        result = runner.invoke(app, ["send", "--help"])
        assert result.exit_code == 0, result.output
        assert "send-raw" in result.output


# ── silent-failure regressions ───────────────────────────────────────────────


@pytest.fixture
def profile_with_stub_default(profile_path: Path) -> Path:
    """Profile shaped like a real machine: a labelled instance plus a 'default' stub.

    This is what `aya init --label <name>` leaves behind, and the shape that
    made every poll silently use the stub's unrelated Nostr keypair.
    """
    profile = Profile()
    profile.instances["default"] = Identity.generate("default")
    profile.instances["harbor"] = Identity.generate("harbor")
    save_profile(profile, profile_path)
    return profile_path


class TestInstanceResolution:
    def test_omitted_as_prefers_sole_non_default_instance(self, profile_with_stub_default: Path):
        """`--as` omitted must not silently select the leftover 'default' stub."""
        p = load_profile(profile_with_stub_default)
        label, reason = p.resolve_instance_name(None)
        assert label == "harbor"
        assert reason == "sole-non-default"

    def test_primary_instance_wins(self, profile_with_stub_default: Path):
        p = load_profile(profile_with_stub_default)
        p.primary_instance = "default"
        assert p.resolve_instance_name(None)[0] == "default"

    def test_primary_instance_round_trips(self, profile_with_stub_default: Path):
        p = load_profile(profile_with_stub_default)
        p.primary_instance = "harbor"
        save_profile(p, profile_with_stub_default)
        assert load_profile(profile_with_stub_default).primary_instance == "harbor"

    def test_ambiguous_resolution_errors_rather_than_guessing(self, profile_path: Path):
        profile = Profile()
        profile.instances["work"] = Identity.generate("work")
        profile.instances["home"] = Identity.generate("home")
        save_profile(profile, profile_path)
        p = load_profile(profile_path)
        with pytest.raises(Exception, match="Multiple instances"):
            p.resolve_instance_name(None)

    def test_explicit_as_still_honoured(self, profile_with_stub_default: Path):
        p = load_profile(profile_with_stub_default)
        assert p.resolve_instance_name("default")[0] == "default"

    def test_use_sets_primary_instance(self, profile_with_stub_default: Path):
        result = runner.invoke(app, ["use", "harbor", "--profile", str(profile_with_stub_default)])
        assert result.exit_code == 0, result.output
        assert load_profile(profile_with_stub_default).primary_instance == "harbor"

    def test_use_rejects_unknown_label(self, profile_with_stub_default: Path):
        result = runner.invoke(app, ["use", "nope", "--profile", str(profile_with_stub_default)])
        assert result.exit_code != 0


class TestEmptyResultsAreSelfDescribing:
    """An empty inbox must state which identity and relays produced it."""

    def test_receive_empty_reports_instance_and_relays(self, profile_with_stub_default: Path):
        async def empty_fetch(*args, **kwargs):
            return
            yield  # pragma: no cover

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = empty_fetch
            result = runner.invoke(
                app,
                [
                    "receive",
                    "--auto-ingest",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_stub_default),
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["packets"] == []
        assert payload["instance"] == "harbor"
        assert payload["relay_reachable"] is True
        assert payload["relays"]

    def test_receive_unreachable_relay_is_distinguishable_from_empty(
        self, profile_with_stub_default: Path
    ):
        async def failing_fetch(*args, **kwargs):
            raise OSError("connection refused")
            yield  # pragma: no cover

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = failing_fetch
            result = runner.invoke(
                app,
                [
                    "receive",
                    "--auto-ingest",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_stub_default),
                ],
            )
        payload = json.loads(result.output)
        assert payload["packets"] == []
        assert payload["relay_reachable"] is False

    def test_inbox_empty_reports_instance_and_relays(self, profile_with_stub_default: Path):
        async def empty_fetch(*args, **kwargs):
            return
            yield  # pragma: no cover

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = empty_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "json", "--profile", str(profile_with_stub_default)],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["instance"] == "harbor"
        assert payload["relay_reachable"] is True

    def test_inbox_unreachable_relay_is_distinguishable_from_empty(
        self, profile_with_stub_default: Path
    ):
        async def failing_fetch(*args, **kwargs):
            raise OSError("connection refused")
            yield  # pragma: no cover

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = failing_fetch
            result = runner.invoke(
                app,
                ["inbox", "--format", "json", "--profile", str(profile_with_stub_default)],
            )
        payload = json.loads(result.output)
        assert payload["relay_reachable"] is False


class TestSendBodySources:
    def test_message_flag_populates_body(self, profile_with_trusted: Path):
        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "home",
                "--intent",
                "test",
                "--message",
                "# Hello\n\nbody text",
                "--dry-run",
                "--profile",
                str(profile_with_trusted),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "body text" in result.output

    def test_empty_body_is_rejected_not_silently_sent(self, profile_with_trusted: Path):
        result = runner.invoke(
            app,
            [
                "send",
                "--to",
                "home",
                "--intent",
                "test",
                "--message",
                "   ",
                "--dry-run",
                "--profile",
                str(profile_with_trusted),
            ],
        )
        assert result.exit_code == 2
        assert "body is empty" in result.output.lower()

    def test_send_help_documents_every_body_source(self):
        result = runner.invoke(app, ["send", "--help"])
        assert result.exit_code == 0
        for token in ("--message", "--files", "--opener", "stdin"):
            assert token in plain(result.output)


class TestWhoami:
    def test_whoami_lists_instances_and_peers(self, profile_with_trusted: Path):
        result = runner.invoke(
            app, ["whoami", "--format", "json", "--profile", str(profile_with_trusted)]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["active_instance"] == "default"
        assert [i["label"] for i in payload["instances"]] == ["default"]
        assert [p["label"] for p in payload["peers"]] == ["home"]

    def test_whoami_marks_ambiguity_instead_of_guessing(self, profile_path: Path):
        profile = Profile()
        profile.instances["work"] = Identity.generate("work")
        profile.instances["home"] = Identity.generate("home")
        save_profile(profile, profile_path)
        result = runner.invoke(app, ["whoami", "--format", "json", "--profile", str(profile_path)])
        payload = json.loads(result.output)
        assert payload["active_instance"] is None
        assert "ambiguous" in payload["resolved_by"]


# ── outbound log + per-relay delivery ────────────────────────────────────────


class TestSentLog:
    """`aya send` must leave a local trace with per-relay delivery status."""

    def _fake_client(self, report):
        class FakeClient:
            last_publish_report = report

            def __init__(self, *a, **kw):
                type(self).last_publish_report = report

            async def publish(self, packet, pubkey, encrypt=True):
                return "evt" + packet.id[-8:]

        return FakeClient

    def test_send_records_outbound_packet(self, profile_with_trusted: Path):
        report = [{"url": "wss://a", "ok": True, "error": None}]
        with patch("aya.adapters.relay.RelayClient", self._fake_client(report)):
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "hello",
                    "-m",
                    "body",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["relays_ok"] == ["wss://a"]
        assert payload["relays_failed"] == []

        saved = load_profile(profile_with_trusted)
        assert len(saved.sent_ids) == 1
        assert saved.sent_ids[0]["to_label"] == "home"
        assert saved.sent_ids[0]["intent"] == "hello"

    def test_partial_delivery_is_reported_not_hidden(self, profile_with_trusted: Path):
        """A relay that rejected must be named — publish succeeds if any accepts."""
        report = [
            {"url": "wss://good", "ok": True, "error": None},
            {"url": "wss://bad", "ok": False, "error": "503"},
        ]
        with patch("aya.adapters.relay.RelayClient", self._fake_client(report)):
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "hello",
                    "-m",
                    "body",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["relays_ok"] == ["wss://good"]
        assert payload["relays_failed"] == [{"url": "wss://bad", "error": "503"}]

    def test_sent_command_lists_and_filters(self, profile_with_trusted: Path):
        report = [
            {"url": "wss://good", "ok": True, "error": None},
            {"url": "wss://bad", "ok": False, "error": "503"},
        ]
        with patch("aya.adapters.relay.RelayClient", self._fake_client(report)):
            runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "partial",
                    "-m",
                    "b",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        with patch(
            "aya.adapters.relay.RelayClient",
            self._fake_client([{"url": "wss://good", "ok": True, "error": None}]),
        ):
            runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "clean",
                    "-m",
                    "b",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )

        result = runner.invoke(
            app, ["sent", "--format", "json", "--profile", str(profile_with_trusted)]
        )
        assert result.exit_code == 0, result.output
        intents = [p["intent"] for p in json.loads(result.output)["packets"]]
        assert intents == ["clean", "partial"]  # newest first

        result = runner.invoke(
            app,
            ["sent", "--failed", "--format", "json", "--profile", str(profile_with_trusted)],
        )
        failed = json.loads(result.output)["packets"]
        assert [p["intent"] for p in failed] == ["partial"]

    def test_sent_empty_by_default(self, profile_with_trusted: Path):
        result = runner.invoke(
            app, ["sent", "--format", "json", "--profile", str(profile_with_trusted)]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["packets"] == []

    def test_sent_ids_round_trip(self, profile_with_trusted: Path):
        p = load_profile(profile_with_trusted)
        p.sent_ids.append(
            {
                "id": "01KZN6N2Q4Q9NHRRQAHN0NFPCB",
                "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "to_did": "did:key:zAAA",
                "to_label": "home",
                "intent": "x",
                "event_id": "evt",
                "relays_ok": ["wss://a"],
                "relays_failed": [],
            }
        )
        save_profile(p, profile_with_trusted)
        assert len(load_profile(profile_with_trusted).sent_ids) == 1

    def test_sent_ids_pruned_after_ttl(self, profile_with_trusted: Path):
        p = load_profile(profile_with_trusted)
        old = (datetime.now(UTC) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
        p.sent_ids.append(
            {
                "id": "01KZN6N2Q4Q9NHRRQAHN0NFPCB",
                "sent_at": old,
                "to_did": "did:key:zAAA",
                "to_label": "home",
                "intent": "stale",
                "event_id": "evt",
                "relays_ok": [],
                "relays_failed": [],
            }
        )
        save_profile(p, profile_with_trusted)
        assert load_profile(profile_with_trusted).sent_ids == []


class TestDeliverySummary:
    """The one-line relay summary must not read the same for 2/2 and 1/2."""

    def test_summary_distinguishes_partial_from_complete(self):
        from aya.adapters.outbox import delivery_summary

        complete = delivery_summary(["wss://a", "wss://b"], 2)
        partial = delivery_summary(["wss://a"], 2)
        assert complete != partial
        assert "2 of 2" in complete
        assert "1 of 2" in partial

    def test_summary_single_relay_stays_bare(self):
        from aya.adapters.outbox import delivery_summary

        assert delivery_summary(["wss://a"], 1) == "wss://a"

    def test_send_json_relay_field_reflects_delivery(self, profile_with_trusted: Path):
        report = [
            {"url": "wss://good", "ok": True, "error": None},
            {"url": "wss://bad", "ok": False, "error": "503"},
        ]

        class FakeClient:
            last_publish_report = report

            def __init__(self, *a, **kw):
                pass

            async def publish(self, packet, pubkey, encrypt=True):
                return "evt" + packet.id[-8:]

        with patch("aya.adapters.relay.RelayClient", FakeClient):
            result = runner.invoke(
                app,
                [
                    "send",
                    "--to",
                    "home",
                    "--intent",
                    "x",
                    "-m",
                    "b",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert "1 of 2" in json.loads(result.output)["relay"]

    def test_send_help_warns_exit_code_is_not_delivery(self):
        result = runner.invoke(app, ["send", "--help"])
        assert "relays_failed" in result.output


class TestNotIngestedErrorIsActionable:
    """A packet visible in `aya inbox` must not error as a bare 'not found'."""

    def test_read_names_the_remedy(self, profile_with_trusted: Path):
        result = runner.invoke(app, ["read", "--format", "json", "01ZZZZZZZZZZZZZZZZZZZZZZZZ"])
        assert result.exit_code != 0
        payload = json.loads(result.output)["error"]
        assert payload["code"] == "PACKET_NOT_FOUND"
        assert "aya receive" in payload["message"]
        assert "inbox" in payload["message"]

    def test_ack_names_the_remedy(self, profile_with_trusted: Path):
        result = runner.invoke(
            app,
            [
                "ack",
                "01ZZZZZZZZZZZZZZZZZZZZZZZZ",
                "hi",
                "--format",
                "json",
                "--profile",
                str(profile_with_trusted),
            ],
        )
        assert result.exit_code != 0
        assert "aya receive" in json.loads(result.output)["error"]["message"]

    def test_identity_less_commands_say_why(self):
        for cmd in ("read", "packets"):
            result = runner.invoke(app, [cmd, "--help"])
            assert "no --as" in plain(result.output), cmd


class TestRelayPromotion:
    """Pairing proves a relay reaches the peer; that fact must be kept."""

    def test_add_relay_appends_once(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a"]
        assert p.add_relay("wss://b") is True
        assert p.default_relays == ["wss://a", "wss://b"]
        assert p.add_relay("wss://b") is False

    def test_first_moves_an_already_present_relay(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a", "wss://b", "wss://c"]
        assert p.add_relay("wss://c", first=True) is True
        assert p.default_relays == ["wss://c", "wss://a", "wss://b"]

    def test_first_is_noop_when_already_leading(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a", "wss://b"]
        assert p.add_relay("wss://a", first=True) is False
        assert p.default_relays == ["wss://a", "wss://b"]

    def test_relay_add_first_reorders_existing(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example.com", "wss://b.example.com"]
        save_profile(p, profile_with_instance)
        result = runner.invoke(
            app,
            [
                "relay",
                "add",
                "wss://b.example.com",
                "--first",
                "--format",
                "json",
                "--profile",
                str(profile_with_instance),
            ],
        )
        assert result.exit_code == 0, result.output
        assert load_profile(profile_with_instance).default_relays[0] == "wss://b.example.com"

    def test_pairing_promotes_the_relay_it_used(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://public.example.com"]
        save_profile(p, profile_with_instance)

        peer = Identity.generate("bob")
        trusted = TrustedKey(did=peer.did, label="", nostr_pubkey=peer.nostr_public_hex)
        from aya.adapters.cli._kernel import _record_pairing

        p = load_profile(profile_with_instance)
        promoted = _record_pairing(
            p, profile_with_instance, "bob", trusted, ["wss://private.example.com"]
        )
        assert promoted == "wss://private.example.com"

        saved = load_profile(profile_with_instance)
        assert saved.default_relays[0] == "wss://private.example.com"
        assert "wss://public.example.com" in saved.default_relays  # fallback kept
        assert saved.trusted_keys["bob"].label == "bob"

    def test_pairing_over_existing_primary_reports_no_change(self, profile_with_instance: Path):
        p = load_profile(profile_with_instance)
        p.default_relays = ["wss://a.example.com", "wss://b.example.com"]
        save_profile(p, profile_with_instance)
        peer = Identity.generate("bob")
        trusted = TrustedKey(did=peer.did, label="", nostr_pubkey=peer.nostr_public_hex)
        from aya.adapters.cli._kernel import _record_pairing

        p = load_profile(profile_with_instance)
        assert (
            _record_pairing(p, profile_with_instance, "bob", trusted, ["wss://a.example.com"])
            is None
        )


class TestReceivePersistGuard:
    """A failed body write must not advance the ingest cursor."""

    def test_cursor_not_advanced_when_persist_fails(self, profile_with_trusted: Path):
        p = load_profile(profile_with_trusted)
        sender = Identity.generate("home")
        p.trusted_keys["home"] = TrustedKey(
            did=sender.did, label="home", nostr_pubkey=sender.nostr_public_hex
        )
        save_profile(p, profile_with_trusted)

        packet = Packet(
            from_did=sender.did,
            to_did=p.instances["default"].did,
            intent="persist-fail",
            content="body",
        ).sign(sender)

        async def fetch(*a, **kw):
            yield packet

        with (
            patch("aya.adapters.relay.RelayClient") as mock_cls,
            patch("aya.usecases.relay_ops.ingest_packet", return_value=False),
        ):
            mock_cls.return_value.fetch_pending = fetch
            result = runner.invoke(
                app,
                [
                    "receive",
                    "--auto-ingest",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)["packets"][0]
        assert summary["ingested"] is False
        assert summary["error"] == "persist_failed"
        assert load_profile(profile_with_trusted).ingested_ids == []


class TestDropSurvivesReceive:
    """`aya drop` must stop a packet resurfacing on *every* path, not just inbox."""

    def test_dropped_packet_is_not_reingested(self, profile_with_trusted: Path):
        p = load_profile(profile_with_trusted)
        sender = Identity.generate("home")
        p.trusted_keys["home"] = TrustedKey(
            did=sender.did, label="home", nostr_pubkey=sender.nostr_public_hex
        )
        save_profile(p, profile_with_trusted)

        packet = Packet(
            from_did=sender.did,
            to_did=p.instances["default"].did,
            intent="spam",
            content="unwanted",
        ).sign(sender)

        async def fetch(*a, **kw):
            yield packet

        # Drop it, then poll. It must not come back.
        p = load_profile(profile_with_trusted)
        p.dropped_ids.append(packet.id)
        save_profile(p, profile_with_trusted)

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            mock_cls.return_value.fetch_pending = fetch
            received = runner.invoke(
                app,
                [
                    "receive",
                    "--auto-ingest",
                    "--format",
                    "json",
                    "--profile",
                    str(profile_with_trusted),
                ],
            )
            listed = runner.invoke(
                app,
                ["inbox", "--format", "json", "--profile", str(profile_with_trusted)],
            )

        assert received.exit_code == 0, received.output
        assert json.loads(received.output)["packets"] == []
        assert json.loads(listed.output)["packets"] == []
        assert load_profile(profile_with_trusted).ingested_ids == []


class TestSendRawRequiresPubkey:
    """send-raw was the one publish path with no recipient-pubkey check."""

    def test_unpaired_recipient_is_rejected(self, profile_with_instance: Path, tmp_path: Path):
        p = load_profile(profile_with_instance)
        p.trusted_keys["bob"] = TrustedKey(did="did:key:zBOB", label="bob", nostr_pubkey=None)
        save_profile(p, profile_with_instance)

        packet_file = tmp_path / "pkt.json"
        packet = Packet(
            from_did=p.instances["default"].did,
            to_did="did:key:zBOB",
            intent="orphan",
            content="body",
        ).sign(p.instances["default"])
        packet_file.write_text(packet.to_json())

        with patch("aya.adapters.relay.RelayClient") as mock_cls:
            result = runner.invoke(
                app,
                ["send-raw", str(packet_file), "--profile", str(profile_with_instance)],
            )
            # Never reaches the relay: an event addressed to nobody would be
            # accepted by every relay and matched by none.
            mock_cls.return_value.publish.assert_not_called()

        assert result.exit_code != 0
        assert "Nostr pubkey" in result.output
