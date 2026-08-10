"""Inbound: receive and inbox."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import typer

from aya.adapters.cli._kernel import (
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _emit_error,
    _load_profile,
    _output_json,
    app,
    console,
    err,
    resolve_format,
)
from aya.adapters.cli._render import (
    _render_receive,
    _show_inbox,
)
from aya.adapters.profile_store import save_profile

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.identity import (
    InstanceResolutionError,
)
from aya.entities.packet import Packet
from aya.usecases import relay_ops

logger = logging.getLogger(__name__)


@app.command()
def receive(
    relay: str = typer.Option(None),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    auto_ingest: bool = typer.Option(False, help="Ingest all trusted packets without prompting"),
    skip_untrusted: bool = typer.Option(
        False,
        "--skip-untrusted",
        help="Skip untrusted packets silently (use with --auto-ingest)",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-confirm all prompts (non-interactive mode)"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress output when inbox is empty (for startup hooks)"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Poll for pending packets and surface them for review."""
    if skip_untrusted and not auto_ingest and not yes:
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            "--skip-untrusted requires --auto-ingest or --yes for non-interactive use.",
            exit_code=2,
        )
    format_ = resolve_format(format_)
    as_json = format_ == OutputFormat.JSON

    async def _run() -> None:
        p = _load_profile(profile)

        def decide(packet: Packet, trusted: bool) -> relay_ops.Decision:
            """Turn this command's flags into a per-packet decision."""
            if auto_ingest and trusted:
                return relay_ops.Decision.INGEST
            if skip_untrusted and not trusted:
                logger.debug("Skipping untrusted packet %s", packet.id[:8])
                return relay_ops.Decision.SKIP_UNTRUSTED
            if yes:
                return relay_ops.Decision.INGEST
            # typer.confirm has no non-interactive fallback — without a TTY it
            # aborts mid-poll, which reads as a crash rather than a missing flag.
            if not sys.stdin.isatty():
                save_profile(p, profile)
                _emit_error(
                    ErrorCode.INVALID_ARGUMENT,
                    "Packet(s) need confirmation but there is no terminal. "
                    "Re-run with --auto-ingest (trusted senders only) or --yes (all senders).",
                    {"instance": as_},
                    exit_code=2,
                )
            trust_label = "[green]trusted[/green]" if trusted else "[yellow]unknown sender[/yellow]"
            confirmed = typer.confirm(
                f"\nIngest '{packet.intent}' ({trust_label})?", default=trusted
            )
            return relay_ops.Decision.INGEST if confirmed else relay_ops.Decision.DECLINE

        def show_batch(packets: list[Packet]) -> None:
            if not as_json:
                _show_inbox(packets, p)

        try:
            result = await relay_ops.receive(
                p,
                profile,
                instance=as_,
                relay=relay,
                decide=decide,
                on_fresh=None if quiet else show_batch,
            )
        except InstanceResolutionError as exc:
            if not quiet:
                _emit_error(
                    ErrorCode.INSTANCE_NOT_FOUND,
                    str(exc),
                    {"instance": as_, "available": exc.available},
                )
            raise typer.Exit(1) from None

        _render_receive(result, as_json=as_json, quiet=quiet, auto_ingest=auto_ingest)

    asyncio.run(_run())


@app.command()
def inbox(
    relay: str = typer.Option(None),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
    show_all: bool = typer.Option(
        False, "--all", help="Show all packets including already-ingested ones"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """List pending packets without ingesting."""
    format_ = resolve_format(format_)

    async def _run() -> None:
        p = _load_profile(profile)
        try:
            result, packets = await relay_ops.inbox(
                p,
                instance=as_,
                relay=relay,
                include_ingested=show_all,
            )
        except InstanceResolutionError as exc:
            _emit_error(
                ErrorCode.INSTANCE_NOT_FOUND,
                str(exc),
                {"instance": as_, "available": exc.available},
            )
            return

        context_suffix = f" (as={result.instance}, relays={', '.join(result.relays)})"
        if format_ == OutputFormat.JSON:
            _output_json(result.envelope())
            return

        if not result.relay_reachable:
            err.print(f"[yellow]Could not reach relay.{context_suffix}[/yellow]")
        if not packets:
            console.print(f"[dim]Inbox empty.{context_suffix}[/dim]")
            return

        ingested_set = {entry["id"] for entry in p.ingested_ids} if show_all else None
        _show_inbox(packets, p, ingested_set)
        if show_all:
            new = sum(1 for pkt in packets if pkt.id not in (ingested_set or set()))
            if new != len(packets):
                console.print(f"[dim]{len(packets)} total, {new} new[/dim]")

    asyncio.run(_run())
