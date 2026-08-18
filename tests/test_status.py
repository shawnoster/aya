"""Tests for the status module — readiness checks, greeting, perspective."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from rich.console import Console

from aya.adapters.status_view import _render_json, _render_plain, _render_rich
from aya.usecases.status import (
    _exists,
    _gather_status,
    _greeting,
    _perspective,
    _read_json,
    _time_flavor,
)

# ── CheckResult / _exists ────────────────────────────────────────────────────


class TestCheckResult:
    def test_exists_true(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = _exists(f, "test file")
        assert result.ok is True
        assert result.name == "test file"

    def test_exists_false(self, tmp_path):
        result = _exists(tmp_path / "nope.txt", "missing")
        assert result.ok is False


# ── _read_json ───────────────────────────────────────────────────────────────


class TestReadJson:
    def test_valid_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        assert _read_json(f) == {"key": "value"}

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        assert _read_json(f) is None

    def test_missing_file(self, tmp_path):
        assert _read_json(tmp_path / "nope.json") is None

    def test_array_returns_none(self, tmp_path):
        f = tmp_path / "arr.json"
        f.write_text("[1, 2, 3]")
        assert _read_json(f) is None


# ── Greeting ─────────────────────────────────────────────────────────────────


class TestGreeting:
    def test_morning(self):
        now = datetime(2026, 3, 21, 8, 0, tzinfo=UTC)
        result = _greeting(now, "Shawn", "GSV Test Ship")
        assert "Good morning" in result
        assert "Shawn" in result
        assert "GSV Test Ship" in result

    def test_afternoon(self):
        now = datetime(2026, 3, 21, 14, 0, tzinfo=UTC)
        assert "Good afternoon" in _greeting(now, "Shawn", "Ship")

    def test_evening(self):
        now = datetime(2026, 3, 21, 19, 0, tzinfo=UTC)
        assert "Evening" in _greeting(now, "Shawn", "Ship")

    def test_late_night(self):
        now = datetime(2026, 3, 21, 23, 0, tzinfo=UTC)
        assert "Still at it" in _greeting(now, "Shawn", "Ship")

    def test_very_early(self):
        now = datetime(2026, 3, 21, 3, 0, tzinfo=UTC)
        assert "Still running" in _greeting(now, "Shawn", "Ship")


# ── Time flavor ──────────────────────────────────────────────────────────────


class TestTimeFlavor:
    def test_morning_coffee(self):
        now = datetime(2026, 3, 21, 7, 0, tzinfo=UTC)
        assert "Coffee" in _time_flavor(now)

    def test_focus_window(self):
        now = datetime(2026, 3, 21, 10, 0, tzinfo=UTC)
        assert "focus" in _time_flavor(now).lower()

    def test_afternoon(self):
        now = datetime(2026, 3, 21, 15, 0, tzinfo=UTC)
        assert "Afternoon" in _time_flavor(now)

    def test_unconventional(self):
        now = datetime(2026, 3, 21, 3, 0, tzinfo=UTC)
        assert "Unconventional" in _time_flavor(now)


# ── Perspective ──────────────────────────────────────────────────────────────


class TestPerspective:
    def test_deterministic_per_day(self):
        assert _perspective() == _perspective()


# ── main() rendering ─────────────────────────────────────────────────────────


class TestRenderRich:
    def test_renders_output(self, monkeypatch):
        """_render_rich must produce output — regression guard for the 'prints nothing' bug."""
        console = Console(record=True)
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        data = _gather_status()
        _render_rich(data, console)

        output = console.export_text()
        assert "Systems" in output

    def test_fresh_install_with_nothing_scheduled_is_ok(self, monkeypatch, tmp_path):
        """A missing scheduler.json must not read as a failed install.

        scheduler.json is written lazily by the first `aya schedule` command, and
        load_items() returns [] when it is absent. Failing the gate on its
        absence made every fresh box report `systems.ok: false`, which
        skills/aya/SKILL.md turns into "the installation failed".
        """
        profile_file = tmp_path / "profile.json"
        profile_file.write_text(json.dumps({"ship_mind_name": "GSV Test", "user_name": "Test"}))
        monkeypatch.setattr("aya.adapters.paths.PROFILE_PATH", profile_file)
        monkeypatch.setattr("aya.adapters.paths.SCHEDULER_FILE", tmp_path / "scheduler.json")
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        data = _gather_status()

        assert not (tmp_path / "scheduler.json").exists()
        assert data["checks_ok"] == data["checks_total"], [
            (c.name, c.ok, c.detail) for c in data["checks"]
        ]
        assert json.loads(_render_json(data))["systems"]["ok"] is True
        # The absence is still reported, just not as a failure.
        scheduler = next(c for c in data["checks"] if c.name == "scheduler")
        assert "not created yet" in scheduler.detail

    def test_name_reeval_z_suffix(self, monkeypatch, tmp_path):
        """name_next_reevaluation_at stored with 'Z' suffix must parse without error."""
        import json

        profile_file = tmp_path / "profile.json"
        profile_file.write_text(
            json.dumps(
                {
                    "ship_mind_name": "GSV Test",
                    "user_name": "Test",
                    "name_next_reevaluation_at": "2026-03-22T00:00:00Z",
                }
            )
        )
        monkeypatch.setattr("aya.adapters.paths.PROFILE_PATH", profile_file)
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        console = Console(record=True)
        data = _gather_status()
        _render_rich(data, console)  # must not raise

        assert "Name re-eval due" in console.export_text()


def _sample_alerts():
    return [
        {
            "id": "alert-1",
            "source_item_id": "watch-abcd1234",
            "created_at": "2026-03-29T10:00:00-07:00",
            "message": "PR 85 merged",
            "seen": False,
        }
    ]


def _sample_due(now, **kw):
    return [
        {
            "id": "rem-due-1234",
            "due_at": now.isoformat(),
            "message": "Review PR feedback",
        }
    ]


def _sample_upcoming(now, **kw):
    return [
        {
            "due_at": (now + timedelta(hours=2)).isoformat(),
            "message": "Team standup",
        }
    ]


def _sample_watches():
    return [
        {
            "id": "watch-5678abcd",
            "message": "PR 90 approved",
            "last_checked_at": "2026-03-29T14:00:00-07:00",
        }
    ]


class TestRenderPlain:
    def test_renders_compact(self, monkeypatch):
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        output = _render_plain(_gather_status())
        assert "Systems" in output
        assert "\n\n" not in output  # no blank lines

    def test_renders_populated_data(self, monkeypatch):
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", _sample_alerts)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", _sample_due)
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", _sample_upcoming)
        monkeypatch.setattr("aya.usecases.status.get_active_watches", _sample_watches)

        output = _render_plain(_gather_status())
        assert "alert:" in output
        assert "PR 85 merged" in output
        assert "due:" in output
        assert "Review PR feedback" in output
        assert "upcoming:" in output
        assert "Team standup" in output
        assert "watch:" in output
        assert "PR 90 approved" in output

    def test_renders_next_eval_when_due(self, monkeypatch, tmp_path):
        profile_path = tmp_path / "profile.json"
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
        profile_path.write_text(
            json.dumps(
                {
                    "ship_mind_name": "GSV Test",
                    "user_name": "Test",
                    "name_next_reevaluation_at": yesterday,
                }
            )
        )
        monkeypatch.setattr("aya.adapters.paths.PROFILE_PATH", profile_path)
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        output = _render_plain(_gather_status())
        assert "Name re-eval due" in output


class TestRenderJson:
    def test_valid_json(self, monkeypatch):
        import json as json_mod

        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        raw = _render_json(_gather_status())
        parsed = json_mod.loads(raw)
        assert "systems" in parsed
        assert "greeting" in parsed
        assert "next_eval" in parsed
        assert parsed["systems"]["ok"] is True or parsed["systems"]["ok"] is False

    def test_json_with_populated_data(self, monkeypatch):
        import json as json_mod

        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", _sample_alerts)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", _sample_due)
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", _sample_upcoming)
        monkeypatch.setattr("aya.usecases.status.get_active_watches", _sample_watches)

        raw = _render_json(_gather_status())
        parsed = json_mod.loads(raw)
        assert len(parsed["alerts"]) == 1
        assert parsed["alerts"][0]["message"] == "PR 85 merged"
        assert "source_item_id" in parsed["alerts"][0]
        assert len(parsed["due"]) == 1
        assert len(parsed["upcoming"]) == 1
        assert len(parsed["watches"]) == 1


# ── crontab check ────────────────────────────────────────────────────────────


class TestCrontabCheck:
    """The out-of-session tick has no other health signal."""

    @staticmethod
    def _patch(monkeypatch, *, crontab: str | None, tick_interval: str | None):
        from aya.usecases import status as status_mod

        def fake_installed():
            if crontab is None:
                raise FileNotFoundError("crontab")
            return "aya-scheduler-tick" in crontab

        # Patch where status.py *binds* these rather than where they are
        # defined: a from-import holds its own reference, so patching the source
        # module would not intercept the call.
        monkeypatch.setattr("aya.usecases.status.aya_cron_installed", fake_installed)
        monkeypatch.setattr(
            "aya.usecases.status.load_config",
            lambda *a, **kw: {"tick_interval": tick_interval} if tick_interval else {},
        )
        return status_mod

    AYA_LINE = "* * * * * /home/shawn/.local/bin/aya schedule tick --quiet  # aya-scheduler-tick"

    def test_present_and_configured_is_ok(self, monkeypatch):
        m = self._patch(monkeypatch, crontab=self.AYA_LINE, tick_interval="1m")
        r = m._check_crontab()
        assert r.ok
        assert "installed" in r.detail

    def test_missing_but_configured_fails(self, monkeypatch):
        # The regression this check exists to catch: the tick was installed at
        # some point (tick_interval persisted) and the entry is now gone, so
        # out-of-session polling is silently off.
        m = self._patch(monkeypatch, crontab="# nothing here\n", tick_interval="1m")
        r = m._check_crontab()
        assert not r.ok
        assert "MISSING" in r.detail
        assert "aya schedule install" in r.detail

    def test_missing_and_never_configured_is_not_a_failure(self, monkeypatch):
        # Never asked for. Reported as fact, not treated as broken — otherwise
        # every install that skips the cron reports systems.ok false.
        m = self._patch(monkeypatch, crontab="", tick_interval=None)
        r = m._check_crontab()
        assert r.ok
        assert "never configured" in r.detail

    def test_no_crontab_command_is_not_a_failure(self, monkeypatch):
        # WSL without cron installed. Not aya's fault and not installable.
        m = self._patch(monkeypatch, crontab=None, tick_interval="1m")
        r = m._check_crontab()
        assert r.ok
        assert "no crontab command" in r.detail

    def test_appears_in_the_systems_payload(self, monkeypatch):
        import json as _json

        from aya.adapters.status_view import _render_json
        from aya.usecases.status import _gather_status

        self._patch(monkeypatch, crontab="", tick_interval="1m")
        monkeypatch.setattr("aya.usecases.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.usecases.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.usecases.status.get_active_watches", list)

        payload = _json.loads(_render_json(_gather_status()))
        names = {c["name"] for c in payload["systems"]["checks"]}
        assert "crontab" in names
        # A JSON/MCP consumer must be able to see the degradation, which is the
        # surface where this went unnoticed.
        assert payload["systems"]["ok"] is False
