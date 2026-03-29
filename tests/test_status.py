"""Tests for the status module — readiness checks, greeting, perspective."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console

from aya.status import (
    _exists,
    _gather_status,
    _greeting,
    _perspective,
    _read_json,
    _render_json,
    _render_plain,
    _render_rich,
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
    def test_returns_string(self):
        result = _perspective()
        assert isinstance(result, str)
        assert len(result) > 10

    def test_deterministic_per_day(self):
        assert _perspective() == _perspective()


# ── main() rendering ─────────────────────────────────────────────────────────


class TestRenderRich:
    def test_renders_output(self, monkeypatch):
        """_render_rich must produce output — regression guard for the 'prints nothing' bug."""
        console = Console(record=True)
        monkeypatch.setattr("aya.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_active_watches", list)

        data = _gather_status()
        _render_rich(data, console)

        output = console.export_text()
        assert "Systems" in output

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
        monkeypatch.setattr("aya.status.PROFILE", profile_file)
        monkeypatch.setattr("aya.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_active_watches", list)

        console = Console(record=True)
        data = _gather_status()
        _render_rich(data, console)  # must not raise

        assert "Name re-eval due" in console.export_text()


class TestRenderPlain:
    def test_renders_compact(self, monkeypatch):
        monkeypatch.setattr("aya.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_active_watches", list)

        output = _render_plain(_gather_status())
        assert "Systems" in output
        assert "\n\n" not in output  # no blank lines


class TestRenderJson:
    def test_valid_json(self, monkeypatch):
        import json as json_mod

        monkeypatch.setattr("aya.status.get_unseen_alerts", list)
        monkeypatch.setattr("aya.status.get_due_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_upcoming_reminders", lambda *a, **kw: [])
        monkeypatch.setattr("aya.status.get_active_watches", list)

        raw = _render_json(_gather_status())
        parsed = json_mod.loads(raw)
        assert "systems" in parsed
        assert "greeting" in parsed
        assert parsed["systems"]["ok"] is True or parsed["systems"]["ok"] is False
