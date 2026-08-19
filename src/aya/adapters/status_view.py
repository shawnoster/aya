"""Rendering for ``aya status``.

Three presentations of one gathered dict — JSON, plain text, and Rich.
Kept apart from the gathering so each can be tested by passing data in
rather than by driving a command.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.rule import Rule

from aya.adapters.credentials import CredentialsReport
from aya.scheduler import watch_target
from aya.usecases.status import (
    ALERT_DISPLAY_LIMIT,
    DUE_DISPLAY_LIMIT,
    ID_PREVIEW_LENGTH,
    UPCOMING_DISPLAY_LIMIT,
    WATCH_DISPLAY_LIMIT,
    _gather_status,
    _greeting,
    _parse_next_eval,
    _perspective,
    _time_flavor,
)


def _render_plain(data: dict[str, Any]) -> str:
    """Compact plain-text status — no Rich markup, minimal lines."""
    ok = data["checks_ok"]
    total = data["checks_total"]
    checks = data["checks"]

    lines: list[str] = []
    lines.append(_greeting(data["now_local"], data["user"], data["ship"]))
    lines.append(_time_flavor(data["now_local"]))

    if ok == total:
        lines.append(f"Systems {ok}/{total} OK")
    else:
        failed = [c for c in checks if not c.ok]
        lines.append(f"Systems {ok}/{total} — failed: {', '.join(c.name for c in failed)}")

    credentials: CredentialsReport = data["credentials"]
    lit_services = [s.name for s in credentials.services if s.state == "lit"]
    partial_services = [
        f"{s.name} (missing {', '.join(s.missing)})"
        for s in credentials.services
        if s.state == "partial"
    ]
    dark_services = [s.name for s in credentials.services if s.state == "dark"]
    cred_summary = (
        f"Credentials {credentials.lit} lit · {credentials.partial} partial · "
        f"{credentials.dark} dark"
    )
    lines.append(cred_summary)
    if lit_services:
        lines.append(f"  lit: {', '.join(lit_services)}")
    if partial_services:
        lines.append(f"  partial: {'; '.join(partial_services)}")
    if dark_services:
        lines.append(f"  dark: {', '.join(dark_services)}")

    for a in data["unseen"][:ALERT_DISPLAY_LIMIT]:
        lines.append(f"  alert: {a['source_item_id'][:ID_PREVIEW_LENGTH]}  {a['message'][:60]}")

    for r in data["due"][:DUE_DISPLAY_LIMIT]:
        due_dt = datetime.fromisoformat(r["due_at"])
        msg = r["message"][:55]
        lines.append(f"  due: {r['id'][:ID_PREVIEW_LENGTH]}  {due_dt.strftime('%I:%M %p')}  {msg}")

    for r in data["upcoming"][:UPCOMING_DISPLAY_LIMIT]:
        rd = datetime.fromisoformat(r["due_at"])
        lines.append(f"  upcoming: {rd.strftime('%I:%M %p')}  {r['message'][:55]}")

    for w in data["active_watches"][:WATCH_DISPLAY_LIMIT]:
        target = watch_target(w)
        target_str = f"  {target}" if target else ""
        lines.append(f"  watch: {w['id'][:ID_PREVIEW_LENGTH]}{target_str}  {w['message'][:50]}")

    next_eval_result = _parse_next_eval(data["next_eval"], data["now_local"])
    if next_eval_result:
        date_str, _ = next_eval_result
        lines.append(f"  Name re-eval due: {date_str}")

    lines.append(_perspective())
    return "\n".join(lines)


def _render_json(data: dict[str, Any]) -> str:
    """Machine-readable JSON status."""
    ok = data["checks_ok"]
    total = data["checks_total"]
    checks = data["checks"]

    credentials: CredentialsReport = data["credentials"]
    credentials_payload: dict[str, Any] = {
        "lit": credentials.lit,
        "partial": credentials.partial,
        "dark": credentials.dark,
        "services": {
            s.name: {
                "state": s.state,
                "required": s.required,
                "set": s.set_vars,
                "missing": s.missing,
            }
            for s in credentials.services
        },
    }

    payload: dict[str, Any] = {
        "greeting": _greeting(data["now_local"], data["user"], data["ship"]),
        "time_flavor": _time_flavor(data["now_local"]),
        "systems": {
            "ok": ok == total,
            "passed": ok,
            "total": total,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        },
        "credentials": credentials_payload,
        "alerts": [
            {
                "id": a.get("id", "")[:ID_PREVIEW_LENGTH],
                "source_item_id": a["source_item_id"][:ID_PREVIEW_LENGTH],
                "message": a["message"],
            }
            for a in data["unseen"]
        ],
        "due": [
            {"id": r["id"][:ID_PREVIEW_LENGTH], "due_at": r["due_at"], "message": r["message"]}
            for r in data["due"]
        ],
        "upcoming": [{"due_at": r["due_at"], "message": r["message"]} for r in data["upcoming"]],
        # provider/last_checked_at/consecutive_failures are carried here because
        # this payload is what non-interactive consumers (the MCP status tool,
        # scripts) see. Emitting only id and message hides a watch that is
        # failing every poll, which the Rich view below does show.
        "watches": [
            {
                "id": w["id"][:ID_PREVIEW_LENGTH],
                "message": w["message"],
                "provider": w.get("provider"),
                # What the watch points at. Reassembled from watch_config,
                # which is where the parsed target actually lives.
                "target": watch_target(w),
                "last_checked_at": w.get("last_checked_at"),
                "consecutive_failures": w.get("consecutive_failures", 0),
            }
            for w in data["active_watches"]
        ],
        "next_eval": data["next_eval"],
        "perspective": _perspective(),
    }
    return json.dumps(payload, indent=2, default=str)


def _render_rich(data: dict[str, Any], console: Console) -> None:
    """Full Rich-formatted status for interactive terminal use."""
    now_local = data["now_local"]
    checks = data["checks"]
    ok = data["checks_ok"]
    total = data["checks_total"]
    all_ok = ok == total

    console.print()
    console.print(f"[bold]{_greeting(now_local, data['user'], data['ship'])}[/bold]")
    console.print(f"[dim]{_time_flavor(now_local)}[/dim]")
    console.print()

    if all_ok:
        console.print(f"[green]✓[/green] Systems  [dim]{ok}/{total} checks passed[/dim]")
    else:
        console.print(f"[yellow]⚠[/yellow] Systems  [yellow]{ok}/{total} checks passed[/yellow]")
        for c in checks:
            if not c.ok:
                console.print(f"  [red]✗[/red] {c.name}  [dim]{c.detail}[/dim]")

    credentials: CredentialsReport = data["credentials"]
    total_services = len(credentials.services)
    if total_services:
        if credentials.lit == total_services:
            # Everyone's lit — one-line summary, Ship Mind satisfied.
            console.print(
                f"[green]✓[/green] Credentials  "
                f"[dim]{credentials.lit}/{total_services} services lit[/dim]"
            )
        else:
            console.print(
                f"[yellow]◐[/yellow] Credentials  "
                f"[dim]{credentials.lit} lit · {credentials.partial} partial · "
                f"{credentials.dark} dark[/dim]"
            )
            for s in credentials.services:
                if s.state == "lit":
                    console.print(f"  [green]✓[/green] {s.name}")
                elif s.state == "partial":
                    missing = ", ".join(s.missing)
                    console.print(f"  [yellow]◐[/yellow] {s.name}  [dim]missing {missing}[/dim]")
                else:  # dark
                    console.print(f"  [dim]○ {s.name}  (dark)[/dim]")

    next_eval_result = _parse_next_eval(data["next_eval"], now_local)
    if next_eval_result:
        date_str, _ = next_eval_result
        console.print(f"  [dim]Name re-eval due: {date_str}[/dim]")

    console.print()

    unseen = data["unseen"]
    if unseen:
        console.print(f"[bold red]🔔 {len(unseen)} alert(s):[/bold red]")
        for a in unseen[:ALERT_DISPLAY_LIMIT]:
            console.print(f"  📢 {a['source_item_id'][:ID_PREVIEW_LENGTH]}  {a['message'][:60]}")
        if len(unseen) > ALERT_DISPLAY_LIMIT:
            console.print(f"  [dim]… and {len(unseen) - ALERT_DISPLAY_LIMIT} more[/dim]")
        console.print()

    due = data["due"]
    if due:
        console.print(f"[bold yellow]⏰ {len(due)} reminder(s) due:[/bold yellow]")
        for r in due[:DUE_DISPLAY_LIMIT]:
            due_dt = datetime.fromisoformat(r["due_at"])
            msg = r["message"][:55]
            console.print(
                f"  🔴 {r['id'][:ID_PREVIEW_LENGTH]}  {due_dt.strftime('%I:%M %p')}  {msg}"
            )
        if len(due) > DUE_DISPLAY_LIMIT:
            console.print(f"  [dim]… and {len(due) - DUE_DISPLAY_LIMIT} more[/dim]")
        console.print()

    upcoming = data["upcoming"]
    if upcoming:
        console.print("[bold]Upcoming (12h):[/bold]")
        for r in upcoming[:UPCOMING_DISPLAY_LIMIT]:
            rd = datetime.fromisoformat(r["due_at"])
            console.print(f"  ⏳ {rd.strftime('%I:%M %p')}  {r['message'][:55]}")
        console.print()

    active_watches = data["active_watches"]
    if active_watches:
        console.print(f"[bold]Watches ({len(active_watches)} active):[/bold]")
        for w in active_watches[:WATCH_DISPLAY_LIMIT]:
            last = w.get("last_checked_at")
            last_str = datetime.fromisoformat(last).strftime("%H:%M") if last else "never"
            msg = w["message"][:50]
            target = watch_target(w)
            target_str = f"  [cyan]{escape(target)}[/cyan]" if target else ""
            failures = w.get("consecutive_failures", 0)
            health = f"  [yellow]⚠ {failures} failed poll(s)[/yellow]" if failures else ""
            console.print(
                f"  👁  {w['id'][:ID_PREVIEW_LENGTH]}{target_str}  {msg}  "
                f"[dim]checked {last_str}[/dim]{health}"
            )
        console.print()

    console.print(Rule(style="dim"))
    console.print(f"[dim italic]{_perspective()}[/dim italic]")
    if not all_ok:
        console.print(f"[yellow]⚠ {total - ok} check(s) degraded — verify paths above.[/yellow]")
    console.print()


def run_status(format_: str = "text") -> None:
    """Entry point for aya status subcommand."""
    data = _gather_status()
    if format_ == "json":
        print(_render_json(data))  # noqa: T201 — raw stdout for JSON
    elif format_ == "rich":
        _render_rich(data, Console())
    elif format_ == "text":
        print(_render_plain(data))  # noqa: T201 — raw stdout for plain text
    else:
        sys.stderr.write(
            f"aya status: unknown format '{format_}'. Expected one of: text, json, rich.\n"
        )
        raise SystemExit(2)
