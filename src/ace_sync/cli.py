"""CLI entry point — ace-sync command."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ace_sync.identity import Identity, Profile
from ace_sync.packet import ConflictStrategy, ContentType, Packet
from ace_sync.relay import RelayClient

app = typer.Typer(
    name="ace-sync",
    help="Async knowledge packets between your AI assistant instances.",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)

DEFAULT_PROFILE = Path.home() / ".copilot" / "assistant_profile.json"


def _load_profile(profile_path: Path) -> Profile:
    if not profile_path.exists():
        err.print(
            f"[red]Profile not found at {profile_path}.[/red]\n"
            "Run [bold]ace-sync init[/bold] first."
        )
        raise typer.Exit(1)
    return Profile.load(profile_path)


# ── init ─────────────────────────────────────────────────────────────────────


@app.command()
def init(
    label: str = typer.Option("default", help="Label for this instance (work, home, laptop…)"),
    profile: Path = typer.Option(DEFAULT_PROFILE, help="Path to assistant_profile.json"),
    relay: str = typer.Option("wss://relay.damus.io", help="Default Nostr relay URL"),
) -> None:
    """Generate a keypair for this instance and register it in your profile."""
    identity = Identity.generate(label)

    if profile.exists():
        p = Profile.load(profile)
    else:
        profile.parent.mkdir(parents=True, exist_ok=True)
        p = Profile(alias="Ace", ship_mind_name="", user_name="")

    p.instances[label] = identity
    p.default_relay = relay
    p.save(profile)

    console.print(Panel.fit(
        f"[bold green]✓ Instance created[/bold green]\n\n"
        f"Label:  [cyan]{label}[/cyan]\n"
        f"DID:    [dim]{identity.did}[/dim]\n"
        f"Relay:  [cyan]{relay}[/cyan]\n\n"
        "[dim]Share your DID with other instances you want to trust.[/dim]",
        title="Ace Sync — init",
    ))


# ── trust ─────────────────────────────────────────────────────────────────────


@app.command()
def trust(
    did: str = typer.Argument(help="DID to trust (did:key:z6Mk…)"),
    label: str = typer.Option(..., help="Human label for this key (home, friend:alice)"),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """Add a DID to your trusted keys list."""
    from ace_sync.identity import TrustedKey
    from ace_sync.relay import _did_to_pubkey

    p = _load_profile(profile)
    p.trusted_keys[label] = TrustedKey(
        did=did,
        label=label,
        nostr_pubkey=_did_to_pubkey(did),
    )
    p.save(profile)
    console.print(f"[green]✓[/green] Trusted: [cyan]{label}[/cyan]  [dim]{did}[/dim]")


# ── pack ──────────────────────────────────────────────────────────────────────


@app.command()
def pack(
    to: str = typer.Option(..., help="Recipient label (home) or DID"),
    intent: str = typer.Option(..., help="What is this packet and why"),
    files: list[Path] = typer.Option([], help="Files to include"),
    context: str = typer.Option(None, help="Annotation for the receiving assistant"),
    seed: bool = typer.Option(False, help="Create a conversation seed instead of content"),
    opener: str = typer.Option(None, help="[seed] Opening question for the receiving assistant"),
    out: Path = typer.Option(None, help="Write packet JSON to file (default: stdout)"),
    instance: str = typer.Option("default", help="Which local instance to send from"),
    conflict: ConflictStrategy = typer.Option(
        ConflictStrategy.LAST_WRITE_WINS, help="Conflict resolution strategy"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """Pack a knowledge packet ready to send."""
    p = _load_profile(profile)
    local = p.instances.get(instance)
    if not local:
        err.print(f"[red]Instance '{instance}' not found. Run ace-sync init.[/red]")
        raise typer.Exit(1)

    # Resolve recipient DID
    to_did = _resolve_did(to, p)

    if seed:
        if not opener:
            err.print("[red]--opener required for seed packets.[/red]")
            raise typer.Exit(1)
        packet = Packet.as_seed(
            from_did=local.did,
            to_did=to_did,
            intent=intent,
            opener=opener,
            context_summary=context or "",
        )
    elif files:
        packet = Packet.from_files(
            paths=[str(f) for f in files],
            from_did=local.did,
            to_did=to_did,
            intent=intent,
            context=context,
        )
    else:
        content = sys.stdin.read()
        packet = Packet(
            **{"from": local.did, "to": to_did},
            intent=intent,
            context=context,
            content_type=ContentType.MARKDOWN,
            content=content,
            conflict_strategy=conflict,
        )

    signed = packet.sign(local)
    json_output = signed.to_json()

    if out:
        out.write_text(json_output)
        console.print(f"[green]✓[/green] Packet written to [cyan]{out}[/cyan]")
    else:
        print(json_output)


# ── send ──────────────────────────────────────────────────────────────────────


@app.command()
def send(
    packet_file: Path = typer.Argument(help="Packet JSON file to send"),
    relay: str = typer.Option(None, help="Relay URL (overrides profile default)"),
    instance: str = typer.Option("default"),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """Send a packet to a Nostr relay."""
    p = _load_profile(profile)
    local = p.instances.get(instance)
    if not local:
        err.print(f"[red]Instance '{instance}' not found.[/red]")
        raise typer.Exit(1)

    relay_url = relay or p.default_relay
    packet = Packet.from_json(packet_file.read_text())
    client = RelayClient(relay_url, local.private_key_hex, local.public_key_hex)

    event_id = asyncio.run(client.publish(packet))
    console.print(
        f"[green]✓[/green] Sent [cyan]{packet.intent}[/cyan]\n"
        f"  Packet: [dim]{packet.id[:8]}[/dim]  "
        f"Event: [dim]{event_id[:8]}[/dim]  "
        f"Relay: [dim]{relay_url}[/dim]"
    )


# ── receive ───────────────────────────────────────────────────────────────────


@app.command()
def receive(
    relay: str = typer.Option(None),
    instance: str = typer.Option("default"),
    auto_ingest: bool = typer.Option(False, help="Ingest all trusted packets without prompting"),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """Poll for pending packets and surface them for review."""

    async def _run() -> None:
        p = _load_profile(profile)
        local = p.instances.get(instance)
        if not local:
            err.print(f"[red]Instance '{instance}' not found.[/red]")
            raise typer.Exit(1)

        relay_url = relay or p.default_relay
        client = RelayClient(relay_url, local.private_key_hex, local.public_key_hex)

        packets: list[Packet] = []
        async for packet in client.fetch_pending():
            packets.append(packet)

        if not packets:
            console.print("[dim]No pending packets.[/dim]")
            return

        _show_inbox(packets, p)

        for packet in packets:
            trusted = p.is_trusted(packet.from_did)
            trust_label = "[green]trusted[/green]" if trusted else "[yellow]unknown sender[/yellow]"

            if auto_ingest and trusted:
                _ingest(packet)
                continue

            ingest = typer.confirm(
                f"\nIngest '{packet.intent}' ({trust_label})?",
                default=trusted,
            )
            if ingest:
                _ingest(packet)
                await client.send_receipt(packet)

    asyncio.run(_run())


# ── inbox ─────────────────────────────────────────────────────────────────────


@app.command()
def inbox(
    relay: str = typer.Option(None),
    instance: str = typer.Option("default"),
    profile: Path = typer.Option(DEFAULT_PROFILE),
) -> None:
    """List pending packets without ingesting."""

    async def _run() -> None:
        p = _load_profile(profile)
        local = p.instances.get(instance)
        if not local:
            err.print(f"[red]Instance '{instance}' not found.[/red]")
            raise typer.Exit(1)

        relay_url = relay or p.default_relay
        client = RelayClient(relay_url, local.private_key_hex, local.public_key_hex)

        packets = [pkt async for pkt in client.fetch_pending()]
        if not packets:
            console.print("[dim]Inbox empty.[/dim]")
        else:
            _show_inbox(packets, p)

    asyncio.run(_run())


# ── helpers ───────────────────────────────────────────────────────────────────


def _resolve_did(to: str, profile: Profile) -> str:
    """Resolve a label ('home') or raw DID to a DID string."""
    if to.startswith("did:"):
        return to
    key = profile.trusted_keys.get(to)
    if not key:
        err.print(
            f"[red]Unknown recipient '{to}'.[/red]\n"
            "Use a full DID or add with [bold]ace-sync trust[/bold]."
        )
        raise typer.Exit(1)
    return key.did


def _show_inbox(packets: list[Packet], profile: Profile) -> None:
    table = Table(title=f"Inbox — {len(packets)} packet(s)", show_lines=True)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Intent")
    table.add_column("From", style="cyan")
    table.add_column("Age", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Trust")

    for pkt in packets:
        from_label = _label_for_did(pkt.from_did, profile)
        trusted = "[green]✓[/green]" if profile.is_trusted(pkt.from_did) else "[yellow]?[/yellow]"
        from ace_sync.packet import _human_age
        table.add_row(
            pkt.id[:8],
            pkt.intent,
            from_label,
            _human_age(pkt.sent_at),
            pkt.content_type,
            trusted,
        )
    console.print(table)


def _label_for_did(did: str, profile: Profile) -> str:
    for key in profile.trusted_keys.values():
        if key.did == did:
            return key.label
    return did[:20] + "…"


def _ingest(packet: Packet) -> None:
    """
    Ingest a packet into the active assistant context.
    In Phase 1 this prints to stdout for the assistant to pick up.
    Phase 3+ will pipe directly into the Claude session context.
    """
    console.print(f"\n[bold]Ingesting:[/bold] {packet.intent}")

    if packet.content_type == "application/ace-seed":
        seed = packet.content if isinstance(packet.content, dict) else {}
        console.print(Panel(
            f"[bold]Opening question:[/bold]\n{seed.get('opener', '')}\n\n"
            f"[bold]Context:[/bold]\n{seed.get('context_summary', '')}\n\n"
            + (
                "[bold]Open questions:[/bold]\n"
                + "\n".join(f"  • {q}" for q in seed.get("open_questions", []))
                if seed.get("open_questions") else ""
            ),
            title="Conversation Seed",
            border_style="cyan",
        ))
    else:
        console.print(Panel(
            str(packet.content),
            title=packet.intent,
            subtitle=f"[dim]{packet.id[:8]} · {packet.sent_at[:10]}[/dim]",
        ))
