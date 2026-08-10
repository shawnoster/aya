"""Relay: send, ack, receive, inbox, read, drop, sent, packets, pair."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import nullcontext
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
    _collect_body,
    _emit_error,
    _extract_body,
    _load_profile,
    _output_json,
    _record_pairing,
    _render_ack,
    _render_receive,
    _render_send,
    _resolve_instance,
    _show_inbox,
    app,
    console,
    err,
    resolve_format,
)
from aya.adapters.outbox import (
    NOT_INGESTED_HINT,
    check_idempotency,
    record_idempotency,
)
from aya.adapters.profile_store import save_profile
from aya.adapters.relay import RelayUnreachableError

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.identity import (
    InstanceResolutionError,
)
from aya.entities.packet import ConflictStrategy, ContentType, Packet
from aya.scheduler import (
    dismiss_alert,
    show_alerts,
)
from aya.usecases import relay_ops
from aya.usecases.pair import (
    PairingError,
    generate_code,
    hash_code,
    join_pairing,
    poll_for_pair_response,
    publish_pair_request,
)
from aya.usecases.resolve import (
    NoNostrPubkeyError,
    UnknownRecipientError,
    nostr_pubkey_for,
)

logger = logging.getLogger(__name__)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """aya — personal AI assistant toolkit."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)


@app.command("send-raw")
def send_raw(
    packet_file: Path = typer.Argument(help="Packet JSON file to send"),
    relay: str = typer.Option(None, help="Relay URL (overrides profile default)"),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show packet without publishing"),
    idempotency_key: str = typer.Option(
        None,
        "--idempotency-key",
        "-k",
        help="Dedup key — if already sent within 24h, return cached result",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Send a pre-built packet file to a Nostr relay.

    This sends a pre-built packet file. To compose and send in one step:
      aya send --to <label> --intent "..."
    """
    logger.debug("send-raw: packet_file=%s, as=%s", packet_file, as_)
    format_ = resolve_format(format_)
    p = _load_profile(profile)
    local = _resolve_instance(p, as_)

    relay_urls = [relay] if relay else p.default_relays
    packet = Packet.from_json(packet_file.read_text())

    # Validate the packet's signature before publishing. Two failure modes
    # to handle separately:
    #
    # 1. Signature is missing or invalid AND from_did matches the local
    #    instance → user authored this packet but didn't sign it (common
    #    when hand-editing JSON). Re-sign with the local key automatically.
    #
    # 2. Signature is missing or invalid AND from_did is someone else →
    #    refuse. Forwarding an unsigned packet that claims to be from
    #    another sender would let the relay carry forged-looking data.
    #    The user must either get the original sender to sign it, or
    #    rewrite the from_did to match a local instance.
    if not packet.verify_from_did():
        if packet.from_did == local.did:
            packet = packet.sign(local)
            logger.info("Re-signed packet %s with local instance key", packet.id)
            if format_ != OutputFormat.JSON:
                err.print(
                    "[dim]Re-signed packet with local instance key "
                    "(signature was missing or invalid).[/dim]"
                )
        else:
            _emit_error(
                ErrorCode.INVALID_ARGUMENT,
                (
                    f"Packet has missing or invalid signature, and from_did "
                    f"({packet.from_did[:40]}…) does not match local instance "
                    f"({local.did[:40]}…). Refusing to forward an unsigned "
                    f"packet that claims to be from another sender."
                ),
                {"packet_id": packet.id, "from_did": packet.from_did},
            )

    if dry_run:
        _output_json(json.loads(packet.to_json()))
        raise typer.Exit(0)

    if idempotency_key:
        cached = check_idempotency(idempotency_key)
        if cached:
            if format_ == OutputFormat.JSON:
                _output_json({**cached, "cached": True})
                raise typer.Exit(0)
            console.print(
                f"[dim]Already sent (cached) — packet {cached.get('packet_id', '?')[:8]}[/dim]"
            )
            return

    client = _relay.RelayClient(relay_urls, local.nostr_private_hex, local.nostr_public_hex)

    # A None pubkey here would publish a correctly-signed event addressed to
    # nobody: every relay accepts it and no peer can ever match it.
    try:
        recipient_nostr_pub = nostr_pubkey_for(p, packet.to_did)
    except NoNostrPubkeyError as exc:
        _emit_error(ErrorCode.NO_NOSTR_PUBKEY, str(exc), {"to": packet.to_did})
        return
    event_id = asyncio.run(client.publish(packet, recipient_nostr_pub, encrypt=packet.encrypted))

    if idempotency_key:
        record_idempotency(idempotency_key, packet.id, event_id)

    relay_count = len(relay_urls)
    relay_display = relay_urls[0] if relay_count == 1 else f"{relay_urls[0]} (+{relay_count - 1})"

    if format_ == OutputFormat.JSON:
        _output_json({"packet_id": packet.id, "event_id": event_id, "relay": relay_display})
        raise typer.Exit(0)

    console.print(
        f"[green]✓[/green] Sent [cyan]{packet.intent}[/cyan]\n"
        f"  Packet: [dim]{packet.id[:8]}[/dim]  "
        f"Event: [dim]{event_id[:8]}[/dim]  "
        f"Relay: [dim]{relay_display}[/dim]"
    )


@app.command("send")
def send_cmd(
    to: str = typer.Option(..., help="Recipient label (home) or DID"),
    intent: str = typer.Option(..., help="What is this packet and why"),
    message: str = typer.Option(
        None,
        "--message",
        "-m",
        help="Markdown body of the packet (otherwise read from stdin)",
    ),
    files: list[Path] = typer.Option([], help="Files to include"),
    context: str = typer.Option(None, help="Annotation for the receiving assistant"),
    seed: bool = typer.Option(False, help="Create a conversation seed instead of content"),
    opener: str = typer.Option(None, help="[seed] Opening question for the receiving assistant"),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    relay: str = typer.Option(None, help="Relay URL (overrides profile default)"),
    conflict: ConflictStrategy = typer.Option(
        ConflictStrategy.LAST_WRITE_WINS, help="Conflict resolution strategy"
    ),
    no_encrypt: bool = typer.Option(
        False, "--no-encrypt", help="Send plaintext (debug or private-relay mode)"
    ),
    in_reply_to: str = typer.Option(None, "--in-reply-to", help="Packet ID this is a reply to"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show packet without publishing"),
    idempotency_key: str = typer.Option(
        None,
        "--idempotency-key",
        "-k",
        help="Dedup key — if already sent within 24h, return cached result",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Pack and send in one step — the natural 'pack for home' flow.

    Builds the packet, signs it, and publishes to the relay. This is the
    command most users want. For a pre-built packet file, see send-raw.

    The packet body comes from exactly one of:

    \b
      --seed --opener "..."   a short conversation starter (no body)
      --message/-m "..."      markdown body given inline
      --files path.md         markdown body read from files
      (stdin)                 markdown body piped in, e.g. `... <<'EOF'`

    Pass --in-reply-to <id> to thread a reply. For a bare acknowledgement with
    no new content, `aya ack <id> "message"` is shorter.

    Exit code is 0 if *any* relay accepts the packet, so it is not a delivery
    signal. Check `relays_failed` (or the Delivery block in text mode): if the
    peer polls only a relay that rejected it, they will never see the packet.
    `aya sent --failed` lists such packets later.
    """
    logger.debug("send: to=%s, intent=%s, as=%s", to, intent, as_)
    format_ = resolve_format(format_)
    body = _collect_body(
        message=message,
        files=files,
        seed=seed,
        opener=opener,
        context=context,
        conflict=conflict,
    )

    async def _run() -> None:
        p = _load_profile(profile)
        try:
            result = await relay_ops.send(
                p,
                profile,
                to=to,
                intent=intent,
                body=body,
                instance=as_,
                relay=relay,
                in_reply_to=in_reply_to,
                encrypt=not no_encrypt,
                idempotency_key=idempotency_key,
                publish=not dry_run,
            )
        except (InstanceResolutionError, UnknownRecipientError, NoNostrPubkeyError) as exc:
            code = (
                ErrorCode.INSTANCE_NOT_FOUND
                if isinstance(exc, InstanceResolutionError)
                else ErrorCode.UNKNOWN_RECIPIENT
                if isinstance(exc, UnknownRecipientError)
                else ErrorCode.NO_NOSTR_PUBKEY
            )
            _emit_error(code, str(exc))
            return
        except relay_ops.SendFailedError as exc:
            _emit_error(ErrorCode.SEND_FAILED, str(exc), {"relays": exc.relays})
            return

        if dry_run:
            _output_json(json.loads(result.packet.to_json()))
            return
        _render_send(result, as_json=format_ == OutputFormat.JSON)

    asyncio.run(_run())


@app.command()
def ack(
    packet_id: str = typer.Argument(help="Packet ID or prefix to acknowledge"),
    message: str | None = typer.Argument(
        None, help="Short reply message (default: 'acknowledged')"
    ),
    dismiss: bool = typer.Option(
        False, "--dismiss", help="No-action acknowledgment; message defaults to 'acknowledged'"
    ),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    relay: str = typer.Option(None, help="Relay URL (overrides profile default)"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show ACK packet without publishing"
    ),
    idempotency_key: str = typer.Option(
        None,
        "--idempotency-key",
        "-k",
        help="Dedup key — if already sent within 24h, return cached result",
    ),
    profile: Path = typer.Option(DEFAULT_PROFILE),
    format_: OutputFormat = typer.Option(
        OutputFormat.AUTO, "--format", "-f", help="Output format: auto (default), text, or json"
    ),
) -> None:
    """Acknowledge a received packet — sends a short reply back to the sender.

    MESSAGE is delivered to the sender as the reply body, so an ack is a real
    (if minimal) response, not a read receipt. It carries no intent line and no
    markdown, and the recipient is inferred from the original packet.

    Use this for "got it" / "will do" / no new content. For anything
    substantive — an answer, a decision, a counter-question — use
    ``aya send --in-reply-to <id>`` instead, which carries an intent and a full
    body. The packet must already be ingested (see ``aya receive``).
    """
    format_ = resolve_format(format_)

    async def _run() -> None:
        p = _load_profile(profile)
        if len(packet_id) < 8:
            _emit_error(
                ErrorCode.INVALID_ARGUMENT,
                "Packet ID prefix must be at least 8 characters.",
                {"packet_id": packet_id},
            )
        try:
            result = await relay_ops.ack(
                p,
                profile,
                packet_id=packet_id,
                message=message or "acknowledged",
                dismiss=dismiss,
                instance=as_,
                relay=relay,
                idempotency_key=idempotency_key,
                publish=not dry_run,
            )
        except relay_ops.PacketNotIngestedError as exc:
            _emit_error(ErrorCode.PACKET_NOT_FOUND, str(exc), {"packet_id": packet_id})
            return
        except relay_ops.AmbiguousPrefixError as exc:
            _emit_error(ErrorCode.AMBIGUOUS_PREFIX, str(exc), {"packet_id": packet_id})
            return
        except (relay_ops.AmbiguousAckRecipientError, relay_ops.NoTrustedPeerError) as exc:
            _emit_error(ErrorCode.PEER_NOT_TRUSTED, str(exc))
            return
        except InstanceResolutionError as exc:
            _emit_error(
                ErrorCode.INSTANCE_NOT_FOUND,
                str(exc),
                {"instance": as_, "available": exc.available},
            )
            return
        except relay_ops.SendFailedError as exc:
            _emit_error(ErrorCode.SEND_FAILED, str(exc), {"relays": exc.relays})
            return

        if dry_run:
            _output_json(json.loads(result.packet.to_json()))
            return

        # Clearing the matching seed alert is best-effort; never block the ACK.
        try:
            for alert in show_alerts(mark_seen=False):
                if alert.get("source_item_id", "").startswith(packet_id):
                    dismiss_alert(alert["id"])
                    break
        except Exception:  # noqa: S110
            pass

        _render_ack(result, message or "acknowledged", as_json=format_ == OutputFormat.JSON)

    asyncio.run(_run())


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


@app.command()
def pair(
    code: str = typer.Option(None, help="Pairing code from the other instance (joiner mode)"),
    peer: str = typer.Option(..., "--peer", help="Name for the remote peer"),
    as_: str | None = typer.Option(
        None,
        "--as",
        help="Local identity to act as (default: primary instance)",
    ),
    relay: str = typer.Option(None, help="Relay URL (overrides profile default)"),
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
            trusted = asyncio.run(join_pairing(local, code, relay_urls))
        except PairingError as exc:
            err.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        promoted = _record_pairing(p, profile, peer, trusted, relay_urls)

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
            f"DID:     [dim]{trusted.did}[/dim]"
            "  [dim italic](ed25519 · identity & signing)[/dim italic]",
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
        if format_ != OutputFormat.JSON:
            ctx_mgr = console.status("[bold cyan]Waiting for the other peer…[/bold cyan]")
        else:
            ctx_mgr = nullcontext()
        with ctx_mgr:
            trusted = asyncio.run(
                poll_for_pair_response(relay_urls, local.nostr_public_hex, request_event_id)
            )

        if trusted is None:
            if format_ == OutputFormat.JSON:
                _emit_error(ErrorCode.PAIR_TIMEOUT, "Pairing timed out")
            console.print(
                "[bold yellow]Pairing timed out.[/bold yellow] "
                "Run [bold]aya pair[/bold] again for a new code."
            )
            raise typer.Exit(1)

        promoted = _record_pairing(p, profile, peer, trusted, relay_urls)

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
            f"DID:     [dim]{trusted.did}[/dim]"
            "  [dim italic](ed25519 · identity & signing)[/dim italic]",
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

    from aya.entities.packet import Packet

    packet = Packet.from_json(matches[0].read_text())

    if format_ == OutputFormat.JSON:
        # In JSON output mode, non-seed dict content (e.g. application/json
        # packets) is passed through as a structured value rather than
        # stringified. Callers that ``jq`` or ``python -c 'json.load'`` over
        # the output get a real object, not a string containing pretty-printed
        # JSON. Seed-shape dicts still go through _extract_body so the
        # ``body`` field stays a readable string (opener + context + qs).
        body_value: object
        if isinstance(packet.content, dict) and packet.content_type != ContentType.SEED:
            body_value = packet.content
        else:
            body_value = _extract_body(packet.content, packet.content_type)

        result: dict[str, object] = {"id": packet.id, "body": body_value}
        if meta:
            result["from"] = packet.from_did
            result["sent_at"] = packet.sent_at
            result["intent"] = packet.intent
            result["in_reply_to"] = getattr(packet, "in_reply_to", None)
        _output_json(result)
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
    relay: str | None = typer.Option(None, help="Relay URL (overrides profile default)"),
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
    """List recently received (ingested) packets. For outbound, see 'aya sent'.

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

    from aya.entities.packet import Packet

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
        except Exception:  # noqa: S112
            continue

    if format_ == OutputFormat.JSON:
        _output_json({"packets": items})
        raise typer.Exit(0)

    # Rich table display
    table = Table(title=f"Ingested Packets ({len(items)})")
    table.add_column("ID", width=10)
    table.add_column("Intent")
    table.add_column("From", width=8)
    table.add_column("Sent")
    for item in items:
        from_display = item["from"][:30] + "…" if len(item["from"]) > 30 else item["from"]
        table.add_row(item["id"][:8], item["intent"], from_display, item["sent_at"][:10])
    console.print(table)
