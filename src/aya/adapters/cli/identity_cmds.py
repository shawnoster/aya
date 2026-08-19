"""Identity and setup: version, whoami, use, init, trust, mcp-server."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.panel import Panel

from aya import __version__
from aya.adapters.cli._kernel import (
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _emit_error,
    _load_profile,
    _output_json,
    app,
    console,
    resolve_format,
)
from aya.adapters.profile_store import load_profile, save_profile

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.identity import (
    Identity,
    InstanceResolutionError,
    Profile,
    TrustedKey,
)

logger = logging.getLogger(__name__)


@app.command()
def version(
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Show the installed aya version."""
    format_ = resolve_format(format_)
    if format_ == OutputFormat.JSON:
        _output_json({"version": __version__})
    else:
        console.print(f"aya {__version__}")


@app.command()
def whoami(
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Show which local identity commands act as, and every registered peer."""
    format_ = resolve_format(format_)
    p = _load_profile(profile)

    try:
        active, reason = p.resolve_instance_name(None)
    except InstanceResolutionError as exc:
        active, reason = None, f"ambiguous — {exc}"

    instances = [
        {
            "label": label,
            "did": ident.did,
            "nostr_pubkey": ident.nostr_public_hex,
            "active": label == active,
        }
        for label, ident in p.instances.items()
    ]
    peers = [
        {"label": label, "did": tk.did, "paired": bool(tk.nostr_pubkey)}
        for label, tk in p.trusted_keys.items()
    ]

    if format_ == OutputFormat.JSON:
        _output_json(
            {
                "active_instance": active,
                "resolved_by": reason,
                "primary_instance": p.primary_instance,
                "instances": instances,
                "peers": peers,
                "relays": list(p.default_relays),
            }
        )
        return

    console.print(f"Active identity: {active or '(ambiguous)'}  [dim]({reason})[/dim]")
    console.print("\nInstances:")
    for inst in instances:
        marker = "*" if inst["active"] else " "
        console.print(f"  {marker} {inst['label']}  [dim]{str(inst['did'])[:32]}…[/dim]")
    console.print("\nPeers you can --to:")
    if peers:
        for peer in peers:
            state = "paired" if peer["paired"] else "[yellow]not paired[/yellow]"
            console.print(f"    {peer['label']}  [dim]{str(peer['did'])[:32]}…[/dim]  {state}")
    else:
        console.print("    [dim](none — run 'aya pair --peer <label>')[/dim]")
    console.print("\nRelays: " + (", ".join(p.default_relays) or "(none)"))


@app.command()
def use(
    label: str = typer.Argument(..., help="Instance label to act as by default"),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Set the local identity that commands use when --as is omitted."""
    format_ = resolve_format(format_)
    p = _load_profile(profile)
    if label not in p.instances:
        _emit_error(
            ErrorCode.INSTANCE_NOT_FOUND,
            f"Instance '{label}' not found. Available: {', '.join(p.instances)}.",
            {"instance": label, "available": list(p.instances)},
        )
    p.primary_instance = label
    save_profile(p, profile)
    if format_ == OutputFormat.JSON:
        _output_json({"primary_instance": label})
    else:
        console.print(f"[green]✓[/green] Now acting as [cyan]{label}[/cyan] by default.")


@app.command("mcp-server")
def mcp_server_cmd() -> None:
    """Start the MCP server (stdio transport) for AI tool integration."""
    from aya.adapters.mcp_server import main as mcp_main

    asyncio.run(mcp_main())


@app.command()
def init(
    label: str = typer.Option("default", help="Label for this instance (work, home, laptop…)"),
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to profile.json"),
    relay: str | None = typer.Option(
        None,
        help=(
            "Seed this relay as the only one, dropping both public defaults "
            "(omit to keep the built-in two-relay default)"
        ),
    ),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Generate a keypair for this instance and register it in your profile."""
    format_ = resolve_format(format_)
    identity = Identity.generate(label)

    if profile.exists():
        p = load_profile(profile)
    else:
        profile.parent.mkdir(parents=True, exist_ok=True)
        p = Profile()

    p.instances[label] = identity
    if relay is not None:
        p.default_relays = [relay]
    save_profile(p, profile)

    if format_ == OutputFormat.JSON:
        _output_json({"profile_path": str(profile), "did": identity.did, "instance": label})
        raise typer.Exit(0)

    relay_display = relay or ", ".join(p.default_relays)
    console.print(
        Panel.fit(
            f"[bold green]✓ Instance created[/bold green]\n\n"
            f"Instance: [cyan]{label}[/cyan]\n"
            f"DID:      [dim]{identity.did}[/dim]  "
            "[dim italic](ed25519 · identity & signing)[/dim italic]\n"
            f"Nostr:    [dim]{identity.nostr_public_hex[:16]}…[/dim]  "
            "[dim italic](secp256k1 · relay transport)[/dim italic]\n"
            f"Relay:    [cyan]{relay_display}[/cyan]\n\n"
            "[dim]Share your DID with other instances you want to trust.[/dim]\n\n"
            "[bold]Next steps:[/bold]\n"
            "  [cyan]aya schedule install[/cyan]    Set up hooks and cron\n"
            "  [cyan]aya pair --peer <name>[/cyan]  Connect to another instance",
            title="aya — init",
        )
    )


@app.command()
def trust(
    did: str = typer.Argument(help="DID to trust (did:key:z6Mk…)"),
    peer: str = typer.Option(..., "--peer", help="Name for the remote peer"),
    nostr_pubkey: str = typer.Option(
        None,
        help="Nostr pubkey hex (required for send/receive; pairing fills this automatically)",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Add a DID to your trusted keys list."""
    format_ = resolve_format(format_)
    p = _load_profile(profile)
    p.trusted_keys[peer] = TrustedKey(
        did=did,
        label=peer,
        nostr_pubkey=nostr_pubkey,
    )
    save_profile(p, profile)

    if format_ == OutputFormat.JSON:
        _output_json({"did": did, "label": peer, "nostr_pubkey": nostr_pubkey or None})
        raise typer.Exit(0)

    console.print(
        f"[green]✓[/green] Trusted: [cyan]{peer}[/cyan]  [dim]{did}[/dim]  "
        f"[dim italic](ed25519 · identity & signing)[/dim italic]"
    )
    if not nostr_pubkey:
        console.print(
            "[dim]Note: No Nostr pubkey provided. "
            "Use --nostr-pubkey or pair to enable relay delivery.[/dim]"
        )
