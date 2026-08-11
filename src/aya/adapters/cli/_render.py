"""Rendering for the CLI.

Everything that turns a result into terminal output: the packet table, the
delivery block, the send/ack/receive panels. Separated from the kernel so a
renderer can be exercised with a constructed result instead of by driving a
whole command, and so the plumbing stays free of Rich.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, TypedDict

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aya.adapters.cli._kernel import _output_json, console, err
from aya.adapters.outbox import (
    delivery_summary,
)
from aya.entities.identity import (
    Profile,
)
from aya.entities.packet import Packet, human_age
from aya.usecases import relay_ops
from aya.usecases.packet_view import extract_body


def _render_send(result: relay_ops.SendResult, *, as_json: bool) -> None:
    """Present a completed send. Pure presentation."""
    if result.cached:
        if as_json:
            _output_json({"event_id": result.event_id, "cached": True})
        else:
            console.print(f"[dim]Already sent (cached) — event {result.event_id[:8]}[/dim]")
        return

    packet_id = result.packet.id if result.packet else ""
    if as_json:
        _output_json(
            {
                "packet_id": packet_id,
                "event_id": result.event_id,
                "relay": delivery_summary(result.relays_ok, result.attempted),
                "relays_ok": result.relays_ok,
                "relays_failed": result.relays_failed,
                "intent": result.packet.intent if result.packet else "",
            }
        )
        return

    console.print(
        Panel.fit(
            f"[bold green]✓ Sent[/bold green]\n\n"
            f"Intent:  [cyan]{result.packet.intent if result.packet else ''}[/cyan]\n"
            f"Packet:  [dim]{packet_id[:8]}[/dim]\n"
            f"Event:   [dim]{result.event_id[:8]}[/dim]\n"
            f"To:      [dim]{result.to_label}[/dim]\n\n"
            f"Delivery:\n{_render_delivery(result.relays_ok, result.relays_failed)}",
            title="aya — send",
        )
    )
    if result.partial:
        err.print(
            f"[yellow]Delivered to {len(result.relays_ok)} of {result.attempted} relay(s). "
            "If the peer polls only a failed relay, it will not see this packet.[/yellow]"
        )


def _render_ack(result: relay_ops.AckResult, message: str, *, as_json: bool) -> None:
    """Present a completed ack. Pure presentation."""
    if result.cached:
        if as_json:
            _output_json({"event_id": result.event_id, "cached": True})
        else:
            console.print(f"[dim]Already sent (cached) — ack {result.event_id[:8]}[/dim]")
        return

    if as_json:
        _output_json(
            {
                "packet_id": result.packet.id if result.packet else "",
                "event_id": result.event_id,
                "in_reply_to": result.in_reply_to,
                "to": result.to_label,
                "relays_ok": result.relays_ok,
                "relays_failed": result.relays_failed,
            }
        )
        return

    console.print(
        Panel.fit(
            f"[bold green]✓ ACK sent[/bold green]\n\n"
            f"In reply to: [dim]{result.in_reply_to[:8]}[/dim]\n"
            f"To:          [dim]{result.to_label}[/dim]\n"
            f"Message:     [cyan]{message}[/cyan]\n"
            f"Event:       [dim]{result.event_id[:8]}[/dim]\n\n"
            f"Delivery:\n{_render_delivery(result.relays_ok, result.relays_failed)}",
            title="aya — ack",
        )
    )
    if result.partial:
        err.print(
            f"[yellow]Delivered to {len(result.relays_ok)} of {result.attempted} relay(s).[/yellow]"
        )


def _render_receive(
    result: relay_ops.PollResult, *, as_json: bool, quiet: bool, auto_ingest: bool
) -> None:
    """Present a poll. Pure presentation — no relay or profile access."""
    if as_json:
        _output_json(result.envelope())
        return
    if quiet:
        return

    context = f" (as={result.instance}, relays={', '.join(result.relays)})"
    for packet in result.bad_signature:
        err.print(
            f"[red]⚠ Packet {packet.id[:8]} failed signature verification "
            f"(from {packet.from_did[:30]}…) — discarded[/red]"
        )
    if not result.relay_reachable:
        err.print(f"[yellow]Could not reach relay — skipping relay fetch.{context}[/yellow]")
        return
    if not result.packets:
        console.print(f"[dim]No pending packets.{context}[/dim]")
        return

    for summary in result.packets:
        if summary.get("skipped"):
            err.print(f"[dim]Skipped untrusted: {summary['id'][:8]} ({summary['intent']})[/dim]")

    if auto_ingest:
        ingested = sum(1 for s in result.packets if s.get("ingested"))
        skipped = sum(1 for s in result.packets if s.get("skipped"))
        total = len(result.packets)
        parts = [f"[green]✓[/green] Ingested {ingested} of {total} packet(s)"]
        if skipped:
            parts.append(f"({skipped} untrusted, skipped)")
        declined = total - ingested - skipped
        if declined:
            parts.append(f"({declined} declined)")
        console.print("  ".join(parts))


def _render_ingested(packet: Packet) -> None:
    """Draw an ingested packet. Lives in the surface layer; aya.ingest injects it."""
    from aya.usecases.ingest import is_seed, seed_fields

    console.print(f"\n[bold]Ingesting:[/bold] {packet.intent}")
    if is_seed(packet):
        seed = seed_fields(packet)
        questions = seed.get("open_questions") or []
        tail = (
            "[bold]Open questions:[/bold]\n" + "\n".join(f"  • {q}" for q in questions)
            if questions
            else ""
        )
        console.print(
            Panel(
                f"[bold]Opening question:[/bold]\n{seed.get('opener', '')}\n\n"
                f"[bold]Context:[/bold]\n{seed.get('context_summary', '')}\n\n" + tail,
                title="Conversation Seed",
                border_style="cyan",
            )
        )
    else:
        console.print(
            Panel(
                str(packet.content),
                title=packet.intent,
                subtitle=f"[dim]{packet.id[:8]} · {packet.sent_at[:10]}[/dim]",
            )
        )


def _render_delivery(relays_ok: list[str], relays_failed: list[dict[str, object]]) -> str:
    """One line per relay, so a partial delivery is visible rather than implied."""
    lines = [f"  [green]✓[/green] {url}" for url in relays_ok]
    lines += [
        f"  [red]✗[/red] {f['url']} [dim]({f.get('error') or 'failed'})[/dim]"
        for f in relays_failed
    ]
    return "\n".join(lines)


class PacketRow(TypedDict):
    """One packet as the displays need it — fields plus derived values.

    Typed rather than ``dict[str, object]`` so callers can index it without
    every value degrading to ``object``.
    """

    id: str
    intent: str
    from_did: str
    from_label: str | None
    sent_at: str
    age: str
    content_type: str
    trusted: bool


def _extract_packet_data(pkt: Packet, profile: Profile) -> PacketRow:
    """Extract all packet fields and computed values for reuse across displays."""
    return {
        "id": pkt.id,
        "intent": pkt.intent,
        "from_did": pkt.from_did,
        "from_label": _label_for_did(pkt.from_did, profile),
        "sent_at": pkt.sent_at,
        "age": human_age(pkt.sent_at),
        "content_type": str(pkt.content_type),
        "trusted": profile.is_trusted(pkt.from_did),
    }


def _packet_to_dict(
    pkt: Packet, profile: Profile, ingested_set: set[str] | None = None
) -> dict[str, Any]:
    """Packet as a JSON-ready dict, optionally marking ingested packets."""
    d: dict[str, Any] = dict(_extract_packet_data(pkt, profile))
    if ingested_set is not None:
        d["ingested"] = pkt.id in ingested_set
    return d


def _show_inbox(
    packets: list[Packet], profile: Profile, ingested_set: set[str] | None = None
) -> None:
    table = Table(title=f"Inbox — {len(packets)} packet(s)", show_lines=True)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Intent")
    table.add_column("From", style="cyan")
    table.add_column("Age", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Trust")

    for pkt in packets:
        data = _extract_packet_data(pkt, profile)
        trusted_display = "[green]✓[/green]" if data["trusted"] else "[yellow]?[/yellow]"
        already_ingested = ingested_set is not None and pkt.id in ingested_set
        if already_ingested:
            intent: str | Text = Text.assemble((data["intent"], "dim"), (" [ingested]", "dim"))
        else:
            intent = data["intent"]
        table.add_row(
            data["id"][:8],
            intent,
            data["from_label"],
            data["age"],
            data["content_type"],
            trusted_display,
        )
    console.print(table)


def _label_for_did(did: str, profile: Profile) -> str:
    for key in profile.trusted_keys.values():
        if key.did == did:
            return key.label
    return did[:20] + "…"


# Re-exported so CLI call sites keep the private name; the definition is shared
# with mcp_server via usecases.packet_view so the two surfaces cannot diverge.
_extract_body = extract_body


def _copy_to_clipboard(text: str) -> None:
    xclip = shutil.which("xclip")
    xsel = shutil.which("xsel")
    clip = shutil.which("clip.exe")
    if xclip:
        result = subprocess.run(  # noqa: S603
            [xclip, "-selection", "clipboard"], input=text.encode(), check=False
        )
        if result.returncode == 0:
            console.print("[dim]Copied to clipboard (xclip)[/dim]")
        else:
            err.print(f"[yellow]--copy: xclip failed (exit {result.returncode})[/yellow]")
    elif xsel:
        result = subprocess.run(  # noqa: S603
            [xsel, "--clipboard", "--input"], input=text.encode(), check=False
        )
        if result.returncode == 0:
            console.print("[dim]Copied to clipboard (xsel)[/dim]")
        else:
            err.print(f"[yellow]--copy: xsel failed (exit {result.returncode})[/yellow]")
    elif clip:
        result = subprocess.run([clip], input=text.encode(), check=False)  # noqa: S603
        if result.returncode == 0:
            console.print("[dim]Copied to clipboard (clip.exe)[/dim]")
        else:
            err.print(f"[yellow]--copy: clip.exe failed (exit {result.returncode})[/yellow]")
    else:
        err.print("[yellow]--copy: no clipboard tool found (xclip, xsel, clip.exe)[/yellow]")
