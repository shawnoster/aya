"""Tests for watch-chain handling in ``aya hook watch``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from aya.usecases.watch_chains import _hook_watch_impl


@pytest.fixture
def isolated_scheduler(tmp_path, monkeypatch):
    """Point scheduler files at a temp directory for each test."""
    scheduler_file = tmp_path / "assistant" / "memory" / "scheduler.json"
    alerts_file = tmp_path / "assistant" / "memory" / "alerts.json"
    registered_file = tmp_path / "assistant" / "memory" / "session_registered_crons.json"
    lock_file = tmp_path / "assistant" / "memory" / ".scheduler.lock"
    scheduler_file.parent.mkdir(parents=True)
    scheduler_file.write_text(json.dumps({"items": []}))
    alerts_file.write_text(json.dumps({"alerts": []}))

    monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", scheduler_file)
    monkeypatch.setattr("aya.adapters.paths.ALERTS_FILE", alerts_file)
    monkeypatch.setattr("aya.scheduler.REGISTERED_CRONS_FILE", registered_file)
    monkeypatch.setattr("aya.adapters.paths.LOCK_FILE", lock_file)

    return {"scheduler_file": scheduler_file, "alerts_file": alerts_file}


def _write_items(path, items):
    path.write_text(json.dumps({"schema_version": 1, "items": items}))


def _read_items(path):
    return json.loads(path.read_text())["items"]


def _read_alerts(path):
    return json.loads(path.read_text())["alerts"]


def _gh_state(*, merged: bool = False, comment_count: int = 0):
    return {
        "pr_state": "closed" if merged else "open",
        "merged": merged,
        "draft": False,
        "title": "My PR",
        "reviews": [],
        "has_approval": False,
        "comment_count": comment_count,
    }


class TestHookWatchChains:
    def test_auto_advances_watch_then_dispatch(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
        chain = {
            "id": "chain-1",
            "type": "watch",
            "status": "active",
            "created_at": now.isoformat(),
            "message": "ship-pr",
            "chain": "ship-pr",
            "tags": [],
            "session_required": False,
            "stages": [
                {
                    "name": "wait-for-review",
                    "watch": "github-pr owner/repo#42",
                    "condition": "new_comments",
                    "action": "notify",
                },
                {
                    "name": "address-feedback",
                    "action": "dispatch",
                    "dispatch": "/address-pr-feedback 42",
                    "autonomy": "autonomous",
                },
                {
                    "name": "wait-for-merge",
                    "watch": "github-pr owner/repo#42",
                    "condition": "merged",
                    "action": "notify",
                },
            ],
            "current_stage_index": 0,
            "current_stage_started_at": now.isoformat(),
            "heartbeat_interval_minutes": 120,
            "last_heartbeat_at": now.isoformat(),
        }
        _write_items(isolated_scheduler["scheduler_file"], [chain])

        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        monkeypatch.setattr(
            "aya.usecases.watch_chains.poll_watch",
            lambda item: (
                (_gh_state(comment_count=3), True)
                if item["condition"] == "new_comments"
                else (_gh_state(merged=False, comment_count=3), False)
            ),
        )

        rewake_messages: list[str] = []
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", rewake_messages.append)

        exit_code = _hook_watch_impl({})

        assert exit_code == 2
        item = _read_items(isolated_scheduler["scheduler_file"])[0]
        assert item["status"] == "active"
        assert item["current_stage_index"] == 2
        assert item["last_state"]["merged"] is False

        alerts = _read_alerts(isolated_scheduler["alerts_file"])
        assert len(alerts) == 2
        assert "wait-for-review" in alerts[0]["message"]
        assert "dispatching /address-pr-feedback 42" in alerts[1]["message"]
        assert rewake_messages
        assert "dispatching /address-pr-feedback 42" in rewake_messages[0]

    def test_confirm_stage_pauses_chain(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
        chain = {
            "id": "chain-2",
            "type": "watch",
            "status": "active",
            "created_at": now.isoformat(),
            "message": "ship-pr",
            "chain": "ship-pr",
            "tags": [],
            "session_required": False,
            "stages": [
                {
                    "name": "address-feedback",
                    "action": "dispatch",
                    "dispatch": "/address-pr-feedback 42",
                    "autonomy": "confirm",
                },
                {
                    "name": "wait-for-merge",
                    "watch": "github-pr owner/repo#42",
                    "condition": "merged",
                    "action": "notify",
                },
            ],
            "current_stage_index": 0,
            "current_stage_started_at": now.isoformat(),
            "heartbeat_interval_minutes": 120,
            "last_heartbeat_at": now.isoformat(),
        }
        _write_items(isolated_scheduler["scheduler_file"], [chain])

        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        rewake_messages: list[str] = []
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", rewake_messages.append)

        exit_code = _hook_watch_impl({})

        assert exit_code == 2
        item = _read_items(isolated_scheduler["scheduler_file"])[0]
        assert item["current_stage_index"] == 0
        assert item["awaiting_confirmation"] is True
        assert item["pending_dispatch"] == "/address-pr-feedback 42"

        alerts = _read_alerts(isolated_scheduler["alerts_file"])
        assert len(alerts) == 1
        assert "awaiting confirmation" in alerts[0]["message"]
        assert "awaiting confirmation" in rewake_messages[0]

    def test_emits_heartbeat_when_chain_is_idle(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 15, 0, tzinfo=UTC)
        chain = {
            "id": "chain-3",
            "type": "watch",
            "status": "active",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "message": "ship-pr",
            "chain": "ship-pr",
            "tags": [],
            "session_required": False,
            "stages": [
                {
                    "name": "wait-for-merge",
                    "watch": "github-pr owner/repo#42",
                    "condition": "merged",
                    "action": "notify",
                }
            ],
            "current_stage_index": 0,
            "current_stage_started_at": (now - timedelta(hours=3)).isoformat(),
            "last_checked_at": (now - timedelta(minutes=10)).isoformat(),
            "heartbeat_interval_minutes": 60,
            "last_heartbeat_at": (now - timedelta(hours=2)).isoformat(),
        }
        _write_items(isolated_scheduler["scheduler_file"], [chain])

        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        rewake_messages: list[str] = []
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", rewake_messages.append)

        exit_code = _hook_watch_impl({})

        assert exit_code == 2
        item = _read_items(isolated_scheduler["scheduler_file"])[0]
        assert item["last_heartbeat_at"] == now.isoformat()

        alerts = _read_alerts(isolated_scheduler["alerts_file"])
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "heartbeat"
        assert "heartbeat" in alerts[0]["message"]
        assert "heartbeat" in rewake_messages[0]


class TestChainPollFailures:
    """A chain stage whose poll fails must record the attempt, not retry every tick."""

    @staticmethod
    def _chain(now):
        return {
            "id": "chain-failing",
            "type": "watch",
            "status": "active",
            "created_at": now.isoformat(),
            "message": "ship-pr",
            "chain": "ship-pr",
            "tags": [],
            "session_required": False,
            "stages": [
                {
                    "name": "wait-for-checks",
                    "watch": "ci-checks owner/repo#42",
                    "condition": "checks_complete",
                    "action": "notify",
                }
            ],
            "current_stage_index": 0,
            "current_stage_started_at": now.isoformat(),
            "heartbeat_interval_minutes": 120,
            "last_heartbeat_at": now.isoformat(),
        }

    def test_failed_stage_poll_records_attempt(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
        _write_items(isolated_scheduler["scheduler_file"], [self._chain(now)])
        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        monkeypatch.setattr("aya.usecases.watch_chains.poll_watch", lambda item: (None, False))
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", lambda *a, **kw: None)

        _hook_watch_impl({})

        item = _read_items(isolated_scheduler["scheduler_file"])[0]
        # Without the stamp the interval gate never advances and the stage
        # re-polls on every tick for as long as the chain lives.
        assert item["last_checked_at"] is not None
        assert item["consecutive_failures"] == 1
        assert item["current_stage_index"] == 0

    def test_failing_stage_respects_interval(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
        _write_items(isolated_scheduler["scheduler_file"], [self._chain(now)])
        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", lambda *a, **kw: None)

        calls: list[int] = []

        def failing_poll(_item):
            calls.append(1)
            return None, False

        monkeypatch.setattr("aya.usecases.watch_chains.poll_watch", failing_poll)

        _hook_watch_impl({})
        _hook_watch_impl({})
        _hook_watch_impl({})

        # ci-checks polls at 1-minute intervals and the clock is frozen, so
        # three runs inside that minute must cost one poll.
        assert len(calls) == 1
        assert _read_items(isolated_scheduler["scheduler_file"])[0]["consecutive_failures"] == 1

    def test_recovery_resets_the_counter(self, isolated_scheduler, monkeypatch):
        now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
        chain = self._chain(now)
        chain["consecutive_failures"] = 4
        chain["last_checked_at"] = (now - timedelta(minutes=30)).isoformat()
        _write_items(isolated_scheduler["scheduler_file"], [chain])
        monkeypatch.setattr("aya.usecases.watch_chains._hook_watch_now", lambda: now)
        monkeypatch.setattr("aya.usecases.watch_chains.rewake_emit", lambda *a, **kw: None)
        monkeypatch.setattr(
            "aya.usecases.watch_chains.poll_watch",
            lambda item: (
                {"all_complete": True, "passed": ["lint"], "failed": [], "pending": []},
                True,
            ),
        )

        _hook_watch_impl({})

        assert _read_items(isolated_scheduler["scheduler_file"])[0]["consecutive_failures"] == 0
