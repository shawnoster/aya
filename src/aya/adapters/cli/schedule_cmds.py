"""Scheduler: reminders, watches, recurring jobs, install/uninstall."""

from __future__ import annotations

import logging
from datetime import datetime

import typer

from aya.adapters.cli._kernel import (
    ErrorCode,
    OutputFormat,
    _emit_error,
    _output_json,
    console,
    err,
    resolve_format,
    schedule_app,
)
from aya.adapters.config import load_config, set_config_value
from aya.adapters.install import install_scheduler, uninstall_scheduler

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.scheduler import (
    DEFAULT_PRUNE_DAYS,
    SEVERITY_ACTIONABLE,
    SEVERITY_HEARTBEAT,
    AlertItem,
    AlertSeverity,
    SchedulerItem,
    _display_items,
    add_recurring,
    add_reminder,
    add_watch,
    dismiss_alert,
    dismiss_item,
    format_pending,
    format_scheduler_status,
    get_pending,
    get_scheduler_status,
    is_idle,
    list_items,
    parse_due,
    prune_items,
    record_activity,
    run_tick,
    show_alerts,
    snooze_item,
    validate_watch,
)

logger = logging.getLogger(__name__)


@schedule_app.command("remind")
def schedule_remind(
    message: str = typer.Option(..., "--message", "-m", help="Reminder message"),
    due: str = typer.Option(..., "--due", "-d", help="When: 'tomorrow 9am', 'in 2 hours', ISO8601"),
    tag: str = typer.Option("", "--tags", "-t", help="Comma-separated tags"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show reminder without saving"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Add a one-shot reminder."""
    format_ = resolve_format(format_)
    if dry_run:
        due_dt = parse_due(due)
        preview = {
            "type": "reminder",
            "status": "pending",
            "message": message,
            "tags": [t.strip() for t in tag.split(",") if t.strip()] if tag else [],
            "due_at": due_dt.isoformat(),
        }
        _output_json({"item": preview})
        raise typer.Exit(0)
    item = add_reminder(message, due, tag)
    if format_ == OutputFormat.JSON:
        _output_json({"item": item})
        raise typer.Exit(0)
    due_dt = parse_due(due)
    console.print(
        f"[green]✓[/green] Reminder {item['id'][:8]} — {due_dt.strftime('%a %b %d, %I:%M %p')}"
    )
    console.print(f"  {message}")


@schedule_app.command("watch")
def schedule_watch(
    provider: str = typer.Argument(
        help="Provider: github-pr, ci-checks, jira-query, jira-ticket, relay-inbox"
    ),
    target: str = typer.Argument(
        help=(
            "Target: owner/repo#123, JQL, TICKET-123, or an instance label "
            "('default' for the primary) for relay-inbox"
        )
    ),
    message: str = typer.Option(..., "--message", "-m", help="Watch description"),
    tag: str = typer.Option("", "--tags", "-t", help="Comma-separated tags"),
    condition: str = typer.Option(
        "",
        "--condition",
        "-c",
        help=(
            "Condition that triggers the alert. "
            "github-pr: approved_or_merged (default), merged, new_comments. "
            "jira-query: new_results. jira-ticket: status_changed. "
            "ci-checks: checks_failed, checks_complete. "
            "relay-inbox: new_packets."
        ),
    ),
    interval: int = typer.Option(30, "--interval", "-i", help="Poll interval minutes"),
    remove_when: str = typer.Option("", help="Auto-remove: merged_or_closed"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show watch without saving"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Add a condition-based watch."""
    format_ = resolve_format(format_)
    # Validate against the scheduler's own rules rather than a second, narrower
    # copy — the local gate never learned about ci-checks, so the CLI rejected
    # specs the MCP surface accepted.
    try:
        _, resolved_condition, resolved_interval = validate_watch(
            provider, target, condition, interval
        )
    except ValueError as exc:
        _emit_error(ErrorCode.INVALID_ARGUMENT, str(exc), {"provider": provider}, exit_code=2)

    if dry_run:
        preview = {
            "type": "watch",
            "status": "active",
            "message": message,
            "tags": [t.strip() for t in tag.split(",") if t.strip()] if tag else [],
            "provider": provider,
            "target": target,
            # Both fields come from validate_watch rather than a second table:
            # a local copy of the per-provider defaults is what made --dry-run
            # print a blank condition for any provider it had not learned about,
            # and the same for the provider-specific interval tightening.
            "condition": resolved_condition,
            "poll_interval_minutes": resolved_interval,
            "remove_when": remove_when,
        }
        _output_json({"item": preview})
        raise typer.Exit(0)
    try:
        item = add_watch(provider, target, message, tag, condition, interval, remove_when)
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if format_ == OutputFormat.JSON:
        _output_json({"item": item})
        raise typer.Exit(0)
    console.print(f"[green]✓[/green] Watch {item['id'][:8]} ({provider})")
    console.print(f"  {message}")
    console.print(f"  Condition: {item['condition']}, poll every {item['poll_interval_minutes']}m")


@schedule_app.command("recurring")
def schedule_recurring(
    message: str = typer.Option(..., "--message", "-m", help="Short label for this recurring job"),
    cron: str = typer.Option(..., "--cron", "-c", help="Cron expression, e.g. '13,43 * * * *'"),
    prompt: str = typer.Option("", "--prompt", "-p", help="Prompt delivered to Claude each firing"),
    tag: str = typer.Option("", "--tags", "-t", help="Comma-separated tags"),
    idle_back_off: str = typer.Option(
        "",
        "--idle-back-off",
        help="Suppress when idle for longer than this (e.g. '30m', '1h')",
    ),
    only_during: str = typer.Option(
        "",
        "--only-during",
        help="Only fire within this time window, e.g. '08:00-18:00'",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show cron without saving"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Add a persistent recurring session job (session_required cron)."""
    format_ = resolve_format(format_)
    # Validate cron expression before dry-run output
    parts = cron.strip().split()
    if len(parts) != 5:
        err.print(f"[red]Invalid cron expression (expected 5 fields): {cron}[/red]")
        raise typer.Exit(1)

    if dry_run:
        preview = {
            "type": "recurring",
            "status": "active",
            "message": message,
            "tags": [t.strip() for t in tag.split(",") if t.strip()] if tag else [],
            "session_required": True,
            "cron": cron,
            "prompt": prompt,
            "idle_back_off": idle_back_off,
            "only_during": only_during,
        }
        _output_json({"item": preview})
        raise typer.Exit(0)
    try:
        item = add_recurring(message, cron, prompt, tag, idle_back_off, only_during)
    except ValueError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    if format_ == OutputFormat.JSON:
        _output_json({"item": item})
        raise typer.Exit(0)
    console.print(f"[green]✓[/green] Recurring {item['id'][:8]} — {cron}")
    console.print(f"  {message}")
    if idle_back_off:
        console.print(f"  Idle back-off: {idle_back_off}")
    if only_during:
        console.print(f"  Only during: {only_during}")


@schedule_app.command("activity")
def schedule_activity() -> None:
    """Record user activity — resets the idle back-off timer.

    Call this whenever the user is known to be active (e.g. on each new message
    or via a SessionStart / PreToolUse hook) so that idle-aware recurring crons
    are not suppressed unnecessarily.
    """
    record_activity()
    console.print("[green]✓[/green] Activity recorded.")


@schedule_app.command("is-idle")
def schedule_is_idle(
    threshold: str = typer.Option(
        "30m", "--threshold", "-t", help="Idle threshold (e.g. '30m', '1h')"
    ),
) -> None:
    """Check whether the session is currently idle.

    Exits with code 0 (active) or 1 (idle) so shell scripts can branch on it.
    """
    try:
        idle = is_idle(threshold)
    except ValueError as exc:
        err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(2) from exc
    if idle:
        console.print(f"[yellow]idle[/yellow] (threshold: {threshold})")
        raise typer.Exit(1)
    console.print(f"[green]active[/green] (threshold: {threshold})")


@schedule_app.command("list")
def schedule_list(
    all_items: bool = typer.Option(False, "--all", "-a", help="Include dismissed/delivered"),
    item_type: str = typer.Option(None, "--type", help="Filter: reminder, watch, recurring, event"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """List scheduled items."""
    format_ = resolve_format(format_)
    items = list_items(show_all=all_items, item_type=item_type)
    if format_ == OutputFormat.JSON:
        _output_json({"items": items})
    else:
        _display_items(items)


@schedule_app.command("prune")
def schedule_prune(
    older_than: int = typer.Option(
        DEFAULT_PRUNE_DAYS, "--older-than", help="Drop finished items older than N days"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would go"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Drop dismissed and done items. Nothing that could still fire is touched."""
    format_ = resolve_format(format_)
    pruned, remaining = prune_items(older_than_days=older_than, dry_run=dry_run)

    if format_ == OutputFormat.JSON:
        _output_json(
            {
                "pruned": [
                    {"id": i["id"], "type": i.get("type"), "status": i.get("status")}
                    for i in pruned
                ],
                "pruned_count": len(pruned),
                "remaining": remaining,
                "older_than_days": older_than,
                "dry_run": dry_run,
            }
        )
        return

    # "would drop" only in dry-run: a preview that reports the change as done is
    # how `schedule install` came to claim a crontab it had not written.
    verb = "would drop" if dry_run else "dropped"
    if not pruned:
        console.print(f"[dim]Nothing to prune — no finished items older than {older_than}d.[/dim]")
        return
    console.print(f"[yellow]{verb}[/yellow] {len(pruned)} item(s) older than {older_than}d:")
    for item in pruned[:10]:
        console.print(
            f"  {item['id'][:8]}  {item.get('type', '?')}/{item.get('status', '?')}  "
            f"{str(item.get('message', ''))[:50]}"
        )
    if len(pruned) > 10:
        console.print(f"  [dim]… and {len(pruned) - 10} more[/dim]")
    tense = "would remain" if dry_run else "remain"
    console.print(f"[dim]{remaining} item(s) {tense}.[/dim]")


@schedule_app.command("dismiss")
def schedule_dismiss(
    item_id: str = typer.Argument(help="Item ID (prefix match ok)"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Dismiss a scheduled item or alert."""
    format_ = resolve_format(format_)
    item: SchedulerItem | AlertItem
    try:
        item = dismiss_item(item_id)
    except ValueError:
        try:
            item = dismiss_alert(item_id)
        except ValueError as exc:
            err.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
    if format_ == OutputFormat.JSON:
        _output_json({"dismissed": item["id"], "status": "dismissed"})
        raise typer.Exit(0)
    console.print(f"[green]✓[/green] Dismissed {item['id'][:8]} — {item['message'][:60]}")


@schedule_app.command("snooze")
def schedule_snooze(
    item_id: str = typer.Argument(help="Item ID (prefix match ok)"),
    until: str = typer.Option(
        ..., "--until", "-u", help="Snooze until: 'in 1 hour', 'tomorrow 9am'"
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Snooze a reminder."""
    format_ = resolve_format(format_)
    try:
        item, snooze_until = snooze_item(item_id, until)
    except ValueError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if format_ == OutputFormat.JSON:
        _output_json({"snoozed": item["id"], "until": snooze_until.isoformat()})
        raise typer.Exit(0)
    console.print(
        f"💤 Snoozed {item['id'][:8]} until {snooze_until.strftime('%a %b %d, %I:%M %p')}"
    )


@schedule_app.command("tick")
def schedule_tick(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output"),
) -> None:
    """Run one scheduler tick — poll watches, check reminders, sweep stale claims.

    Canonical entry point for system cron:
        */5 * * * * aya scheduler tick --quiet
    """
    result = run_tick(quiet=quiet)
    if not quiet:
        active = result.get("session_active")
        session_note = " (session active — delivery deferred)" if active else ""
        console.print(
            f"[dim]Tick complete. Claims swept: {result['claims_swept']}{session_note}[/dim]"
        )


@schedule_app.command("pending")
def schedule_pending(
    all_severities: bool = typer.Option(
        False, "--all", "-a", help="Show all alerts including info/heartbeat"
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Show pending items for this session — alerts to deliver + session crons.

    SessionStart hook entry point:
        aya scheduler pending --format text
    """
    format_ = resolve_format(format_)
    if format_ == OutputFormat.JSON:
        min_severity: AlertSeverity = SEVERITY_HEARTBEAT if all_severities else SEVERITY_ACTIONABLE
        pending = get_pending(min_severity=min_severity)
        _output_json(pending)
    else:
        # Always fetch all severities for text output so format_pending
        # can summarize queued non-actionable alerts without --all.
        pending = get_pending(min_severity=SEVERITY_HEARTBEAT)
        # Same reason as schedule status below: format_pending is plain text and
        # brackets both the severity and the cron meta block, which Rich would
        # read as style tags and drop.
        console.print(format_pending(pending, show_all=all_severities), markup=False)


@schedule_app.command("status")
def schedule_status(
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Show scheduler overview — watches, reminders, crons, deliveries."""
    format_ = resolve_format(format_)
    status = get_scheduler_status()
    if format_ == OutputFormat.JSON:
        _output_json(status)
    else:
        # format_scheduler_status is plain text and brackets each watch's provider
        # label. Rich reads "[relay-inbox]" as a style tag and drops it, so markup
        # must stay off on this line.
        console.print(format_scheduler_status(status), markup=False)


@schedule_app.command("alerts")
def schedule_alerts(
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
    mark_seen: bool = typer.Option(False, "--mark-seen", help="Mark all alerts as seen"),
) -> None:
    """Show alerts from background watcher."""
    format_ = resolve_format(format_)
    unseen = show_alerts(mark_seen=mark_seen)

    if format_ == OutputFormat.JSON:
        _output_json({"alerts": unseen})
        return

    if not unseen:
        console.print("[dim]No unseen alerts.[/dim]")
        return

    console.print(f"\n  [bold]🔔 {len(unseen)} alert(s):[/bold]")
    for a in unseen:
        ts = datetime.fromisoformat(a["created_at"]).strftime("%b %d %I:%M %p")
        console.print(f"    📢 {a['source_item_id'][:8]}  {ts}  {a['message'][:55]}")

    if mark_seen:
        console.print(f"\n  Marked {len(unseen)} alert(s) as seen.")


@schedule_app.command("install")
def schedule_install(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview changes without applying"),
    tick_interval: str | None = typer.Option(
        None,
        "--tick-interval",
        help=(
            "How often the scheduler ticks (e.g. '30s', '1m', '5m', '1h'). "
            "Sub-minute intervals generate multi-line crontab entries with "
            "sleep offsets. Persisted to ~/.aya/config.json so re-runs without "
            "this flag preserve the chosen value. Default: 5m on first install."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace any existing aya cron entries instead of treating them as already-installed.",
    ),
) -> None:
    """Install scheduler integrations — system crontab + Claude Code hooks."""
    from aya.adapters.install import DEFAULT_TICK_INTERVAL

    # Resolve the effective tick interval: explicit flag > persisted config > default.
    if tick_interval is None:
        cfg = load_config()
        tick_interval = cfg.get("tick_interval", DEFAULT_TICK_INTERVAL)

    result = install_scheduler(dry_run=dry_run, tick_interval=tick_interval, force=force)

    if result.errors:
        for e in result.errors:
            err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Persist the chosen interval (only on a successful real install,
    # not dry-run or already-present cases — those don't change state).
    if not dry_run and result.cron_installed:
        set_config_value("tick_interval", tick_interval)

    prefix = "[dim](dry run)[/dim] " if dry_run else ""
    # A dry run reports what *would* change, so it has to say so. "installed"
    # is one word from "already installed" in this same block, and that line is
    # a statement of current state — so the two must not share a verb, or a dry
    # run against a machine with nothing installed reads as confirmation.
    did = "would install" if dry_run else "installed"
    did_update = "would update" if dry_run else "updated"

    if result.cron_already_present:
        console.print(
            f"  {prefix}[dim]Crontab:[/dim] already installed "
            f"[dim](use --force to replace with --tick-interval {tick_interval})[/dim]"
        )
    elif result.cron_installed:
        console.print(f"  {prefix}[green]Crontab:[/green] {did} (tick={tick_interval})")
        for line in result.cron_lines:
            console.print(f"    [dim]{line}[/dim]")

    for event in result.hooks_already_present:
        console.print(f"  {prefix}[dim]{event}:[/dim] already installed")
    for event in result.hooks_installed:
        console.print(f"  {prefix}[green]{event}:[/green] {did}")
    for event in result.hooks_updated:
        console.print(f"  {prefix}[yellow]{event}:[/yellow] {did_update}")

    if result.opencode_plugin_already_present:
        console.print(f"  {prefix}[dim]OpenCode plugin:[/dim] already installed")
    elif result.opencode_plugin_installed:
        console.print(f"  {prefix}[green]OpenCode plugin:[/green] {did}")

    if not dry_run and not result.errors:
        console.print("\n[green]✓[/green] Scheduler integrations installed.")
    elif result.errors:
        raise typer.Exit(1)


@schedule_app.command("uninstall")
def schedule_uninstall(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview changes without applying"),
) -> None:
    """Remove scheduler integrations — system crontab + Claude Code hooks."""
    result = uninstall_scheduler(dry_run=dry_run)

    if result.errors:
        for e in result.errors:
            err.print(f"[red]Error:[/red] {e}")

    prefix = "[dim](dry run)[/dim] " if dry_run else ""

    if result.cron_removed:
        console.print(f"  {prefix}[yellow]Crontab:[/yellow] removed")
    elif result.cron_unreadable:
        # The crontab could not be read, so "not present" would be a claim about
        # a state nobody observed. install exits before reaching its equivalent
        # line; uninstall carries on removing hooks, so it says so instead.
        console.print(f"  {prefix}[yellow]Crontab:[/yellow] unknown — see the error above")
    else:
        console.print(f"  {prefix}[dim]Crontab:[/dim] not present")

    for event in result.hooks_removed:
        console.print(f"  {prefix}[yellow]{event}:[/yellow] removed")

    if not result.hooks_removed:
        console.print(f"  {prefix}[dim]Hooks:[/dim] not present")

    if result.opencode_plugin_removed:
        console.print(f"  {prefix}[yellow]OpenCode plugin:[/yellow] removed")
    else:
        console.print(f"  {prefix}[dim]OpenCode plugin:[/dim] not present")

    if not dry_run and not result.errors:
        console.print("\n[green]✓[/green] Scheduler integrations removed.")
    elif result.errors:
        raise typer.Exit(1)
