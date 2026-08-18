"""Ship Mind status ritual — aya readiness check."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aya.adapters import clock
from aya.adapters import paths as _paths
from aya.adapters.config import load_config
from aya.adapters.credentials import check_credentials
from aya.adapters.install import aya_cron_installed
from aya.scheduler import (
    LOCAL_TZ,
    AlertItem,
    SchedulerItem,
    get_active_watches,
    get_due_reminders,
    get_unseen_alerts,
    get_upcoming_reminders,
    load_items,
)

logger = logging.getLogger(__name__)

# ── aya data paths (from ~/.aya) ────────────────────────────────────────────


# ── data ──────────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


# ── display limits ────────────────────────────────────────────────────────────

ALERT_DISPLAY_LIMIT = 4
DUE_DISPLAY_LIMIT = 4
UPCOMING_DISPLAY_LIMIT = 3
WATCH_DISPLAY_LIMIT = 4
ID_PREVIEW_LENGTH = 8

# ── helpers ───────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _exists(path: Path, name: str) -> CheckResult:
    return CheckResult(name=name, ok=path.exists(), detail=str(path))


# ── greeting ──────────────────────────────────────────────────────────────────


def _greeting(now: datetime, user: str, ship: str) -> str:
    hour = now.hour
    if hour < 6:
        salutation = f"Still running at this hour, {user}."
    elif hour < 12:
        salutation = f"Good morning, {user}."
    elif hour < 17:
        salutation = f"Good afternoon, {user}."
    elif hour < 21:
        salutation = f"Evening, {user}."
    else:
        salutation = f"Still at it, {user}."
    return f"{salutation} {ship} online."


def _time_flavor(now: datetime) -> str:
    hour = now.hour
    table = [
        (range(6, 9), "Coffee consumed? Let's make the day count."),
        (
            range(9, 12),
            "Morning focus window. Best cognition of the day — use it before the meetings eat it.",
        ),
        (range(12, 14), "Post-lunch territory. Carbs are the enemy of momentum. Push through."),
        (range(14, 17), "Afternoon. Attention debt accumulates here. One thing at a time."),
        (range(17, 19), "End-of-day push. Close the loop on something before you log off."),
        (range(19, 22), "Late session. Diminishing returns are real. Mind the clock."),
    ]
    for rng, flavor in table:
        if hour in rng:
            return flavor
    return "Unconventional hours. The ship is watching regardless."


# ── perspective ───────────────────────────────────────────────────────────────


def _perspective() -> str:
    lines = [
        "Break the impossible into next actions and proceed with unreasonable calm.",
        "Purpose is local, meaning is cumulative, and git history remembers everything.",
        "Most crises are just queued decisions wearing dramatic hats.",
        "Entropy hates momentum. Ship small, ship often.",
        "The answer is 42, but the method is: observe, decide, act, iterate.",
        "Hydrate. Stretch. The biological subsystems are not optional peripherals.",
    ]
    return lines[clock.now(UTC).toordinal() % len(lines)]


def _parse_next_eval(next_eval: Any, now_local: datetime) -> tuple[str, int] | None:
    """Parse next_eval ISO string and return (date_str, days_until) if due soon, else None."""
    if not isinstance(next_eval, str) or len(next_eval) < 10:
        return None
    try:
        eval_dt = datetime.fromisoformat(next_eval.replace("Z", "+00:00"))
        days_until = (eval_dt.date() - now_local.date()).days
        if days_until <= 1:
            return (next_eval[:10], days_until)
    except ValueError:
        pass
    return None


# ── main ──────────────────────────────────────────────────────────────────────


def _active_scheduler_items() -> list[SchedulerItem]:
    """Return all active scheduler items (watches, recurring, reminders)."""
    return [i for i in load_items() if i.get("status") == "active"]


def _check_crontab() -> CheckResult:
    """Report whether the out-of-session tick is still installed.

    Nothing else surfaces this. The scheduler's own status covers items, not the
    system crontab, so the tick can be absent — and out-of-session polling with
    it — while every other signal reads healthy.

    ``tick_interval`` in config.json is written only by a successful
    ``aya schedule install``, which makes it a durable record of intent: with it
    set, a missing entry is a regression and fails the check; without it, the
    tick was never asked for and its absence is reported as fact rather than
    treated as broken.
    """
    wanted = load_config().get("tick_interval")
    try:
        present = aya_cron_installed()
    except FileNotFoundError:
        # No crontab binary at all — common on WSL without cron. Not a fault in
        # aya, and not something `aya schedule install` can fix.
        return CheckResult(
            "crontab", True, "no crontab command available (out-of-session tick off)"
        )

    if present:
        return CheckResult("crontab", True, f"aya-scheduler-tick installed (tick={wanted or '?'})")
    if wanted:
        return CheckResult(
            "crontab",
            False,
            f"aya-scheduler-tick MISSING though tick_interval={wanted} was configured "
            f"— out-of-session polling is off; run `aya schedule install`",
        )
    return CheckResult("crontab", True, "not installed (out-of-session tick never configured)")


def _gather_status() -> dict[str, Any]:
    """Collect all status data into a plain dict."""
    now_local = clock.now(LOCAL_TZ)

    profile = _read_json(_paths.PROFILE_PATH)
    ship = profile.get("ship_mind_name", "GSV Unknown Vessel") if profile else "GSV Unknown Vessel"
    user = profile.get("user_name", "Shawn") if profile else "Shawn"
    next_eval = profile.get("name_next_reevaluation_at", "unknown") if profile else "unknown"

    unseen: list[AlertItem] = []
    due: list[SchedulerItem] = []
    upcoming: list[SchedulerItem] = []
    active_watches: list[SchedulerItem] = []
    scheduler_ok = True
    try:
        unseen = get_unseen_alerts()
        due = get_due_reminders(now_local)
        upcoming = get_upcoming_reminders(now_local, hours=12)
        active_watches = get_active_watches()
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError) as e:
        # Log scheduler fetch failures but don't crash — mark scheduler check failed
        logger.warning("Failed to load scheduler status: %s", e)
        scheduler_ok = False

    # One scheduler check, on whether the data loads — not on whether the file
    # exists. scheduler.json is written lazily by the first `schedule` command
    # (see scheduler.storage.save_items), and load_items() returns [] for a
    # missing file rather than raising. Failing the gate on its absence made
    # every fresh install report `systems.ok: false`, which skills/aya/SKILL.md
    # reads as "installation failed".
    scheduler_detail = (
        str(_paths.SCHEDULER_FILE)
        if _paths.SCHEDULER_FILE.exists()
        else f"{_paths.SCHEDULER_FILE} (not created yet — nothing scheduled)"
    )
    checks: list[CheckResult] = [
        CheckResult("profile", profile is not None, str(_paths.PROFILE_PATH)),
        CheckResult("scheduler", scheduler_ok, scheduler_detail),
        _check_crontab(),
    ]

    # Pre-compute check totals once, reuse in all render functions
    checks_ok = sum(1 for c in checks if c.ok)
    checks_total = len(checks)

    # Credential ACK — per-service env var presence for the common
    # service integrations (GitHub, Atlassian, Datadog, npm, …). No
    # network calls, no secret reads, just presence checks.
    credentials = check_credentials()

    return {
        "now_local": now_local,
        "ship": ship,
        "user": user,
        "next_eval": next_eval,
        "checks": checks,
        "checks_ok": checks_ok,
        "checks_total": checks_total,
        "credentials": credentials,
        "unseen": unseen,
        "due": due,
        "upcoming": upcoming,
        "active_watches": active_watches,
    }
