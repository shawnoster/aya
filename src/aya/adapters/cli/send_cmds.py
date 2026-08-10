"""Outbound: send, send-raw, ack."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer

from aya.adapters import relay as _relay
from aya.adapters.cli._kernel import (
    DEFAULT_PROFILE,
    ErrorCode,
    OutputFormat,
    _collect_body,
    _emit_error,
    _load_profile,
    _output_json,
    _resolve_instance,
    app,
    console,
    err,
    resolve_format,
)
from aya.adapters.cli._render import (
    _render_ack,
    _render_send,
)
from aya.adapters.outbox import (
    check_idempotency,
    record_idempotency,
)

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.identity import (
    InstanceResolutionError,
)
from aya.entities.packet import ConflictStrategy, Packet
from aya.scheduler import (
    dismiss_alert,
    show_alerts,
)
from aya.usecases import relay_ops
from aya.usecases.resolve import (
    NoNostrPubkeyError,
    UnknownRecipientError,
    nostr_pubkey_for,
)

logger = logging.getLogger(__name__)


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

        if dry_run and result.packet is not None:
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

        if dry_run and result.packet is not None:
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
