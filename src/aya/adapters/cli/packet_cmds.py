"""The local packet store: read, drop, sent, packets."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aya.adapters import relay as _relay
from aya.adapters.cli._kernel import (
    _RELAY_FETCH_TIMEOUT_SECONDS,
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _emit_error,
    _load_profile,
    _output_json,
    _resolve_instance,
    app,
    console,
    resolve_format,
)
from aya.adapters.cli._render import (
    _extract_body,
)
from aya.adapters.outbox import (
    NOT_INGESTED_HINT,
)
from aya.adapters.profile_store import save_profile
from aya.adapters.relay import RelayUnreachableError

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.packet import Packet
from aya.usecases.packet_view import read_view

logger = logging.getLogger(__name__)


@app.command()
def read(
    packet_id: str = typer.Argument(help="Packet ID or prefix (min 8 chars)"),
    meta: bool = typer.Option(False, "--meta", help="Also print packet metadata header"),
    panel: bool = typer.Option(
        False, "--panel", help="Render the body in a boxed Rich panel with title/subtitle"
    ),
    format_: OutputFormat = typer.Option(OutputFormat.AUTO, "--format", "-f", help="Output format"),
) -> None:
    """Read a previously ingested packet — extracts body without dumping the envelope JSON.

    The packet must already be ingested. IDs listed by 'aya inbox' are still
    pending and are not readable until 'aya receive' ingests them. The usual
    order is 'aya receive --auto-ingest' then 'aya read <id>'.

    Takes no --as: ingested packets are stored per-machine, not per-identity,
    so every local instance reads the same store.

    For seed packets, prints the opener (and context_summary, open_questions
    if present). For content packets, prints the content directly. Use
    ``--meta`` to also print id/from/sent_at/intent header, or ``--panel`` to
    render the body in a boxed display. ``--panel`` is ignored under
    ``--format json``.
    """
    from aya.adapters.paths import PACKETS_DIR

    format_ = resolve_format(format_)

    if len(packet_id) < 8:
        _emit_error(ErrorCode.INVALID_ARGUMENT, "Packet ID prefix must be at least 8 characters.")

    if not PACKETS_DIR.exists():
        _emit_error(ErrorCode.PACKET_NOT_FOUND, NOT_INGESTED_HINT.format(packet_id=packet_id))

    matches = [f for f in PACKETS_DIR.glob("*.json") if f.stem.startswith(packet_id)]
    if not matches:
        _emit_error(
            ErrorCode.PACKET_NOT_FOUND,
            NOT_INGESTED_HINT.format(packet_id=packet_id),
            {"packet_id": packet_id, "remedy": "aya receive --auto-ingest"},
        )
    if len(matches) > 1:
        _emit_error(
            ErrorCode.AMBIGUOUS_PREFIX,
            f"Ambiguous prefix — matches {len(matches)} packets.",
            {"packet_id": packet_id, "matches": len(matches)},
        )

    packet = Packet.from_json(matches[0].read_text())

    if format_ == OutputFormat.JSON:
        # Shape lives in usecases.packet_view so `aya_read` over MCP answers
        # with the same keys. Non-seed dict content is passed through as a real
        # object rather than stringified, so `jq` over the output gets a value
        # and not a string of pretty-printed JSON.
        _output_json(read_view(packet, meta=meta))
        raise typer.Exit(0)

    # Text mode — always render as a string via _extract_body.
    body = _extract_body(packet.content, packet.content_type)
    if panel:
        # Wrap in Text() so packet bodies containing `[...]` sequences are
        # not interpreted as Rich markup. Mirrors the non-panel path's
        # markup=False / highlight=False behaviour.
        console.print(
            Panel(
                Text(body),
                title=f"{packet.intent}  ·  {packet.id[:8]}",
                subtitle=f"from {packet.from_did[:30]}…  ·  {packet.sent_at[:10]}",
            )
        )
        return
    if meta:
        console.print(f"[bold]{packet.intent}[/bold]  ·  {packet.id[:12]}")
        console.print(f"[dim]from {packet.from_did[:30]}…  ·  {packet.sent_at[:16]}[/dim]")
        console.print()
    console.print(body, markup=False, highlight=False)


@app.command()
def drop(
    packet_id: str = typer.Argument(help="Packet ID or prefix (min 8 chars) to drop from inbox"),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    relay: str | None = typer.Option(
        None, help="Use only this relay, replacing the profile list (no fallback)"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(OutputFormat.AUTO, "--format", "-f", help="Output format"),
) -> None:
    """Drop a packet from inbox view so it stops re-surfacing on each poll.

    Useful for bad-signature packets, spam, or any packet you want to ignore
    permanently. The drop is local to this profile — the packet stays on the
    relay until its natural expiry. Prefix matching resolves the full ID by
    looking at ingested packets first, then querying the relay if needed.
    """
    format_ = resolve_format(format_)

    if len(packet_id) < 8:
        _emit_error(ErrorCode.INVALID_ARGUMENT, "Packet ID prefix must be at least 8 characters.")

    async def _run() -> None:
        p = _load_profile(profile)
        local = _resolve_instance(p, as_)

        # Try to resolve full ID from ingested_ids first (cheap, no network).
        ingested_matches = [
            entry["id"] for entry in p.ingested_ids if entry["id"].startswith(packet_id)
        ]

        # Also check existing dropped_ids so the user can re-confirm a drop
        # using a prefix without hitting the relay.
        dropped_matches = [pid for pid in p.dropped_ids if pid.startswith(packet_id)]

        local_matches = list(set(ingested_matches + dropped_matches))

        if len(local_matches) == 1:
            full_id = local_matches[0]
        elif len(local_matches) > 1:
            _emit_error(
                ErrorCode.AMBIGUOUS_PREFIX,
                f"Ambiguous prefix '{packet_id}' — matches {len(local_matches)} known packets.",
                {"packet_id": packet_id, "matches": len(local_matches)},
            )
            return  # unreachable, _emit_error raises
        else:
            # Fall back to the relay for packets that were never ingested
            # (bad-sig, spam, untrusted senders that aya skipped). Wrap
            # the stream in asyncio.timeout() so a slow or large relay
            # can't wedge the command indefinitely — after
            # _RELAY_FETCH_TIMEOUT_SECONDS we abandon the fetch and
            # report RELAY_TIMEOUT so the caller can retry with a full
            # ID or a different --relay.
            relay_urls = [relay] if relay else p.default_relays
            client = _relay.RelayClient(relay_urls, local.nostr_private_hex, local.nostr_public_hex)
            relay_matches: list[str] = []
            try:
                async with asyncio.timeout(_RELAY_FETCH_TIMEOUT_SECONDS):
                    async for pkt in client.fetch_pending():
                        if pkt.id.startswith(packet_id):
                            relay_matches.append(pkt.id)
                            if len(relay_matches) > 1:
                                break  # ambiguous — stop early
            except TimeoutError:
                _emit_error(
                    ErrorCode.RELAY_TIMEOUT,
                    (
                        f"Relay fetch timed out after {_RELAY_FETCH_TIMEOUT_SECONDS}s "
                        f"while resolving prefix '{packet_id}'. The relay may be slow "
                        f"or the inbox very large — retry with the full packet ID, "
                        f"or use --relay to point at a different relay."
                    ),
                    {
                        "packet_id": packet_id,
                        "timeout_seconds": _RELAY_FETCH_TIMEOUT_SECONDS,
                    },
                )
                return  # unreachable
            except RelayUnreachableError:
                _emit_error(
                    ErrorCode.RELAY_UNREACHABLE,
                    (
                        f"Could not connect to relay while resolving prefix '{packet_id}'. "
                        "Check your network connection or use --relay to point at a "
                        "different relay."
                    ),
                    {"packet_id": packet_id},
                )
                return  # unreachable

            if not relay_matches:
                _emit_error(
                    ErrorCode.PACKET_NOT_FOUND,
                    f"No packet matching '{packet_id}' found locally or on relay. "
                    "Use the full packet ID if it's already past relay retention.",
                    {"packet_id": packet_id},
                )
                return  # unreachable
            if len(relay_matches) > 1:
                _emit_error(
                    ErrorCode.AMBIGUOUS_PREFIX,
                    f"Ambiguous prefix '{packet_id}' — matches {len(relay_matches)} relay packets.",
                    {"packet_id": packet_id, "matches": len(relay_matches)},
                )
                return  # unreachable

            full_id = relay_matches[0]

        already_dropped = full_id in p.dropped_ids
        if not already_dropped:
            p.dropped_ids.append(full_id)
            save_profile(p, profile)

        if format_ == OutputFormat.JSON:
            _output_json(
                {
                    "dropped": full_id,
                    "already_dropped": already_dropped,
                }
            )
        else:
            if already_dropped:
                console.print(f"[dim]Packet[/dim] {full_id[:12]}… [dim]was already dropped.[/dim]")
            else:
                console.print(f"[green]Dropped[/green] {full_id[:12]}…")

    asyncio.run(_run())


@app.command()
def sent(
    limit: int = typer.Option(20, "--limit", "-n", help="Max packets to show"),
    failed_only: bool = typer.Option(
        False, "--failed", help="Show only packets that some relay rejected"
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(OutputFormat.AUTO, "--format", "-f", help="Output format"),
) -> None:
    """List packets this instance has sent, with per-relay delivery status.

    The counterpart to 'aya inbox'. 'aya packets' lists received packets
    only; this is the outbound log. Entries are kept for 7 days.

    A packet with entries under relays_failed was accepted by at least one
    relay ('aya send' succeeds if any relay takes it) but rejected by others.
    If the peer polls only a rejected relay, it will never see the packet.
    """
    format_ = resolve_format(format_)
    if limit < 1:
        limit = 20
    p = _load_profile(profile)

    entries = list(reversed(p.sent_ids))
    if failed_only:
        entries = [e for e in entries if e.get("relays_failed")]
    entries = entries[:limit]

    if format_ == OutputFormat.JSON:
        _output_json({"packets": entries})
        return

    if not entries:
        console.print(
            "[dim]No sent packets.[/dim]"
            if not failed_only
            else "[dim]No sent packets with relay failures.[/dim]"
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("To")
    table.add_column("Intent")
    table.add_column("Sent")
    table.add_column("Delivery")
    for e in entries:
        ok = e.get("relays_ok") or []
        failed = e.get("relays_failed") or []
        if failed:
            delivery = f"[yellow]{len(ok)}/{len(ok) + len(failed)} relays[/yellow]"
        else:
            delivery = f"[green]{len(ok)}/{len(ok)} relays[/green]"
        table.add_row(
            str(e.get("id", ""))[:8],
            str(e.get("to_label") or e.get("to_did", ""))[:20],
            str(e.get("intent", ""))[:40],
            str(e.get("sent_at", ""))[:19],
            delivery,
        )
    console.print(table)
    partial = [e for e in entries if e.get("relays_failed")]
    if partial:
        console.print(
            f"[yellow]{len(partial)} packet(s) reached only some relays — "
            "run with --format json to see which.[/yellow]"
        )


@app.command()
def packets(
    limit: int = typer.Option(20, "--limit", "-n", help="Max packets to show"),
    format_: OutputFormat = typer.Option(OutputFormat.AUTO, "--format", "-f", help="Output format"),
) -> None:
    """List packets stored on this machine, newest first.

    Both directions appear: packets you received, and your own sent ones, whose
    bodies are kept so 'aya read' works on them too. The "From" column tells
    them apart. For per-relay delivery status of what you sent, use 'aya sent'.

    Ordering is by local write time, not sent_at, so a batch ingested in one
    poll shares an order unrelated to when the peer sent it.

    Takes no --as: the packet store is per-machine, not per-identity.
    """
    from aya.adapters.paths import PACKETS_DIR

    format_ = resolve_format(format_)
    if limit < 1:
        limit = 20

    if not PACKETS_DIR.exists():
        if format_ == OutputFormat.JSON:
            _output_json({"packets": []})
            raise typer.Exit(0)
        console.print("[dim]No ingested packets found.[/dim]")
        return

    def _safe_mtime(f: Path) -> float:
        try:
            return f.stat().st_mtime
        except OSError:
            return 0.0

    files = sorted(PACKETS_DIR.glob("*.json"), key=_safe_mtime, reverse=True)[:limit]
    items: list[dict[str, str]] = []
    for f in files:
        try:
            pkt = Packet.from_json(f.read_text())
            items.append(
                {
                    "id": pkt.id,
                    "intent": pkt.intent,
                    "from": pkt.from_did,
                    "sent_at": pkt.sent_at,
                    "content_type": pkt.content_type,
                }
            )
        except Exception as exc:  # noqa: BLE001 — any unreadable file must not abort the listing
            # Logged, not swallowed: a skipped file makes the listing shorter
            # than the directory, and without this the difference is invisible.
            logger.warning("Skipping unreadable packet file %s: %s", f.name, exc)
            continue

    if format_ == OutputFormat.JSON:
        _output_json({"packets": items})
        raise typer.Exit(0)

    # Rich table display
    # "Stored", not "Ingested" — sent packets share this directory.
    table = Table(title=f"Stored Packets ({len(items)})")
    table.add_column("ID", width=10)
    table.add_column("Intent")
    table.add_column("From", width=8)
    table.add_column("Sent")
    for item in items:
        from_display = item["from"][:30] + "…" if len(item["from"]) > 30 else item["from"]
        table.add_row(item["id"][:8], item["intent"], from_display, item["sent_at"][:10])
    console.print(table)
