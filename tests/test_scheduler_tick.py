"""Tests for Phase 5B/5C — tick, pending, claims, harness detection, receipts, expiry, status."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from aya.scheduler import (
    _CLAIM_TTL_SECONDS,
    _detect_harness,
    add_seed_alert,
    claim_alert,
    expire_old_alerts,
    format_pending,
    format_scheduler_status,
    get_instance_id,
    get_pending,
    get_scheduler_status,
    load_alerts,
    run_tick,
    sweep_stale_claims,
)


@pytest.fixture(autouse=True)
def _isolate_scheduler(tmp_path, monkeypatch):
    """Point scheduler at a temp directory so tests don't touch real data."""
    scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
    alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
    scheduler_file.parent.mkdir(parents=True)
    scheduler_file.write_text(json.dumps({"items": []}))
    alerts_file.write_text(json.dumps({"alerts": []}))

    monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
    monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)


# ── Harness detection ────────────────────────────────────────────────────────


class TestHarnessDetection:
    def test_detects_claude(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        assert _detect_harness() == "claude"

    def test_detects_copilot(self, monkeypatch):
        # Clear any CLAUDE vars first
        for key in list(os.environ):
            if key.startswith("CLAUDE"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("COPILOT_AGENT", "1")
        assert _detect_harness() == "copilot"

    def test_unknown_fallback(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith(("CLAUDE", "COPILOT", "GITHUB_COPILOT")):
                monkeypatch.delenv(key, raising=False)
        assert _detect_harness() == "unknown"

    def test_instance_id_format(self):
        iid = get_instance_id()
        parts = iid.rsplit("-", 1)
        assert len(parts) == 2
        assert parts[0] in ("claude", "copilot", "unknown")
        assert parts[1].isdigit()


# ── Claim files ──────────────────────────────────────────────────────────────


class TestClaimAlert:
    def test_first_claim_succeeds(self):
        assert claim_alert("alert-001", "claude-1234") is True

    def test_second_claim_fails(self):
        claim_alert("alert-001", "claude-1234")
        assert claim_alert("alert-001", "claude-5678") is False

    def test_different_alerts_both_claimable(self):
        assert claim_alert("alert-001", "claude-1234") is True
        assert claim_alert("alert-002", "claude-1234") is True

    def test_stale_claim_reclaimable(self, tmp_path):
        """Claims past TTL can be re-claimed."""
        from aya.scheduler import _claims_dir, _get_local_tz

        claims = _claims_dir()
        claims.mkdir(parents=True, exist_ok=True)
        claim_path = claims / "alert-stale.claimed"

        # Write a claim from 10 minutes ago (past 5-min TTL)
        stale_time = (datetime.now(_get_local_tz()) - timedelta(minutes=10)).isoformat()
        claim_path.write_text(
            json.dumps(
                {
                    "instance": "claude-old",
                    "claimed_at": stale_time,
                    "ttl_seconds": _CLAIM_TTL_SECONDS,
                }
            )
        )

        assert claim_alert("alert-stale", "claude-new") is True

    def test_corrupt_claim_reclaimable(self, tmp_path):
        """Corrupt claim files are removed and re-claimable."""
        from aya.scheduler import _claims_dir

        claims = _claims_dir()
        claims.mkdir(parents=True, exist_ok=True)
        (claims / "alert-corrupt.claimed").write_text("not json{{{")

        assert claim_alert("alert-corrupt", "claude-1234") is True


class TestSweepStaleClaims:
    def test_sweeps_old_claims(self):
        from aya.scheduler import _claims_dir, _get_local_tz

        claims = _claims_dir()
        claims.mkdir(parents=True, exist_ok=True)

        # Write a claim from 2 days ago
        old_time = (datetime.now(_get_local_tz()) - timedelta(days=2)).isoformat()
        (claims / "old-alert.claimed").write_text(
            json.dumps(
                {
                    "instance": "claude-1",
                    "claimed_at": old_time,
                    "ttl_seconds": 300,
                }
            )
        )

        # Write a fresh claim
        claim_alert("fresh-alert", "claude-2")

        removed = sweep_stale_claims(max_age_seconds=86400)
        assert removed == 1
        assert not (claims / "old-alert.claimed").exists()
        assert (claims / "fresh-alert.claimed").exists()

    def test_sweep_empty_dir(self):
        assert sweep_stale_claims() == 0

    def test_sweep_nonexistent_dir(self):
        assert sweep_stale_claims() == 0


# ── run_tick ─────────────────────────────────────────────────────────────────


class TestRunTick:
    def test_tick_returns_sweep_count(self):
        result = run_tick(quiet=True)
        assert "claims_swept" in result
        assert isinstance(result["claims_swept"], int)

    def test_tick_sweeps_stale_claims(self):
        from aya.scheduler import _claims_dir, _get_local_tz

        claims = _claims_dir()
        claims.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now(_get_local_tz()) - timedelta(days=2)).isoformat()
        (claims / "old.claimed").write_text(
            json.dumps(
                {
                    "instance": "claude-1",
                    "claimed_at": old_time,
                    "ttl_seconds": 300,
                }
            )
        )

        result = run_tick(quiet=True)
        assert result["claims_swept"] == 1


# ── get_pending ──────────────────────────────────────────────────────────────


class TestGetPending:
    def test_empty_state(self):
        pending = get_pending("test-1")
        assert pending["alerts"] == []
        assert pending["session_crons"] == []
        assert pending["instance_id"] == "test-1"

    def test_claims_alerts(self, tmp_path):
        """Pending claims alerts and returns them."""
        from aya.scheduler import _alerts_file

        alerts_file = _alerts_file()
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "a1",
                            "source_item_id": "s1",
                            "created_at": datetime.now(UTC).isoformat(),
                            "message": "PR merged",
                            "details": {},
                            "seen": False,
                        },
                        {
                            "id": "a2",
                            "source_item_id": "s2",
                            "created_at": datetime.now(UTC).isoformat(),
                            "message": "Reminder due",
                            "details": {},
                            "seen": False,
                        },
                    ]
                }
            )
        )

        pending = get_pending("test-session")
        assert len(pending["alerts"]) == 2

        # Second call from different instance — already claimed
        pending2 = get_pending("other-session")
        assert len(pending2["alerts"]) == 0

    def test_returns_session_crons(self, tmp_path):
        """Session-required recurring items appear in pending."""
        from aya.scheduler import _scheduler_file

        sf = _scheduler_file()
        sf.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "cron-1",
                            "type": "recurring",
                            "status": "active",
                            "session_required": True,
                            "cron": "0,30 * * * *",
                            "prompt": "Update daily notes",
                            "message": "Daily progress logger",
                        },
                        {
                            "id": "watch-1",
                            "type": "watch",
                            "status": "active",
                            "session_required": False,
                        },
                    ]
                }
            )
        )

        pending = get_pending("test-1")
        assert len(pending["session_crons"]) == 1
        assert pending["session_crons"][0]["id"] == "cron-1"


# ── format_pending ───────────────────────────────────────────────────────────


class TestFormatPending:
    def test_with_alerts(self):
        from aya.scheduler import _get_local_tz

        now = datetime.now(_get_local_tz())
        pending = {
            "alerts": [
                {
                    "id": "a1",
                    "message": "PR #42 merged",
                    "created_at": (now - timedelta(minutes=5)).isoformat(),
                },
            ],
            "session_crons": [],
            "instance_id": "test",
        }
        output = format_pending(pending)
        assert "1 pending alert" in output
        assert "PR #42 merged" in output
        assert "5 min ago" in output

    def test_with_crons(self):
        pending = {
            "alerts": [],
            "session_crons": [
                {
                    "id": "cron-abc123",
                    "cron": "*/30 * * * *",
                    "message": "Update notes",
                    "prompt": "do stuff",
                },
            ],
            "instance_id": "test",
        }
        output = format_pending(pending)
        assert "1 session cron" in output
        assert "*/30 * * * *" in output


# ── Phase 5C: Delivery receipts ──────────────────────────────────────────────


class TestDeliveryReceipts:
    def test_pending_stamps_delivery_receipt(self):
        """get_pending writes delivered_at and delivered_by on claimed alerts."""
        from aya.scheduler import _alerts_file

        alerts_file = _alerts_file()
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "r1",
                            "source_item_id": "s1",
                            "created_at": datetime.now(UTC).isoformat(),
                            "message": "Test alert",
                            "details": {},
                            "seen": False,
                        },
                    ]
                }
            )
        )

        get_pending("claude-9999")

        # Re-read alerts from disk
        alerts = load_alerts()
        receipt = next(a for a in alerts if a["id"] == "r1")
        assert receipt["delivered_by"] == "claude-9999"
        assert "delivered_at" in receipt

    def test_unclaimed_alerts_have_no_receipt(self):
        """Alerts not claimed by this session have no delivery receipt."""
        from aya.scheduler import _alerts_file

        alerts_file = _alerts_file()
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "r2",
                            "source_item_id": "s2",
                            "created_at": datetime.now(UTC).isoformat(),
                            "message": "Claimed by first",
                            "details": {},
                            "seen": False,
                        },
                    ]
                }
            )
        )

        get_pending("session-a")  # Claims r2
        get_pending("session-b")  # Gets nothing

        alerts = load_alerts()
        receipt = next(a for a in alerts if a["id"] == "r2")
        assert receipt["delivered_by"] == "session-a"


# ── Phase 5C: Alert expiry ───────────────────────────────────────────────────


class TestAlertExpiry:
    def test_expires_old_alerts(self):
        from aya.scheduler import _alerts_file, _get_local_tz

        now = datetime.now(_get_local_tz())
        alerts_file = _alerts_file()
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "old",
                            "source_item_id": "s1",
                            "created_at": (now - timedelta(days=10)).isoformat(),
                            "message": "Ancient alert",
                            "details": {},
                            "seen": True,
                        },
                        {
                            "id": "fresh",
                            "source_item_id": "s2",
                            "created_at": (now - timedelta(hours=1)).isoformat(),
                            "message": "Recent alert",
                            "details": {},
                            "seen": False,
                        },
                    ]
                }
            )
        )

        removed = expire_old_alerts(max_age_days=7)
        assert removed == 1

        remaining = load_alerts()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "fresh"

    def test_no_expiry_when_all_fresh(self):
        from aya.scheduler import _alerts_file, _get_local_tz

        now = datetime.now(_get_local_tz())
        alerts_file = _alerts_file()
        alerts_file.write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "a1",
                            "source_item_id": "s1",
                            "created_at": now.isoformat(),
                            "message": "New",
                            "details": {},
                            "seen": False,
                        },
                    ]
                }
            )
        )

        removed = expire_old_alerts()
        assert removed == 0
        assert len(load_alerts()) == 1

    def test_tick_runs_expiry(self):
        """run_tick includes alert expiry in its return value."""
        result = run_tick(quiet=True)
        assert "alerts_expired" in result

    def test_empty_alerts_no_error(self):
        removed = expire_old_alerts()
        assert removed == 0


# ── Phase 5C: Scheduler status ───────────────────────────────────────────────


class TestSchedulerStatus:
    def test_empty_status(self):
        status = get_scheduler_status()
        assert status["active_watches"] == []
        assert status["pending_reminders"] == []
        assert status["session_crons"] == []
        assert status["unseen_alerts"] == []
        assert status["recent_deliveries"] == []
        assert status["total_items"] == 0
        assert status["total_alerts"] == 0

    def test_status_with_data(self):
        from aya.scheduler import _alerts_file, _get_local_tz, _scheduler_file

        now = datetime.now(_get_local_tz())
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "w1",
                            "type": "watch",
                            "status": "active",
                            "provider": "github-pr",
                            "message": "PR watch",
                        },
                        {
                            "id": "r1",
                            "type": "reminder",
                            "status": "pending",
                            "due_at": now.isoformat(),
                            "message": "Do thing",
                        },
                        {
                            "id": "c1",
                            "type": "recurring",
                            "status": "active",
                            "session_required": True,
                            "cron": "*/30 * * * *",
                            "message": "Logger",
                        },
                    ]
                }
            )
        )
        _alerts_file().write_text(
            json.dumps(
                {
                    "alerts": [
                        {
                            "id": "a1",
                            "message": "Alert!",
                            "created_at": now.isoformat(),
                            "seen": False,
                        },
                        {
                            "id": "a2",
                            "message": "Delivered",
                            "created_at": now.isoformat(),
                            "seen": True,
                            "delivered_at": now.isoformat(),
                            "delivered_by": "claude-123",
                        },
                    ]
                }
            )
        )

        status = get_scheduler_status()
        assert len(status["active_watches"]) == 1
        assert len(status["pending_reminders"]) == 1
        assert len(status["session_crons"]) == 1
        assert len(status["unseen_alerts"]) == 1
        assert len(status["recent_deliveries"]) == 1
        assert status["total_items"] == 3
        assert status["total_alerts"] == 2

    def test_format_status_empty(self):
        status = get_scheduler_status()
        output = format_scheduler_status(status)
        assert "No active watches" in output
        assert "0 items" in output

    def test_format_status_with_watches(self):
        from aya.scheduler import _get_local_tz, _scheduler_file

        now = datetime.now(_get_local_tz())
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "w1",
                            "type": "watch",
                            "status": "active",
                            "provider": "github-pr",
                            "message": "PR #42 approval",
                            "poll_interval_minutes": 5,
                            "last_checked_at": now.isoformat(),
                        },
                    ]
                }
            )
        )

        status = get_scheduler_status()
        output = format_scheduler_status(status)
        assert "1 active watch" in output
        assert "[github-pr]" in output
        assert "PR #42 approval" in output


# ── Seed alerts ───────────────────────────────────────────────────────────────


class TestAddSeedAlert:
    def test_add_seed_alert_appends_unseen(self) -> None:
        """add_seed_alert() appends an alert with seen=False and a valid source_item_id."""
        alert = add_seed_alert(
            intent="Debug relay ingestion",
            opener="How is relay ingestion working on this machine?",
            context_summary="Work instance merged three aya PRs.",
            open_questions=[],
            from_label="did:key:z6Mkwork",
            packet_id="pkt-abc123",
        )

        assert alert["seen"] is False
        assert alert["source_item_id"] == "pkt-abc123"
        assert alert["details"]["type"] == "seed"
        assert "did:key:z6Mkwork" in alert["message"]

        persisted = load_alerts()
        assert len(persisted) == 1
        assert persisted[0]["id"] == alert["id"]

    def test_add_seed_alert_generates_source_item_id_when_packet_id_absent(self) -> None:
        """When no packet_id is supplied, source_item_id is a generated UUID (not empty)."""
        alert = add_seed_alert(
            intent="No packet ID",
            opener="Opener text",
            context_summary="",
            open_questions=[],
            from_label="did:key:z6Mkwork",
        )

        assert alert["source_item_id"]  # non-empty
        assert alert["source_item_id"] != ""
        assert alert["seen"] is False


class TestGetPendingSeedAlert:
    def test_pending_claims_seed_alert(self) -> None:
        """get_pending() returns and claims a seed alert."""
        add_seed_alert(
            intent="Pick up context",
            opener="What was the last thing we worked on?",
            context_summary="EOD wrap.",
            open_questions=[],
            from_label="did:key:z6Mkwork",
            packet_id="pkt-seed-1",
        )

        pending = get_pending("test-claude-99")

        assert len(pending["alerts"]) == 1
        assert pending["alerts"][0]["details"]["type"] == "seed"

        # Delivery metadata is stamped to the persisted file, not the returned dict
        persisted = load_alerts()
        assert persisted[0].get("delivered_by") == "test-claude-99"
        assert persisted[0].get("delivered_at") is not None

    def test_pending_does_not_double_deliver_seed_alert(self) -> None:
        """A second get_pending() call from a different session cannot claim the same alert."""
        add_seed_alert(
            intent="One-time seed",
            opener="Opener",
            context_summary="",
            open_questions=[],
            from_label="did:key:z6Mkwork",
            packet_id="pkt-seed-2",
        )

        first = get_pending("claude-session-A")
        second = get_pending("claude-session-B")

        assert len(first["alerts"]) == 1
        assert len(second["alerts"]) == 0


class TestTickWithMixedAlertTypes:
    def test_tick_with_mixed_alert_types(self) -> None:
        """run_tick() does not error when alerts.json contains seed, watch, and reminder alerts."""
        from aya.scheduler import _alerts_file

        mixed = {
            "alerts": [
                {
                    "id": "a-watch",
                    "source_item_id": "s1",
                    "created_at": datetime.now(UTC).isoformat(),
                    "message": "PR merged",
                    "details": {"type": "watch"},
                    "seen": True,
                },
                {
                    "id": "a-reminder",
                    "source_item_id": "s2",
                    "created_at": datetime.now(UTC).isoformat(),
                    "message": "Stand up",
                    "details": {"type": "reminder"},
                    "seen": True,
                },
                {
                    "id": "a-seed",
                    "source_item_id": "s3",
                    "created_at": datetime.now(UTC).isoformat(),
                    "message": "Seed from did:key:z6Mkwork: debug relay",
                    "details": {"type": "seed"},
                    "seen": False,
                },
            ]
        }
        _alerts_file().write_text(json.dumps(mixed))

        result = run_tick(quiet=True)

        assert isinstance(result, dict)
        assert "claims_swept" in result
        assert "alerts_expired" in result


# ── run_poll integration: new_comments end-to-end ────────────────────────────


class TestRunPollNewCommentsIntegration:
    """End-to-end: run_poll sees more comments → generates an alert."""

    def test_new_comments_generates_alert(self):
        """run_poll with new_comments condition creates an alert when comment count increases."""
        from unittest.mock import patch

        from aya.scheduler import _alerts_file, _get_local_tz, _scheduler_file, run_poll
        from aya.scheduler.providers import GithubPrState

        now = datetime.now(_get_local_tz())

        # Seed scheduler with a github-pr/new_comments watch that has a
        # last_state with comment_count=2 (baseline established on prior poll).
        last_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="My PR",
            reviews=[],
            has_approval=False,
            comment_count=2,
        )
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-comments-1",
                            "type": "watch",
                            "status": "active",
                            "message": "New comment on PR",
                            "provider": "github-pr",
                            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
                            "condition": "new_comments",
                            "poll_interval_minutes": 5,
                            "last_checked_at": None,
                            "last_state": last_state,
                            "remove_when": "",
                            "created_at": now.isoformat(),
                            "session_required": False,
                            "tags": [],
                        }
                    ]
                }
            )
        )
        _alerts_file().write_text(json.dumps({"alerts": []}))

        # Mock poll_watch to return new state with comment_count=3 (one new comment).
        new_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="My PR",
            reviews=[],
            has_approval=False,
            comment_count=3,
        )

        with patch("aya.scheduler.core.poll_watch", return_value=(new_state, True)):
            run_poll(quiet=True)

        # Assert an alert was written to alerts.json.
        alerts_data = json.loads(_alerts_file().read_text())
        alerts = alerts_data["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["source_item_id"] == "watch-comments-1"
        assert "New comment on PR" in alerts[0]["message"]

    def test_no_new_comments_no_alert(self):
        """run_poll with new_comments condition and no change does not create an alert."""
        from unittest.mock import patch

        from aya.scheduler import _alerts_file, _get_local_tz, _scheduler_file, run_poll
        from aya.scheduler.providers import GithubPrState

        now = datetime.now(_get_local_tz())
        last_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=2,
        )
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-comments-2",
                            "type": "watch",
                            "status": "active",
                            "message": "New comment on PR",
                            "provider": "github-pr",
                            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
                            "condition": "new_comments",
                            "poll_interval_minutes": 5,
                            "last_checked_at": None,
                            "last_state": last_state,
                            "remove_when": "",
                            "created_at": now.isoformat(),
                            "session_required": False,
                            "tags": [],
                        }
                    ]
                }
            )
        )
        _alerts_file().write_text(json.dumps({"alerts": []}))

        # No change — same count.
        with patch("aya.scheduler.core.poll_watch", return_value=(last_state, False)):
            run_poll(quiet=True)

        alerts_data = json.loads(_alerts_file().read_text())
        assert len(alerts_data["alerts"]) == 0


class TestFailingWatchVisibility:
    """A watch whose provider never returns state must not spin, and must not read as healthy."""

    @staticmethod
    def _seed_watch(now, **overrides):
        from aya.scheduler import _alerts_file, _scheduler_file

        item = {
            "id": "watch-failing-1",
            "type": "watch",
            "status": "active",
            "message": "CI checks on PR #1",
            "provider": "ci-checks",
            "watch_config": {"owner": "acme", "repo": "widget", "pr": 1},
            "condition": "checks_failed",
            "poll_interval_minutes": 5,
            "last_checked_at": None,
            "last_state": None,
            "remove_when": "checks_complete",
            "created_at": now.isoformat(),
            "session_required": False,
            "tags": [],
        }
        item.update(overrides)
        _scheduler_file().write_text(json.dumps({"items": [item]}))
        _alerts_file().write_text(json.dumps({"alerts": []}))

    @staticmethod
    def _read_watch():
        from aya.scheduler import _scheduler_file

        return json.loads(_scheduler_file().read_text())["items"][0]

    def test_failed_poll_stamps_attempt_and_counts_failure(self):
        from unittest.mock import patch

        from aya.scheduler import _get_local_tz, run_poll

        now = datetime.now(_get_local_tz())
        self._seed_watch(now)

        with patch("aya.scheduler.core.poll_watch", return_value=(None, False)):
            run_poll(quiet=True)

        item = self._read_watch()
        # Stamped, so the poll interval now applies to the failing watch.
        assert item["last_checked_at"] is not None
        assert item["consecutive_failures"] == 1
        assert item["status"] == "active"

    def test_failing_watch_respects_interval_instead_of_polling_every_tick(self):
        from unittest.mock import patch

        from aya.scheduler import _get_local_tz, run_poll

        now = datetime.now(_get_local_tz())
        self._seed_watch(now)

        with patch("aya.scheduler.core.poll_watch", return_value=(None, False)) as mock_poll:
            run_poll(quiet=True)
            run_poll(quiet=True)
            run_poll(quiet=True)

        # Three ticks inside one 5-minute interval must cost one poll, not three.
        assert mock_poll.call_count == 1
        assert self._read_watch()["consecutive_failures"] == 1

    def test_failures_accumulate_across_intervals(self):
        from unittest.mock import patch

        from aya.scheduler import _get_local_tz, run_poll

        now = datetime.now(_get_local_tz())
        # Seed as already-due by backdating the last attempt past the interval.
        stale = (now - timedelta(minutes=30)).isoformat()
        self._seed_watch(now, last_checked_at=stale, consecutive_failures=2)

        with patch("aya.scheduler.core.poll_watch", return_value=(None, False)):
            run_poll(quiet=True)

        assert self._read_watch()["consecutive_failures"] == 3

    def test_success_resets_the_failure_count(self):
        from unittest.mock import patch

        from aya.scheduler import _get_local_tz, run_poll
        from aya.scheduler.providers import CiChecksState

        now = datetime.now(_get_local_tz())
        stale = (now - timedelta(minutes=30)).isoformat()
        self._seed_watch(now, last_checked_at=stale, consecutive_failures=7)

        state = CiChecksState(all_complete=False, passed=["lint"], failed=[], pending=["test"])
        with patch("aya.scheduler.core.poll_watch", return_value=(state, False)):
            run_poll(quiet=True)

        item = self._read_watch()
        assert item["consecutive_failures"] == 0
        assert item["last_state"] == state

    def test_persistent_failure_warns_at_milestones_only(self, caplog):
        import logging
        from unittest.mock import patch

        from aya.scheduler import _get_local_tz, run_poll

        now = datetime.now(_get_local_tz())

        def poll_again(prior_failures):
            stale = (now - timedelta(minutes=30)).isoformat()
            self._seed_watch(now, last_checked_at=stale, consecutive_failures=prior_failures)
            with (
                caplog.at_level(logging.WARNING, logger="aya.scheduler.core"),
                patch("aya.scheduler.core.poll_watch", return_value=(None, False)),
            ):
                run_poll(quiet=True)

        # 1st and 3rd failures are milestones; the 2nd is not, so it stays at DEBUG.
        caplog.clear()
        poll_again(0)
        assert any("consecutive failure" in r.message for r in caplog.records)

        caplog.clear()
        poll_again(1)
        assert not [r for r in caplog.records if "consecutive failure" in r.message]

        caplog.clear()
        poll_again(2)
        assert any("consecutive failure" in r.message for r in caplog.records)

    def test_json_status_exposes_watch_health(self, monkeypatch):
        from aya.adapters.status_view import _render_json
        from aya.usecases.status import _gather_status

        failing = [
            {
                "id": "watch-failing-1",
                "message": "CI checks on PR #1",
                "provider": "ci-checks",
                "last_checked_at": "2026-03-29T14:00:00-07:00",
                "consecutive_failures": 12,
            }
        ]
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", lambda *a, **kw: failing)

        payload = json.loads(_render_json(_gather_status()))
        watch = payload["watches"][0]
        # A JSON/MCP consumer must be able to tell a broken watch from a healthy
        # one; emitting only id and message cannot express "failing every poll".
        assert watch["consecutive_failures"] == 12
        assert watch["provider"] == "ci-checks"
        assert watch["last_checked_at"] is not None
class TestRelayInboxWatch:
    """The relay inbox as a watch: validation, alert text, and the poll path."""

    def test_validation_defaults(self):
        from aya.scheduler.core import validate_watch

        # "default"/"-"/"" all mean the primary instance, matching `aya receive`.
        for target in ("default", "-", ""):
            config, condition, interval = validate_watch("relay-inbox", target, "")
            assert config == {}
            assert condition == "new_packets"
            assert interval == 2

        config, _, _ = validate_watch("relay-inbox", "guild-shawnoster", "")
        assert config == {"instance": "guild-shawnoster"}

    def test_validation_rejects_unknown_condition(self):
        from aya.scheduler.core import validate_watch

        with pytest.raises(ValueError, match="new_packets"):
            validate_watch("relay-inbox", "default", "merged")

    def test_alert_names_the_intents(self):
        from aya.scheduler import _format_watch_alert

        item = {"provider": "relay-inbox", "message": "relay inbox"}
        state = {
            "ingested_ids": ["01AAA", "01BBB"],
            "intents": ["re: theme diff", "dinner party count"],
            "held": 0,
        }
        msg = _format_watch_alert(item, state)
        # The alert text is what asyncRewake injects, so it has to carry enough
        # to decide whether to read the mail now.
        assert "2 new" in msg
        assert "re: theme diff" in msg
        assert "dinner party count" in msg

    def test_alert_notes_held_packets(self):
        from aya.scheduler import _format_watch_alert

        item = {"provider": "relay-inbox", "message": "relay inbox"}
        state = {"ingested_ids": ["01AAA"], "intents": ["mine"], "held": 2}
        assert "2 held" in _format_watch_alert(item, state)

    def test_poll_generates_an_alert_for_new_mail(self):
        from unittest.mock import patch

        from aya.scheduler import _alerts_file, _get_local_tz, _scheduler_file, run_poll

        now = datetime.now(_get_local_tz())
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-relay-1",
                            "type": "watch",
                            "status": "active",
                            "message": "relay inbox",
                            "provider": "relay-inbox",
                            "watch_config": {},
                            "condition": "new_packets",
                            "poll_interval_minutes": 2,
                            "last_checked_at": None,
                            "last_state": None,
                            "remove_when": "",
                            "created_at": now.isoformat(),
                            "session_required": False,
                            "tags": [],
                        }
                    ]
                }
            )
        )
        _alerts_file().write_text(json.dumps({"alerts": []}))

        state = {"ingested_ids": ["01AAA"], "intents": ["re: theme diff"], "held": 0}
        with patch("aya.scheduler.core.poll_watch", return_value=(state, True)):
            run_poll(quiet=True)

        alerts = json.loads(_alerts_file().read_text())["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["source_item_id"] == "watch-relay-1"
        assert "re: theme diff" in alerts[0]["message"]

    def test_poll_is_quiet_when_no_mail(self):
        from unittest.mock import patch

        from aya.scheduler import _alerts_file, _get_local_tz, _scheduler_file, run_poll

        now = datetime.now(_get_local_tz())
        _scheduler_file().write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "watch-relay-2",
                            "type": "watch",
                            "status": "active",
                            "message": "relay inbox",
                            "provider": "relay-inbox",
                            "watch_config": {},
                            "condition": "new_packets",
                            "poll_interval_minutes": 2,
                            "last_checked_at": None,
                            "last_state": None,
                            "remove_when": "",
                            "created_at": now.isoformat(),
                            "session_required": False,
                            "tags": [],
                        }
                    ]
                }
            )
        )
        _alerts_file().write_text(json.dumps({"alerts": []}))

        empty = {"ingested_ids": [], "intents": [], "held": 0}
        with patch("aya.scheduler.core.poll_watch", return_value=(empty, False)):
            run_poll(quiet=True)

        assert json.loads(_alerts_file().read_text())["alerts"] == []
