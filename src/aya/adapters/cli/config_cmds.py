"""Workspace config and the relay list."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.table import Table

from aya.adapters import paths as _paths
from aya.adapters.cli._kernel import (
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _emit_error,
    _load_profile_for_relay,
    _output_json,
    _resolve_instance_labelled,
    _validate_relay_url,
    config_app,
    console,
    relay_app,
    resolve_format,
)
from aya.adapters.config import load_config, set_config_value
from aya.adapters.profile_store import save_profile

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.

logger = logging.getLogger(__name__)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (e.g. notebook_path)"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a config value in ~/.aya/config.json."""
    set_config_value(key, value)
    console.print(f"[green]✓[/green] {key} = {value}")
    console.print(f"[dim]Saved to {_paths.CONFIG_PATH}[/dim]")


@config_app.command("show")
def config_show() -> None:
    """Show current config."""
    config = load_config()
    if not config:
        console.print("[dim]No config set. Use `aya config set <key> <value>`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Value")
    for k, v in sorted(config.items()):
        table.add_row(k, str(v))
    console.print(table)


@relay_app.command("list")
def relay_list(
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to profile.json"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Show the current default relays (in polling order)."""
    format_ = resolve_format(format_)
    p = _load_profile_for_relay(profile)
    relays = list(p.default_relays)

    if format_ == OutputFormat.JSON:
        _output_json({"relays": relays, "count": len(relays)})
        return

    if not relays:
        console.print("[dim]No relays configured.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Relay URL")
    for i, url in enumerate(relays, start=1):
        table.add_row(str(i), url)
    console.print(table)


@relay_app.command("add")
def relay_add(
    url: str = typer.Argument(..., help="Relay URL (wss://… or ws://…)"),
    first: bool = typer.Option(
        False, "--first", help="Prepend instead of append (makes this the primary relay)"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to profile.json"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Add a relay to default_relays. Duplicates are a no-op."""
    format_ = resolve_format(format_)
    _validate_relay_url(url)
    p = _load_profile_for_relay(profile)

    # `--first` must reorder an already-present relay, not no-op: "make this
    # primary" is about polling order, which is what decides reachability.
    if not p.add_relay(url, first=first):
        relays = list(p.default_relays)
        if format_ == OutputFormat.JSON:
            _output_json({"ok": True, "already_present": True, "relays": relays})
            return
        console.print(f"[dim]{url} is already in default_relays — no change.[/dim]")
        return

    relays = list(p.default_relays)
    save_profile(p, profile)

    if format_ == OutputFormat.JSON:
        _output_json(
            {
                "ok": True,
                "added": url,
                "position": "first" if first else "last",
                "relays": relays,
            }
        )
        return
    role = "primary" if first else "fallback"
    console.print(f"[green]✓[/green] Added [cyan]{url}[/cyan] ({role})")
    console.print(f"[dim]Saved to {profile}[/dim]")


@relay_app.command("remove")
def relay_remove(
    target: str = typer.Argument(..., help="Relay URL or 1-based list index to remove"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow removing the last remaining relay. Note: load_profile() auto-refills an "
        "empty list with the bootstrap defaults on next load, so this effectively resets "
        "to defaults.",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to profile.json"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Remove a relay by URL or 1-based index."""
    format_ = resolve_format(format_)
    p = _load_profile_for_relay(profile)
    relays = list(p.default_relays)

    # Resolve target: integer index or URL match
    removed: str | None = None
    if target.isdigit():
        idx = int(target) - 1
        if idx < 0 or idx >= len(relays):
            _emit_error(
                ErrorCode.INVALID_ARGUMENT,
                f"Index {target} out of range (list has {len(relays)} relays).",
                context={"index": target, "count": len(relays)},
                exit_code=2,
            )
        removed = relays.pop(idx)
    elif target in relays:
        relays.remove(target)
        removed = target
    else:
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            f"Relay {target!r} not found in default_relays.",
            context={"target": target, "relays": list(p.default_relays)},
            exit_code=2,
        )

    if not relays and not force:
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            "Refusing to remove the last relay. Use --force to empty the list.",
            context={"removed": removed},
            exit_code=2,
        )

    p.default_relays = relays
    save_profile(p, profile)

    if format_ == OutputFormat.JSON:
        _output_json({"ok": True, "removed": removed, "relays": relays})
        return
    console.print(f"[green]✓[/green] Removed [cyan]{removed}[/cyan]")
    if not relays and force:
        console.print(
            "[yellow]⚠ default_relays was saved empty, but bootstrap defaults will be "
            "restored on the next profile load.[/yellow]"
        )
    console.print(f"[dim]Saved to {profile}[/dim]")


@relay_app.command("status")
def relay_status(
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to profile.json"),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Relay health check: identity, trusted peers, relays, last poll."""
    format_ = resolve_format(format_)
    p = _load_profile_for_relay(profile)

    # Resolve and validate the requested instance
    _local, instance_label = _resolve_instance_labelled(p, as_)

    # Trusted peers
    trusted_peers = [v.label for v in p.trusted_keys.values() if v.label]

    # Relay URLs
    relays = list(p.default_relays)

    # Last poll per relay
    last_checked: dict[str, str] = {}
    if p.last_checked:
        last_checked = {url: ts for url, ts in p.last_checked.items() if url in relays}

    if format_ == OutputFormat.JSON:
        _output_json(
            {
                "instance": instance_label,
                "trusted_peers": trusted_peers,
                "relays": relays,
                "last_checked": last_checked,
            }
        )
        return

    console.print(f"Instance:       {instance_label}")
    console.print("Trusted peers:  " + (", ".join(trusted_peers) if trusted_peers else "(none)"))
    console.print("Relays:         " + (", ".join(relays) if relays else "(none)"))
    if last_checked:
        for url, ts in last_checked.items():
            console.print(f"Last poll:      {url} → {ts}")
    else:
        console.print("Last poll:      (never)")
