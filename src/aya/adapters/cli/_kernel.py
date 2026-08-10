"""Shared plumbing for the CLI: the Typer app, the sub-apps, output
formatting, structured error codes and the renderers.

Command modules import from here and register themselves on ``app``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.parse
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, TypedDict

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aya.adapters import paths as _paths
from aya.adapters.outbox import (
    delivery_summary,
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
from aya.entities.packet import ConflictStrategy, ContentType, Packet, human_age
from aya.usecases import relay_ops
from aya.usecases.resolve import (
    resolve_instance,
)

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)

app = typer.Typer(
    name="aya",
    help="Personal AI assistant toolkit — sync, schedule, identity.",
    no_args_is_help=True,
)

schedule_app = typer.Typer(
    name="schedule",
    help="Reminders, watches, and recurring jobs.",
    no_args_is_help=True,
)

hook_app = typer.Typer(
    name="hook",
    help="Claude Code hook integrations.",
    no_args_is_help=True,
)

config_app = typer.Typer(
    name="config",
    help="Workspace configuration (notebook path, etc.).",
    no_args_is_help=True,
)

relay_app = typer.Typer(
    name="relay",
    help="Relay health and defaults: status, list, add, remove.",
    no_args_is_help=True,
)

console = Console()

err = Console(stderr=True)

_RELAY_FETCH_TIMEOUT_SECONDS = 30

log_app = typer.Typer(
    name="log",
    help="Daily progress logging.",
    no_args_is_help=True,
)

app.add_typer(schedule_app, name="schedule")
app.add_typer(hook_app, name="hook")
app.add_typer(config_app, name="config")
app.add_typer(relay_app, name="relay")
app.add_typer(log_app, name="log")


class OutputFormat(StrEnum):
    AUTO = "auto"
    TEXT = "text"
    JSON = "json"


class StatusFormat(StrEnum):
    AUTO = "auto"
    TEXT = "text"
    JSON = "json"
    RICH = "rich"


def resolve_format(fmt: OutputFormat) -> OutputFormat:
    """Resolve AUTO to a concrete format based on env var or TTY detection."""
    if fmt is not OutputFormat.AUTO:
        return fmt
    env = os.environ.get("AYA_FORMAT", "").strip().lower()
    if env in ("text", "json"):
        return OutputFormat(env)
    return OutputFormat.TEXT if sys.stdout.isatty() else OutputFormat.JSON


def resolve_status_format(fmt: StatusFormat) -> StatusFormat:
    """Resolve AUTO to a concrete format based on env var or TTY detection."""
    if fmt is not StatusFormat.AUTO:
        return fmt
    env = os.environ.get("AYA_FORMAT", "").strip().lower()
    if env in ("text", "json", "rich"):
        return StatusFormat(env)
    return StatusFormat.TEXT if sys.stdout.isatty() else StatusFormat.JSON


class ErrorCode:
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    INSTANCE_NOT_FOUND = "INSTANCE_NOT_FOUND"
    RELAY_UNREACHABLE = "RELAY_UNREACHABLE"
    RELAY_TIMEOUT = "RELAY_TIMEOUT"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    PACKET_NOT_FOUND = "PACKET_NOT_FOUND"
    PEER_NOT_TRUSTED = "PEER_NOT_TRUSTED"
    PAIR_FAILED = "PAIR_FAILED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    AMBIGUOUS_PREFIX = "AMBIGUOUS_PREFIX"
    SEND_FAILED = "SEND_FAILED"
    PAIR_TIMEOUT = "PAIR_TIMEOUT"
    UNKNOWN_RECIPIENT = "UNKNOWN_RECIPIENT"
    NO_NOSTR_PUBKEY = "NO_NOSTR_PUBKEY"


def _want_json_errors() -> bool:
    """True when errors should be emitted as structured JSON."""
    env = os.environ.get("AYA_FORMAT", "").strip().lower()
    if env == "json":
        return True
    if env == "text":
        return False
    return not sys.stderr.isatty()


def _emit_error(
    code: str,
    message: str,
    context: dict[str, object] | None = None,
    exit_code: int = 1,
) -> NoReturn:
    """Emit an error — structured JSON on stderr in JSON mode, Rich-formatted otherwise."""
    if _want_json_errors():
        payload: dict[str, object] = {"error": {"code": code, "message": message}}
        if context:
            payload["error"]["context"] = context  # type: ignore[index]
        err.out(json.dumps(payload, default=str))
    else:
        err.print(f"[red]{message}[/red]")
    raise typer.Exit(exit_code)


def DEFAULT_PROFILE() -> Path:  # noqa: N802 — used as a Typer option default
    """Resolve the profile path per invocation.

    A module-level constant would snapshot AYA_HOME at import, so a process
    that changes it later (or a test) could never redirect the default.
    Typer calls a callable default at parse time.
    """
    return _paths.PROFILE_PATH


def _load_profile(profile_path: Path) -> Profile:
    if not profile_path.exists():
        _emit_error(
            ErrorCode.PROFILE_NOT_FOUND,
            f"Profile not found at {profile_path}. Run 'aya init' first.",
            {"path": str(profile_path)},
        )
    return load_profile(profile_path)


def _collect_body(
    *,
    message: str | None,
    files: list[Path],
    seed: bool,
    opener: str | None,
    context: str | None,
    conflict: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS,
) -> relay_ops.PacketBody:
    """Turn this command's body flags into one PacketBody.

    Input adaptation, kept apart from the send itself so the four ways of
    supplying a body — and the two ways of supplying none — are testable
    without a relay.
    """
    if seed:
        if not opener:
            _emit_error(ErrorCode.INVALID_ARGUMENT, "--opener required for seed packets.")
        return relay_ops.PacketBody.seed(opener or "", context_summary=context or "")
    if files:
        return relay_ops.PacketBody.from_files([str(f) for f in files], context=context)
    if message is not None:
        content = message
    elif sys.stdin.isatty():
        # No body source and no pipe: reading stdin would hang on a terminal
        # and ship an empty packet in a script. Name every way to supply one.
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            "No packet body. Pass --message/-m, --files, or --seed --opener, "
            "or pipe markdown on stdin.",
            exit_code=2,
        )
        content = ""
    else:
        content = sys.stdin.read()
    if not content.strip():
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            "Packet body is empty. Pass --message/-m, --files, or --seed --opener, "
            "or pipe non-empty markdown on stdin.",
            exit_code=2,
        )
    return relay_ops.PacketBody.markdown(content, context=context, conflict=conflict)


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


def _record_pairing(
    p: Profile,
    profile_path: Path,
    peer: str,
    trusted: TrustedKey,
    relay_urls: list[str],
) -> str | None:
    """Persist everything a successful pairing just proved.

    The relay that carried the exchange is demonstrably one both sides can
    reach, so it becomes the primary. Without this the fact is discarded and
    every later send/receive needs ``--relay`` to rediscover it.

    Returns the promoted relay URL, or None if the order was already right.
    """
    trusted.label = peer
    p.trusted_keys[peer] = trusted
    promoted = relay_urls and p.add_relay(relay_urls[0], first=True)
    save_profile(p, profile_path)
    return relay_urls[0] if promoted else None


def _render_delivery(relays_ok: list[str], relays_failed: list[dict[str, object]]) -> str:
    """One line per relay, so a partial delivery is visible rather than implied."""
    lines = [f"  [green]✓[/green] {url}" for url in relays_ok]
    lines += [
        f"  [red]✗[/red] {f['url']} [dim]({f.get('error') or 'failed'})[/dim]"
        for f in relays_failed
    ]
    return "\n".join(lines)


def _resolve_instance_labelled(
    p: Profile, instance: str | None, *, quiet: bool = False
) -> tuple[Identity, str]:
    """Resolve *instance* to ``(Identity, label)``.

    Delegates the rules to :meth:`Profile.resolve_instance_name` and turns an
    unresolvable request into a typed CLI error instead of a silent fallback.
    """
    try:
        return resolve_instance(p, instance)
    except InstanceResolutionError as exc:
        if not quiet:
            _emit_error(
                ErrorCode.INSTANCE_NOT_FOUND,
                str(exc),
                {"instance": instance, "available": exc.available},
            )
        raise typer.Exit(1) from None


def _resolve_instance(p: Profile, instance: str | None, *, quiet: bool = False) -> Identity:
    """Return the local Identity for *instance*. See :func:`_resolve_instance_labelled`."""
    return _resolve_instance_labelled(p, instance, quiet=quiet)[0]


def _output_json(data: object) -> None:
    """Output data as formatted JSON to console."""
    console.out(json.dumps(data, indent=2, default=str))


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


def _extract_body(content: object, content_type: ContentType | None = None) -> str:
    """Extract a packet body string from raw content for display.

    For seed packets (`application/aya-seed`), content is a dict with
    ``opener``, ``context_summary``, and ``open_questions``. For content
    packets (markdown, text), content is a plain string. JSON dict content
    that isn't a seed is serialized with ``json.dumps``. Anything else
    falls back to ``str(content)``.
    """
    lines: list[str] = []
    if isinstance(content, dict):
        if content_type == ContentType.SEED:
            opener = content.get("opener")
            if opener:
                lines.append(str(opener))
            context_summary = content.get("context_summary")
            if context_summary:
                if lines:
                    lines.append("")
                lines.append("--- context ---")
                lines.append(str(context_summary))
            open_questions = content.get("open_questions") or []
            if open_questions:
                if lines:
                    lines.append("")
                lines.append("--- open questions ---")
                for q in open_questions:
                    lines.append(f"- {q}")
        else:
            lines.append(json.dumps(content, indent=2, default=str))
    elif isinstance(content, str):
        lines.append(content)
    else:
        lines.append(str(content))
    return "\n".join(lines)


def _load_profile_for_relay(profile_path: Path) -> Profile:
    """Load a profile for relay commands using the standard profile loader."""
    return _load_profile(profile_path)


def _validate_relay_url(url: str) -> None:
    """Reject anything that isn't a valid ws:// or wss:// URL with a non-empty host.

    Rejects whitespace anywhere in the URL, not just leading/trailing — urlparse
    happily accepts 'wss://relay .example' with a space in the netloc, which
    would later fail at websockets.connect() rather than at the CLI boundary.
    """
    parsed = urllib.parse.urlparse(url)
    has_whitespace = any(c.isspace() for c in url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or has_whitespace:
        _emit_error(
            ErrorCode.INVALID_ARGUMENT,
            f"Relay URL must be a valid wss:// or ws:// address with a hostname (got {url!r}).",
            context={"url": url},
            exit_code=2,
        )


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
