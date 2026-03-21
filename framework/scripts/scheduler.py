#!/usr/bin/env python3
"""Unified scheduler — reminders, watches, recurring items, and events.

Replaces reminders.py. Persists across AI sessions via scheduler.json.
Out-of-session polling via watcher_daemon.py + systemd timer.

Usage:
    scheduler.py remind  --due "tomorrow 9am" -m "Check the PR"
    scheduler.py watch   github-pr owner/repo#123 -m "PR approved"
    scheduler.py watch   jira-query "project=CSD AND created>=-1d" -m "New CSD tickets"
    scheduler.py watch   jira-ticket CSD-225 -m "Ticket status changed"
    scheduler.py list    [--all] [--type TYPE]
    scheduler.py check   [--json]
    scheduler.py dismiss <id>
    scheduler.py snooze  <id> --until "in 1 hour"
    scheduler.py poll    [--quiet]
    scheduler.py alerts  [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_FILE = ROOT / "assistant" / "memory" / "scheduler.json"
ALERTS_FILE = ROOT / "assistant" / "memory" / "alerts.json"
CONFIG_FILE = ROOT / "assistant" / "config.json"

LOCAL_TZ = ZoneInfo("America/Denver")


# ── time parsing ─────────────────────────────────────────────────────────────

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

_RELATIVE_RE = re.compile(
    r"^in\s+(\d+)\s+(minute|min|hour|hr|day|week)s?$", re.IGNORECASE,
)

_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


def _next_weekday(now: datetime, target_day: int) -> datetime:
    days_ahead = target_day - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return now + timedelta(days=days_ahead)


def _apply_time(dt: datetime, hour: int, minute: int) -> datetime:
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _parse_time_component(text: str) -> tuple[int, int]:
    m = _TIME_RE.search(text)
    if not m:
        return 9, 0
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def parse_due(text: str, now: datetime | None = None) -> datetime:
    """Parse human-readable due time into timezone-aware datetime.

    Supports: ISO 8601, relative (in N units), tomorrow/today + time,
    weekday + time, eod/end of day.
    """
    if now is None:
        now = datetime.now(LOCAL_TZ)
    text = text.strip().lower()

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=LOCAL_TZ) if dt.tzinfo is None else dt
        except ValueError:
            continue

    m = _RELATIVE_RE.match(text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        delta = {"minute": timedelta(minutes=amount), "min": timedelta(minutes=amount),
                 "hour": timedelta(hours=amount), "hr": timedelta(hours=amount),
                 "day": timedelta(days=amount), "week": timedelta(weeks=amount)}
        return now + delta.get(unit, timedelta())

    if text in ("eod", "end of day"):
        return _apply_time(now, 17, 0)

    if text.startswith("tomorrow"):
        h, mn = _parse_time_component(text)
        return _apply_time(now + timedelta(days=1), h, mn)

    if text.startswith("today") or _TIME_RE.match(text):
        h, mn = _parse_time_component(text)
        candidate = _apply_time(now, h, mn)
        return candidate + timedelta(days=1) if candidate <= now else candidate

    cleaned = text.replace("next ", "")
    for day_name, day_num in _WEEKDAYS.items():
        if cleaned.startswith(day_name):
            h, mn = _parse_time_component(cleaned)
            return _apply_time(_next_weekday(now, day_num), h, mn)

    raise ValueError(f"Cannot parse due time: {text!r}")


# ── storage ──────────────────────────────────────────────────────────────────

def load_items() -> list[dict[str, Any]]:
    if not SCHEDULER_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULER_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def save_items(items: list[dict[str, Any]]) -> None:
    SCHEDULER_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULER_FILE.write_text(json.dumps({"items": items}, indent=2, default=str) + "\n")


def load_alerts() -> list[dict[str, Any]]:
    if not ALERTS_FILE.exists():
        return []
    try:
        data = json.loads(ALERTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("alerts", []) if isinstance(data, dict) else []


def save_alerts(alerts: list[dict[str, Any]]) -> None:
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_FILE.write_text(json.dumps({"alerts": alerts}, indent=2, default=str) + "\n")


def _find(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if item["id"] == item_id or item["id"].startswith(item_id):
            return item
    return None


def _new_id() -> str:
    return str(uuid.uuid4())


# ── watch providers ──────────────────────────────────────────────────────────

def _run_gh(args: list[str], timeout: int = 15) -> dict[str, Any] | list | None:
    """Run gh CLI and parse JSON output."""
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def _check_github_pr(config: dict[str, Any]) -> dict[str, Any] | None:
    """Check GitHub PR status and reviews."""
    owner = config["owner"]
    repo = config["repo"]
    pr = config["pr"]

    pr_data = _run_gh([
        "api", f"/repos/{owner}/{repo}/pulls/{pr}",
        "--jq", "{ state: .state, merged: .merged, draft: .draft, title: .title }",
    ])
    if not pr_data:
        return None

    reviews = _run_gh([
        "api", f"/repos/{owner}/{repo}/pulls/{pr}/reviews",
        "--jq", "[.[] | { user: .user.login, state: .state }]",
    ])

    return {
        "pr_state": pr_data.get("state"),
        "merged": pr_data.get("merged", False),
        "draft": pr_data.get("draft", False),
        "title": pr_data.get("title", ""),
        "reviews": reviews or [],
        "has_approval": any(r.get("state") == "APPROVED" for r in (reviews or [])),
    }


def _check_jira_query(config: dict[str, Any]) -> dict[str, Any] | None:
    """Run a JQL query and return results."""
    jql = config["jql"]
    email = os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("ATLASSIAN_API_TOKEN", "")
    server = os.environ.get("ATLASSIAN_SERVER_URL", "").rstrip("/")

    if not all([email, token, server]):
        return None

    try:
        import httpx
        resp = httpx.post(
            f"{server}/rest/api/3/search",
            auth=(email, token),
            json={"jql": jql, "maxResults": 20, "fields": ["key", "summary", "status"]},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "total": data.get("total", 0),
            "issues": [
                {
                    "key": i["key"],
                    "summary": i["fields"]["summary"],
                    "status": i["fields"]["status"]["name"],
                }
                for i in data.get("issues", [])
            ],
        }
    except Exception:
        return None


def _check_jira_ticket(config: dict[str, Any]) -> dict[str, Any] | None:
    """Check a specific Jira ticket's status."""
    ticket = config["ticket"]
    email = os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("ATLASSIAN_API_TOKEN", "")
    server = os.environ.get("ATLASSIAN_SERVER_URL", "").rstrip("/")

    if not all([email, token, server]):
        return None

    try:
        import httpx
        resp = httpx.get(
            f"{server}/rest/api/3/issue/{ticket}",
            auth=(email, token),
            params={"fields": "summary,status,assignee,priority"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        fields = data.get("fields", {})
        return {
            "key": data["key"],
            "summary": fields.get("summary", ""),
            "status": fields.get("status", {}).get("name", ""),
            "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
        }
    except Exception:
        return None


WATCH_PROVIDERS = {
    "github-pr": _check_github_pr,
    "jira-query": _check_jira_query,
    "jira-ticket": _check_jira_ticket,
}


def poll_watch(item: dict[str, Any]) -> tuple[dict | None, bool]:
    """Poll a watch item. Returns (new_state, changed)."""
    provider = item.get("provider", "")
    check_fn = WATCH_PROVIDERS.get(provider)
    if not check_fn:
        return None, False

    new_state = check_fn(item.get("watch_config", {}))
    if new_state is None:
        return None, False

    last_state = item.get("last_state")
    changed = False
    condition = item.get("condition", "")

    if provider == "github-pr":
        if condition == "approved_or_merged":
            was_approved = (last_state or {}).get("has_approval", False)
            was_merged = (last_state or {}).get("merged", False)
            changed = (new_state["has_approval"] and not was_approved) or \
                      (new_state["merged"] and not was_merged)
        elif condition == "merged":
            changed = new_state["merged"] and not (last_state or {}).get("merged", False)
        else:
            changed = json.dumps(new_state, sort_keys=True) != json.dumps(last_state, sort_keys=True)

    elif provider == "jira-query":
        if condition == "new_results":
            old_keys = {i["key"] for i in (last_state or {}).get("issues", [])}
            new_keys = {i["key"] for i in new_state.get("issues", [])}
            changed = bool(new_keys - old_keys)
        else:
            changed = new_state.get("total", 0) != (last_state or {}).get("total", 0)

    elif provider == "jira-ticket":
        if condition == "status_changed":
            changed = new_state.get("status") != (last_state or {}).get("status")
        else:
            changed = json.dumps(new_state, sort_keys=True) != json.dumps(last_state, sort_keys=True)

    return new_state, changed


def _evaluate_auto_remove(item: dict[str, Any], state: dict[str, Any]) -> bool:
    """Check if a watch should be auto-removed based on remove_when condition."""
    remove_when = item.get("remove_when", "")
    if not remove_when:
        return False
    if remove_when == "merged_or_closed" and item.get("provider") == "github-pr":
        return state.get("merged", False) or state.get("pr_state") == "closed"
    return False


# ── CLI commands ─────────────────────────────────────────────────────────────

def cmd_remind(args: argparse.Namespace) -> None:
    now = datetime.now(LOCAL_TZ)
    due = parse_due(args.due, now)
    item = {
        "id": _new_id(),
        "type": "reminder",
        "status": "pending",
        "created_at": now.isoformat(),
        "message": args.message,
        "tags": [t.strip() for t in args.tag.split(",")] if args.tag else [],
        "session_required": False,
        "due_at": due.isoformat(),
        "delivered_at": None,
        "snoozed_until": None,
    }
    items = load_items()
    items.append(item)
    save_items(items)
    print(f"  ✓ Reminder {item['id'][:8]} — {due.strftime('%a %b %d, %I:%M %p')}")
    print(f"    {args.message}")


def cmd_watch(args: argparse.Namespace) -> None:
    now = datetime.now(LOCAL_TZ)
    provider = args.provider
    target = args.target

    watch_config: dict[str, Any] = {}
    condition = ""

    if provider == "github-pr":
        m = re.match(r"([^/]+)/([^#]+)#(\d+)", target)
        if not m:
            print("Format: owner/repo#123", file=sys.stderr)
            sys.exit(1)
        watch_config = {"owner": m.group(1), "repo": m.group(2), "pr": int(m.group(3))}
        condition = args.condition or "approved_or_merged"

    elif provider == "jira-query":
        watch_config = {"jql": target}
        condition = args.condition or "new_results"

    elif provider == "jira-ticket":
        watch_config = {"ticket": target.upper()}
        condition = args.condition or "status_changed"

    else:
        print(f"Unknown provider: {provider}", file=sys.stderr)
        sys.exit(1)

    item = {
        "id": _new_id(),
        "type": "watch",
        "status": "active",
        "created_at": now.isoformat(),
        "message": args.message,
        "tags": [t.strip() for t in args.tag.split(",")] if args.tag else [],
        "session_required": False,
        "provider": provider,
        "watch_config": watch_config,
        "condition": condition,
        "poll_interval_minutes": args.interval or 30,
        "last_checked_at": None,
        "last_state": None,
        "remove_when": args.remove_when or "",
    }

    items = load_items()
    items.append(item)
    save_items(items)
    print(f"  ✓ Watch {item['id'][:8]} ({provider})")
    print(f"    {args.message}")
    print(f"    Condition: {condition}, poll every {item['poll_interval_minutes']}m")


def cmd_list(args: argparse.Namespace) -> None:
    items = load_items()
    if args.type:
        items = [i for i in items if i["type"] == args.type]
    if not args.all:
        items = [i for i in items if i["status"] in ("pending", "active", "snoozed")]

    if not items:
        print("No active items.")
        return

    now = datetime.now(LOCAL_TZ)
    type_icons = {"reminder": "⏰", "watch": "👁", "recurring": "🔄", "event": "⚡"}

    for item_type in ("reminder", "watch", "recurring", "event"):
        typed = [i for i in items if i["type"] == item_type]
        if not typed:
            continue
        print(f"\n  {type_icons.get(item_type, '•')} {item_type.upper()}S")
        for i in typed:
            status_icon = {"pending": "⏳", "active": "✅", "snoozed": "💤",
                           "delivered": "📬", "dismissed": "✗"}.get(i["status"], "•")
            tags = f" [{', '.join(i['tags'])}]" if i.get("tags") else ""

            if i["type"] == "reminder":
                due = datetime.fromisoformat(i["due_at"])
                due_str = due.strftime("%a %b %d, %I:%M %p")
                overdue = due <= now and i["status"] == "pending"
                marker = " 🔴 OVERDUE" if overdue else ""
                print(f"    {status_icon} {i['id'][:8]}  {due_str}  {i['message'][:45]}{tags}{marker}")
            elif i["type"] == "watch":
                provider = i.get("provider", "?")
                interval = i.get("poll_interval_minutes", "?")
                last = i.get("last_checked_at")
                last_str = datetime.fromisoformat(last).strftime("%H:%M") if last else "never"
                print(f"    {status_icon} {i['id'][:8]}  [{provider}] {i['message'][:40]}{tags}  (every {interval}m, last: {last_str})")
            elif i["type"] == "recurring":
                cron = i.get("cron", "?")
                sess = " [session]" if i.get("session_required") else ""
                print(f"    {status_icon} {i['id'][:8]}  {i['message'][:45]}{tags}  ({cron}){sess}")
            elif i["type"] == "event":
                trigger = i.get("trigger", "?")
                print(f"    {status_icon} {i['id'][:8]}  {i['message'][:45]}{tags}  on:{trigger}")
    print()


def cmd_check(args: argparse.Namespace) -> None:
    """Check for due reminders and unread alerts."""
    items = load_items()
    now = datetime.now(LOCAL_TZ)
    modified = False
    due_items = []

    for item in items:
        if item["type"] != "reminder" or item["status"] not in ("pending", "snoozed"):
            continue
        if item["status"] == "snoozed" and item.get("snoozed_until"):
            snooze_end = datetime.fromisoformat(item["snoozed_until"])
            if snooze_end > now:
                continue
            item["status"] = "pending"
            item["snoozed_until"] = None
            modified = True
        due = datetime.fromisoformat(item["due_at"])
        if due <= now:
            due_items.append(item)

    if modified:
        save_items(items)

    alerts = load_alerts()
    unseen = [a for a in alerts if not a.get("seen")]

    if args.json:
        json.dump({"due_reminders": due_items, "alerts": unseen}, sys.stdout, indent=2, default=str)
        print()
        return

    if not due_items and not unseen:
        print("Nothing due. No alerts.")
        return

    if due_items:
        print(f"\n  ⏰ {len(due_items)} reminder(s) due:")
        for r in due_items:
            due = datetime.fromisoformat(r["due_at"])
            print(f"    🔴 {r['id'][:8]}  {due.strftime('%I:%M %p')}  {r['message'][:55]}")

    if unseen:
        print(f"\n  🔔 {len(unseen)} alert(s) from background watcher:")
        for a in unseen:
            print(f"    📢 {a['source_item_id'][:8]}  {a['message'][:60]}")


def cmd_dismiss(args: argparse.Namespace) -> None:
    items = load_items()
    item = _find(items, args.id)
    if not item:
        print(f"Item {args.id} not found.", file=sys.stderr)
        sys.exit(1)
    item["status"] = "dismissed"
    if item["type"] == "reminder":
        item["delivered_at"] = datetime.now(LOCAL_TZ).isoformat()
    save_items(items)
    print(f"  ✓ Dismissed {item['id'][:8]} — {item['message'][:60]}")


def cmd_snooze(args: argparse.Namespace) -> None:
    items = load_items()
    item = _find(items, args.id)
    if not item:
        print(f"Item {args.id} not found.", file=sys.stderr)
        sys.exit(1)
    now = datetime.now(LOCAL_TZ)
    snooze_until = parse_due(args.until, now)
    item["status"] = "snoozed"
    item["snoozed_until"] = snooze_until.isoformat()
    save_items(items)
    print(f"  💤 Snoozed {item['id'][:8]} until {snooze_until.strftime('%a %b %d, %I:%M %p')}")


def cmd_poll(args: argparse.Namespace) -> None:
    """Run one poll cycle — check all watches and due reminders. For daemon use."""
    items = load_items()
    alerts = load_alerts()
    now = datetime.now(LOCAL_TZ)
    items_modified = False
    alerts_modified = False

    for item in items:
        if item["type"] == "watch" and item["status"] == "active" and not item.get("session_required"):
            last = item.get("last_checked_at")
            interval = item.get("poll_interval_minutes", 30)
            if last:
                next_check = datetime.fromisoformat(last) + timedelta(minutes=interval)
                if now < next_check:
                    continue

            new_state, changed = poll_watch(item)
            if new_state is not None:
                item["last_checked_at"] = now.isoformat()
                item["last_state"] = new_state
                items_modified = True

                if changed:
                    alert = {
                        "id": _new_id(),
                        "source_item_id": item["id"],
                        "created_at": now.isoformat(),
                        "message": _format_watch_alert(item, new_state),
                        "details": new_state,
                        "seen": False,
                    }
                    alerts.append(alert)
                    alerts_modified = True
                    if not args.quiet:
                        print(f"  🔔 {item['id'][:8]} — {alert['message'][:60]}")

                if _evaluate_auto_remove(item, new_state):
                    item["status"] = "dismissed"
                    items_modified = True
                    if not args.quiet:
                        print(f"  ✓ Auto-dismissed {item['id'][:8]} (condition met)")

            elif not args.quiet:
                print(f"  ⚠ {item['id'][:8]} — poll failed (network/auth?)")

        elif item["type"] == "reminder" and item["status"] == "pending":
            due = datetime.fromisoformat(item["due_at"])
            if due <= now:
                existing_sources = {a["source_item_id"] for a in alerts if not a.get("seen")}
                if item["id"] not in existing_sources:
                    alert = {
                        "id": _new_id(),
                        "source_item_id": item["id"],
                        "created_at": now.isoformat(),
                        "message": f"Reminder due: {item['message']}",
                        "details": {"due_at": item["due_at"]},
                        "seen": False,
                    }
                    alerts.append(alert)
                    alerts_modified = True
                    if not args.quiet:
                        print(f"  ⏰ {item['id'][:8]} — {item['message'][:55]}")

    if items_modified:
        save_items(items)
    if alerts_modified:
        save_alerts(alerts)

    if not args.quiet:
        watch_count = sum(1 for i in items if i["type"] == "watch" and i["status"] == "active")
        reminder_count = sum(1 for i in items if i["type"] == "reminder" and i["status"] == "pending")
        print(f"\n  Poll complete. {watch_count} watches, {reminder_count} pending reminders.")


def cmd_recurring(args: argparse.Namespace) -> None:
    now = datetime.now(LOCAL_TZ)
    item = {
        "id": _new_id(),
        "type": "recurring",
        "status": "active",
        "created_at": now.isoformat(),
        "message": args.message,
        "tags": [t.strip() for t in args.tag.split(",")] if args.tag else [],
        "session_required": True,
        "cron": args.cron,
        "prompt": args.prompt or "",
    }
    items = load_items()
    items.append(item)
    save_items(items)
    print(f"  ✓ Recurring {item['id'][:8]} — {args.cron}")
    print(f"    {args.message}")


def cmd_alerts(args: argparse.Namespace) -> None:
    """Show and optionally clear alerts from daemon."""
    alerts = load_alerts()
    unseen = [a for a in alerts if not a.get("seen")]

    if args.json:
        json.dump(unseen, sys.stdout, indent=2, default=str)
        print()
        return

    if not unseen:
        print("No unseen alerts.")
        return

    print(f"\n  🔔 {len(unseen)} alert(s):")
    for a in unseen:
        ts = datetime.fromisoformat(a["created_at"]).strftime("%b %d %I:%M %p")
        print(f"    📢 {a['source_item_id'][:8]}  {ts}  {a['message'][:55]}")

    if args.mark_seen:
        for a in alerts:
            a["seen"] = True
        save_alerts(alerts)
        print(f"\n  Marked {len(unseen)} alert(s) as seen.")
    print()


def _format_watch_alert(item: dict[str, Any], state: dict[str, Any]) -> str:
    """Format a human-readable alert message from watch state change."""
    provider = item.get("provider", "")
    base = item.get("message", "Watch triggered")

    if provider == "github-pr":
        if state.get("merged"):
            return f"{base} — MERGED"
        if state.get("has_approval"):
            approvers = [r["user"] for r in state.get("reviews", []) if r["state"] == "APPROVED"]
            return f"{base} — APPROVED by {', '.join(approvers)}"
        return f"{base} — state changed"

    if provider == "jira-query":
        new_issues = state.get("issues", [])[:3]
        keys = ", ".join(i["key"] for i in new_issues)
        return f"{base} — new: {keys}" if keys else f"{base} — results changed"

    if provider == "jira-ticket":
        return f"{base} — now: {state.get('status', '?')}"

    return base


# ── programmatic API (for status_check.py, morning.md) ──────────────────────

def get_due_reminders(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return pending reminders that are due. No side effects."""
    items = load_items()
    if now is None:
        now = datetime.now(LOCAL_TZ)
    due = []
    for item in items:
        if item["type"] != "reminder" or item["status"] not in ("pending", "snoozed"):
            continue
        if item["status"] == "snoozed" and item.get("snoozed_until"):
            if datetime.fromisoformat(item["snoozed_until"]) > now:
                continue
        if datetime.fromisoformat(item["due_at"]) <= now:
            due.append(item)
    return due


def get_upcoming_reminders(now: datetime | None = None, hours: int = 24) -> list[dict[str, Any]]:
    """Return pending reminders due within N hours."""
    items = load_items()
    if now is None:
        now = datetime.now(LOCAL_TZ)
    horizon = now + timedelta(hours=hours)
    upcoming = []
    for item in items:
        if item["type"] != "reminder" or item["status"] not in ("pending", "snoozed"):
            continue
        reminder_due = datetime.fromisoformat(item["due_at"])
        if now < reminder_due <= horizon:
            upcoming.append(item)
    upcoming.sort(key=lambda r: r["due_at"])
    return upcoming


def get_unseen_alerts() -> list[dict[str, Any]]:
    """Return unseen alerts from daemon."""
    return [a for a in load_alerts() if not a.get("seen")]


def get_active_watches() -> list[dict[str, Any]]:
    """Return all active watches."""
    return [i for i in load_items() if i["type"] == "watch" and i["status"] == "active"]


# ── CLI entry ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified scheduler — reminders, watches, recurring, events.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # remind
    p = sub.add_parser("remind", help="Add a one-shot reminder")
    p.add_argument("--due", "-d", required=True, help="When: 'tomorrow 9am', 'in 2 hours', ISO8601")
    p.add_argument("--message", "-m", required=True, help="Reminder message")
    p.add_argument("--tag", "-t", default="", help="Comma-separated tags")
    p.set_defaults(func=cmd_remind)

    # watch
    p = sub.add_parser("watch", help="Add a condition-based watch")
    p.add_argument("provider", help="Provider: github-pr, jira-query, jira-ticket")
    p.add_argument("target", help="Target: owner/repo#123, JQL string, or TICKET-123")
    p.add_argument("--message", "-m", required=True, help="Watch description")
    p.add_argument("--tag", "-t", default="", help="Comma-separated tags")
    p.add_argument("--condition", "-c", default="", help="Condition: approved_or_merged, new_results, status_changed")
    p.add_argument("--interval", "-i", type=int, default=30, help="Poll interval in minutes (default: 30)")
    p.add_argument("--remove-when", default="", help="Auto-remove condition: merged_or_closed")
    p.set_defaults(func=cmd_watch)

    # recurring
    p = sub.add_parser("recurring", help="Add a persistent recurring session job")
    p.add_argument("--cron", "-c", required=True, help="5-field cron expression (local time)")
    p.add_argument("--message", "-m", required=True, help="Short description")
    p.add_argument("--prompt", "-p", default="", help="Full prompt to run at each fire time")
    p.add_argument("--tag", "-t", default="", help="Comma-separated tags")
    p.set_defaults(func=cmd_recurring)

    # list
    p = sub.add_parser("list", help="List scheduled items")
    p.add_argument("--all", "-a", action="store_true", help="Include dismissed/delivered")
    p.add_argument("--type", choices=["reminder", "watch", "recurring", "event"])
    p.set_defaults(func=cmd_list)

    # check
    p = sub.add_parser("check", help="Check for due reminders and alerts")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_check)

    # dismiss
    p = sub.add_parser("dismiss", help="Dismiss an item")
    p.add_argument("id", help="Item ID (prefix match ok)")
    p.set_defaults(func=cmd_dismiss)

    # snooze
    p = sub.add_parser("snooze", help="Snooze a reminder")
    p.add_argument("id", help="Item ID (prefix match ok)")
    p.add_argument("--until", "-u", required=True, help="Snooze until: 'in 1 hour', 'tomorrow 9am'")
    p.set_defaults(func=cmd_snooze)

    # poll
    p = sub.add_parser("poll", help="Run one poll cycle (for daemon/cron)")
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress output on no changes")
    p.set_defaults(func=cmd_poll)

    # alerts
    p = sub.add_parser("alerts", help="Show alerts from background watcher")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.add_argument("--mark-seen", action="store_true", help="Mark all alerts as seen")
    p.set_defaults(func=cmd_alerts)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
