"""Workspace: status, context, daily log."""

from __future__ import annotations

import logging

import typer

from aya.adapters.cli._kernel import (
    ErrorCode,
    OutputFormat,
    StatusFormat,
    _copy_to_clipboard,
    _emit_error,
    _output_json,
    app,
    console,
    err,
    log_app,
    resolve_format,
    resolve_status_format,
)
from aya.adapters.config import get_notebook_path

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.adapters.status_view import run_status
from aya.usecases.context import build_context_block

logger = logging.getLogger(__name__)


@app.command()
def status(
    format_: StatusFormat = typer.Option(
        StatusFormat.AUTO,
        "--format",
        "-f",
        help="Output format: auto (default), text, json, or rich",
    ),
) -> None:
    """Workspace readiness check — systems, schedule, focus."""
    format_ = resolve_status_format(format_)
    run_status(format_=format_)


@app.command("context")
def context_cmd(
    short: bool = typer.Option(False, "--short", help="Compact one-line format"),
    copy: bool = typer.Option(False, "--copy", help="Copy output to clipboard"),
    all_projects: bool = typer.Option(False, "--all", help="Include brainstorming projects"),
    project: str | None = typer.Option(None, "--project", help="Filter to a single project"),
) -> None:
    """Assemble a paste-ready session handshake block from the notebook."""
    notebook_path = get_notebook_path()
    if not notebook_path:
        err.print(
            "[red]notebook_path not set.[/red] "
            "Set [bold]AYA_NOTEBOOK_PATH[/bold] or run: "
            "[bold]aya config set notebook_path ~/notebook[/bold]"
        )
        raise typer.Exit(1)
    if not notebook_path.exists():
        err.print(f"[red]Notebook path does not exist:[/red] {notebook_path}")
        raise typer.Exit(1)

    output = build_context_block(
        notebook_path,
        short=short,
        include_brainstorming=all_projects,
        project_filter=project,
    )
    console.print(output)

    if copy:
        _copy_to_clipboard(output)


@log_app.command("append")
def log_append(
    message: str = typer.Option(..., "--message", "-m", help="Progress entry text"),
    tags: str | None = typer.Option(
        None,
        "--tags",
        "-t",
        help="Comma-separated tags (e.g. pr/174,fix/170)",
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--format",
        "-f",
        help="Output format",
    ),
) -> None:
    """Append a timestamped entry to today's daily note."""
    from aya.usecases.log import append_entry

    fmt = resolve_format(format_)
    try:
        daily, entry = append_entry(message, tags=tags)
    except ValueError as exc:
        _emit_error(ErrorCode.INVALID_ARGUMENT, str(exc))
    if fmt == OutputFormat.JSON:
        _output_json({"entry": entry, "file": str(daily)})
    else:
        console.print(f"[green]✓[/green] {entry}")
        console.print(f"[dim]{daily}[/dim]")


@log_app.command("auto")
def log_auto(
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--format",
        "-f",
        help="Output format",
    ),
) -> None:
    """Inspect recent activity and log a summary if warranted.

    Exits silently if nothing noteworthy is detected or if the last entry
    was written less than 5 minutes ago.
    """
    from aya.usecases.log import auto_log

    fmt = resolve_format(format_)
    try:
        result = auto_log()
    except ValueError as exc:
        _emit_error(ErrorCode.INVALID_ARGUMENT, str(exc))
    if result is None:
        if fmt == OutputFormat.JSON:
            _output_json({"logged": False})
        # Text mode: silent when nothing logged (per design spec)
        return
    daily, entry = result
    if fmt == OutputFormat.JSON:
        _output_json({"logged": True, "entry": entry, "file": str(daily)})


@log_app.command("show")
def log_show(
    date: str | None = typer.Option(
        None,
        "--date",
        "-d",
        help="Date to show (YYYY-MM-DD, default: today)",
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO,
        "--format",
        "-f",
        help="Output format",
    ),
) -> None:
    """Display progress entries for today (or a given date)."""
    from aya.scheduler.time_utils import _get_local_tz
    from aya.usecases.log import show_entries

    fmt = resolve_format(format_)
    dt = None
    if date:
        from datetime import datetime as _dt

        try:
            dt = _dt.strptime(date, "%Y-%m-%d").replace(tzinfo=_get_local_tz())
        except ValueError:
            _emit_error(
                ErrorCode.INVALID_ARGUMENT,
                f"Invalid date format: {date!r} (expected YYYY-MM-DD)",
            )

    try:
        entries = show_entries(date=dt)
    except ValueError as exc:
        _emit_error(ErrorCode.INVALID_ARGUMENT, str(exc))

    if fmt == OutputFormat.JSON:
        _output_json({"date": date or "today", "entries": entries})
        return

    if not entries:
        console.print("[dim]No progress entries found.[/dim]")
        return

    for e in entries:
        line = f"[{e['time']}] {e['message']}"
        if "tags" in e:
            line += f" — {e['tags']}"
        console.print(line)
