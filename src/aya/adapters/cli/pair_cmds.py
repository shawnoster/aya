"""Pairing two instances over the relay."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from aya.adapters.cli._kernel import (
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _emit_error,
    _load_profile,
    _output_json,
    _record_pairing,
    _resolve_instance,
    app,
    console,
    resolve_format,
)

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.adapters.error_map import describe
from aya.usecases.pair import (
    PairingError,
    generate_code,
    hash_code,
    join_pairing,
    poll_for_pair_response,
    publish_pair_request,
)

logger = logging.getLogger(__name__)


@app.command()
def pair(
    code: str = typer.Option(None, help="Pairing code from the other instance (joiner mode)"),
    peer: str = typer.Option(..., "--peer", help="Name for the remote peer"),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    relay: str = typer.Option(
        None, help="Pair over only this relay, replacing the profile list (no fallback)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show pairing intent without publishing"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Pair two instances with a short-lived code — no manual DID exchange."""
    format_ = resolve_format(format_)
    p = _load_profile(profile)
    local = _resolve_instance(p, as_)

    relay_urls = [relay] if relay else p.default_relays

    if dry_run:
        summary = {
            "action": "join_pairing" if code else "initiate_pairing",
            "local_did": local.did,
            "peer_label": peer,
            "relay": relay_urls[0] if relay_urls else None,
        }
        if code:
            summary["code"] = code
        _output_json(summary)
        raise typer.Exit(0)

    if code:
        # ── Joiner mode ──────────────────────────────────────────────
        try:
            result = asyncio.run(join_pairing(local, code, relay_urls))
        except PairingError as exc:
            # Through _emit_error: this printed straight to the console, so
            # `--format json` reported a pairing failure with no payload at all.
            described = describe(exc)
            code, detail, context = described or (ErrorCode.PAIR_FAILED, str(exc), {})
            _emit_error(code, detail, context)

        trusted = result.trusted
        promoted = _record_pairing(p, profile, peer, trusted, result.relay)

        if format_ == OutputFormat.JSON:
            _output_json(
                {
                    "status": "paired",
                    "peer_label": peer,
                    "peer_did": trusted.did,
                    "primary_relay": promoted,
                }
            )
            raise typer.Exit(0)

        lines = [
            "[bold green]✓ Paired![/bold green]\n",
            f"Trusted: [cyan]{peer}[/cyan]",
            (
                f"DID:     [dim]{trusted.did}[/dim]"
                "  [dim italic](ed25519 · identity & signing)[/dim italic]"
            ),
        ]
        if trusted.nostr_pubkey:
            lines.append(
                f"Nostr:   [dim]{trusted.nostr_pubkey[:16]}…[/dim]  "
                "[dim italic](secp256k1 · relay transport)[/dim italic]"
            )
        if promoted:
            lines.append(
                f"Relay:   [dim]{promoted}[/dim]  "
                "[dim italic](now primary — no --relay needed)[/dim italic]"
            )
        console.print(
            Panel.fit(
                "\n".join(lines),
                title="aya — pair (joined)",
            )
        )

    else:
        # ── Initiator mode ───────────────────────────────────────────
        pairing_code = generate_code()
        code_h = hash_code(pairing_code)

        # Publish the request — embed our own label so the joiner knows what to call us
        if format_ != OutputFormat.JSON:
            console.print("[dim]Publishing pairing request…[/dim]")
        request_event_id = asyncio.run(publish_pair_request(local, local.label, code_h, relay_urls))

        # Show the code — user reads this aloud or types it on the other machine
        if format_ == OutputFormat.JSON:
            _output_json(
                {
                    "status": "awaiting_peer",
                    "pairing_code": pairing_code,
                    "local_did": local.did,
                    "peer_label": peer,
                    "relay": relay_urls[0] if relay_urls else None,
                }
            )
        if format_ != OutputFormat.JSON:
            console.print(
                Panel.fit(
                    f"[bold]Pairing code:[/bold]  [bold cyan]{pairing_code}[/bold cyan]\n\n"
                    "Enter this on your other machine:\n"
                    f"  [dim]aya pair --code {pairing_code}"
                    " --peer <their-name> --as <local-identity>[/dim]\n\n"
                    "[dim]Expires in 10 minutes.[/dim]",
                    title="aya — pair",
                )
            )

        # Poll for response
        ctx_mgr: AbstractContextManager[Any] = (
            console.status("[bold cyan]Waiting for the other peer…[/bold cyan]")
            if format_ != OutputFormat.JSON
            else nullcontext()
        )
        with ctx_mgr:
            result_or_none = asyncio.run(
                poll_for_pair_response(relay_urls, local.nostr_public_hex, request_event_id)
            )

        if result_or_none is None:
            if format_ == OutputFormat.JSON:
                _emit_error(ErrorCode.PAIR_TIMEOUT, "Pairing timed out")
            console.print(
                "[bold yellow]Pairing timed out.[/bold yellow] "
                "Run [bold]aya pair[/bold] again for a new code."
            )
            raise typer.Exit(1)

        trusted = result_or_none.trusted
        promoted = _record_pairing(p, profile, peer, trusted, result_or_none.relay)

        if format_ == OutputFormat.JSON:
            _output_json(
                {
                    "status": "paired",
                    "peer_label": peer,
                    "peer_did": trusted.did,
                    "primary_relay": promoted,
                }
            )
            raise typer.Exit(0)

        lines = [
            "[bold green]✓ Paired![/bold green]\n",
            f"Trusted: [cyan]{peer}[/cyan]",
            (
                f"DID:     [dim]{trusted.did}[/dim]"
                "  [dim italic](ed25519 · identity & signing)[/dim italic]"
            ),
        ]
        if trusted.nostr_pubkey:
            lines.append(
                f"Nostr:   [dim]{trusted.nostr_pubkey[:16]}…[/dim]  "
                "[dim italic](secp256k1 · relay transport)[/dim italic]"
            )
        if promoted:
            lines.append(
                f"Relay:   [dim]{promoted}[/dim]  "
                "[dim italic](now primary — no --relay needed)[/dim italic]"
            )
        console.print(
            Panel.fit(
                "\n".join(lines),
                title="aya — pair (complete)",
            )
        )
