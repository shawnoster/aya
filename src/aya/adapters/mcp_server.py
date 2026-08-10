"""MCP server — expose aya capabilities as Claude-native tools via stdio transport."""

from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from aya.adapters.outbox import (
    NOT_INGESTED_HINT,
    delivery_from_report,
    record_sent,
)
from aya.usecases import relay_ops
from aya.usecases.resolve import (
    NoNostrPubkeyError,
    label_for_did,
    nostr_pubkey_for,
    resolve_instance,
    resolve_recipient,
)

logger = logging.getLogger(__name__)

server = Server("aya")

# ---------------------------------------------------------------------------
# Tool catalogue
# ---------------------------------------------------------------------------

_TOOLS: list[types.Tool] = [
    types.Tool(
        name="aya_status",
        description="Return workspace readiness status (systems, alerts, reminders, watches).",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_inbox",
        description="List pending (un-ingested) relay packets for an instance.",
        inputSchema={
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": ("Local identity to act as. Omit to use the primary instance."),
                },
                "relay": {
                    "type": "string",
                    "description": "Relay URL override (default: profile default_relays).",
                },
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_send",
        description="Build, sign, and publish a packet to a relay.",
        inputSchema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient label (e.g. 'home') or DID.",
                },
                "intent": {
                    "type": "string",
                    "description": "What this packet is and why it is being sent.",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown body of the packet.",
                },
                "instance": {
                    "type": "string",
                    "description": ("Local identity to act as. Omit to use the primary instance."),
                },
                "relay": {
                    "type": "string",
                    "description": "Relay URL override (default: profile default_relays).",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Dedup key — if already sent within 24h, return cached result.",
                },
                "in_reply_to": {
                    "type": "string",
                    "description": "Packet ID this message is a reply to.",
                },
            },
            "required": ["to", "intent", "content"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_receive",
        description="Poll the relay, auto-ingest trusted packets, and return summaries.",
        inputSchema={
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": ("Local identity to act as. Omit to use the primary instance."),
                },
                "relay": {
                    "type": "string",
                    "description": "Relay URL override (default: profile default_relays).",
                },
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_schedule_remind",
        description="Create a one-shot reminder in the scheduler.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Reminder text.",
                },
                "due": {
                    "type": "string",
                    "description": "When the reminder is due (e.g. 'tomorrow 9am', 'in 2 hours').",
                },
            },
            "required": ["message", "due"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_schedule_watch",
        description="Create a condition-based watch in the scheduler.",
        inputSchema={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Watch provider (e.g. 'github-pr').",
                },
                "target": {
                    "type": "string",
                    "description": "Provider-specific target (e.g. 'owner/repo#123').",
                },
                "message": {
                    "type": "string",
                    "description": "Alert message when the condition fires.",
                },
                "condition": {
                    "type": "string",
                    "description": (
                        "Condition that triggers the alert. "
                        "github-pr: 'approved_or_merged' (default), 'merged', 'new_comments' "
                        "(fires when comments increase; no-fire on first poll). "
                        "jira-query: 'new_results'. jira-ticket: 'status_changed'. "
                        "ci-checks: 'checks_failed', 'checks_complete'. "
                        "Omitting condition uses the provider default shown above, not any-change."
                    ),
                },
            },
            "required": ["provider", "target", "message"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_ack",
        description="Acknowledge a received packet, sending a reply back to the sender.",
        inputSchema={
            "type": "object",
            "properties": {
                "packet_id": {
                    "type": "string",
                    "description": "Packet ID or prefix (min 8 chars) to acknowledge.",
                },
                "message": {
                    "type": "string",
                    "description": "Short reply message (default: 'acknowledged').",
                    "default": "acknowledged",
                },
                "instance": {
                    "type": "string",
                    "description": ("Local identity to act as. Omit to use the primary instance."),
                },
                "relay": {
                    "type": "string",
                    "description": "Relay URL override (default: profile default_relays).",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Dedup key — if already sent within 24h, return cached result.",
                },
            },
            "required": ["packet_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_read",
        description="Read the content of a stored packet by ID or prefix.",
        inputSchema={
            "type": "object",
            "properties": {
                "packet_id": {
                    "type": "string",
                    "description": "Packet ID or prefix (min 8 chars).",
                },
                "meta": {
                    "type": "boolean",
                    "description": "If true, return full metadata; otherwise return content only.",
                    "default": False,
                },
            },
            "required": ["packet_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_config_set",
        description="Set a workspace configuration value.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Configuration key to set.",
                },
                "value": {
                    "type": "string",
                    "description": "Value to assign.",
                },
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_config_show",
        description="Show the current workspace configuration.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_packets",
        description="List stored packets, most recent first.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum number of packets to return (default: 20).",
                    "default": 20,
                },
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_sent",
        description=(
            "List packets this instance has sent, with per-relay delivery status. "
            "Counterpart to aya_inbox; aya_packets lists received packets only."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max packets to return (default 20).",
                },
                "failed_only": {
                    "type": "boolean",
                    "description": "Only packets some relay rejected.",
                },
            },
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_relay_status",
        description="Show relay health and identity info for an instance.",
        inputSchema={
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": "Local identity to check (default: 'default').",
                    "default": "default",
                },
            },
            "additionalProperties": False,
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _TOOLS


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _text(data: object) -> list[types.TextContent]:
    """Wrap *data* as a single JSON TextContent block."""
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _error(message: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({"error": message}))]


def _load_profile() -> Any:
    from aya.adapters.paths import PROFILE_PATH
    from aya.entities.identity import Profile

    return Profile.load(PROFILE_PATH)


def _resolve_instance_labelled(profile: Any, instance: str | None) -> tuple[Any, str]:
    """Resolve *instance* to ``(Identity, label)``. See ``aya.resolve``."""
    return resolve_instance(profile, instance)


def _resolve_instance(profile: Any, instance: str | None) -> Any:
    return resolve_instance(profile, instance)[0]


def _resolve_did(to: str, profile: Any) -> tuple[str, str]:
    """Resolve a label or DID. Raises UnknownRecipientError (a ValueError)."""
    return resolve_recipient(profile, to)


def _resolve_nostr_pubkey(did: str, profile: Any) -> str | None:
    """Look up the Nostr pubkey for a DID, or None."""
    try:
        return nostr_pubkey_for(profile, did)
    except NoNostrPubkeyError:
        return None


def _record_send(
    profile: Any,
    packet: Any,
    *,
    to_label: str,
    event_id: str,
    client: Any,
    relay_urls: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Log an outbound packet and return its per-relay delivery outcome."""
    from aya.adapters.paths import PROFILE_PATH

    relays_ok, relays_failed = delivery_from_report(
        getattr(client, "last_publish_report", []), relay_urls
    )
    record_sent(
        profile,
        PROFILE_PATH,
        packet,
        to_did=packet.to_did,
        to_label=to_label,
        event_id=event_id,
        relays_ok=relays_ok,
        relays_failed=relays_failed,
    )
    return relays_ok, relays_failed


async def _handle_sent(arguments: dict[str, Any]) -> list[types.TextContent]:
    """Outbound log with per-relay delivery status — counterpart to aya_inbox."""
    profile = _load_profile()
    limit = int(arguments.get("limit", 20) or 20)
    failed_only = bool(arguments.get("failed_only"))
    entries = list(reversed(profile.sent_ids))
    if failed_only:
        entries = [e for e in entries if e.get("relays_failed")]
    return _text({"packets": entries[:limit]})


def _label_for_did(profile: Any, did: str) -> str | None:
    """Human label for a sender DID. See ``aya.resolve.label_for_did``."""
    return label_for_did(profile, did)


# ── individual handlers ──────────────────────────────────────────────────────


async def _handle_status() -> list[types.TextContent]:
    from aya.adapters.status_view import _render_json
    from aya.usecases.status import _gather_status

    data = _gather_status()
    return [types.TextContent(type="text", text=_render_json(data))]


async def _handle_inbox(arguments: dict[str, Any]) -> list[types.TextContent]:
    profile = _load_profile()
    result, _packets = await relay_ops.inbox(
        profile,
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
    )
    return _text(result.envelope())


async def _handle_send(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.paths import PROFILE_PATH

    profile = _load_profile()
    result = await relay_ops.send(
        profile,
        PROFILE_PATH,
        to=arguments["to"],
        intent=arguments["intent"],
        body=relay_ops.PacketBody.markdown(arguments["content"]),
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
        in_reply_to=arguments.get("in_reply_to"),
        idempotency_key=arguments.get("idempotency_key"),
    )
    if result.cached:
        return _text({"event_id": result.event_id, "cached": True})
    return _text(
        {
            "packet_id": result.packet.id if result.packet else "",
            "event_id": result.event_id,
            "to": result.to_label,
            "relays_ok": result.relays_ok,
            "relays_failed": result.relays_failed,
        }
    )


async def _handle_receive(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.paths import PROFILE_PATH

    profile = _load_profile()
    # MCP is always non-interactive: take trusted senders, hold the rest.
    result = await relay_ops.receive(
        profile,
        PROFILE_PATH,
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
    )
    return _text(result.envelope())


async def _handle_schedule_remind(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.scheduler import add_reminder

    item = add_reminder(arguments["message"], arguments["due"])
    return _text(item)


async def _handle_schedule_watch(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.scheduler import add_watch

    item = add_watch(
        provider=arguments["provider"],
        target=arguments["target"],
        message=arguments["message"],
        condition=arguments.get("condition", ""),
    )
    return _text(item)


async def _handle_ack(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.paths import PROFILE_PATH

    profile = _load_profile()
    result = await relay_ops.ack(
        profile,
        PROFILE_PATH,
        packet_id=arguments["packet_id"],
        message=arguments.get("message", "acknowledged"),
        dismiss=bool(arguments.get("dismiss", False)),
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
        idempotency_key=arguments.get("idempotency_key"),
    )
    if result.cached:
        return _text({"event_id": result.event_id, "cached": True})
    return _text(
        {
            "packet_id": result.packet.id if result.packet else "",
            "event_id": result.event_id,
            "in_reply_to": result.in_reply_to,
            "to": result.to_label,
            "relays_ok": result.relays_ok,
            "relays_failed": result.relays_failed,
        }
    )


async def _handle_read(arguments: dict[str, Any]) -> list[types.TextContent]:
    packet_id = arguments["packet_id"]
    meta = arguments.get("meta", False)

    from aya.adapters.paths import PACKETS_DIR
    from aya.entities.packet import Packet

    if len(packet_id) < 8:
        return _error("Packet ID prefix must be at least 8 characters.")

    if not PACKETS_DIR.exists():
        return _error(NOT_INGESTED_HINT.format(packet_id=packet_id))

    matches = [f for f in PACKETS_DIR.glob("*.json") if f.stem.startswith(packet_id)]
    if not matches:
        return _error(NOT_INGESTED_HINT.format(packet_id=packet_id))
    if len(matches) > 1:
        return _error(f"Ambiguous prefix '{packet_id}' -- matches {len(matches)} packets.")

    pkt = Packet.from_json(matches[0].read_text())

    if meta:
        return _text(
            {
                "id": pkt.id,
                "intent": pkt.intent,
                "from": pkt.from_did,
                "sent_at": pkt.sent_at,
                "content_type": (
                    pkt.content_type.value
                    if hasattr(pkt.content_type, "value")
                    else str(pkt.content_type)
                ),
                "content": pkt.content,
            }
        )
    return _text({"content": pkt.content})


async def _handle_config_set(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.config import set_config_value

    key = arguments["key"]
    value = arguments["value"]
    config = set_config_value(key, value)
    return _text(config)


async def _handle_config_show(_arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.config import load_config

    config = load_config()
    return _text(config)


async def _handle_packets(arguments: dict[str, Any]) -> list[types.TextContent]:
    from aya.adapters.paths import PACKETS_DIR
    from aya.entities.packet import Packet

    limit = max(int(arguments.get("limit", 20)), 1)

    if not PACKETS_DIR.exists():
        return _text([])

    def _safe_mtime(f: Any) -> float:
        try:
            return f.stat().st_mtime
        except OSError:
            return 0.0

    files = sorted(PACKETS_DIR.glob("*.json"), key=_safe_mtime, reverse=True)
    files = files[:limit]

    summaries = []
    for f in files:
        try:
            pkt = Packet.from_json(f.read_text())
            summaries.append(
                {
                    "id": pkt.id,
                    "intent": pkt.intent,
                    "from": pkt.from_did,
                    "sent_at": pkt.sent_at,
                }
            )
        except Exception:
            logger.debug("Skipping unparseable packet file %s", f.name)
    return _text(summaries)


async def _handle_relay_status(arguments: dict[str, Any]) -> list[types.TextContent]:
    instance = arguments.get("instance")
    profile = _load_profile()
    local, instance_label = _resolve_instance_labelled(profile, instance)

    trusted = {label: tk.did for label, tk in profile.trusted_keys.items()}

    relays = profile.default_relays
    last_checked = {url: ts for url, ts in profile.last_checked.items() if url in relays}

    result: dict[str, Any] = {
        # Resolved label, never the caller's (possibly omitted) argument — the
        # answer must say which identity actually polled.
        "instance": instance_label,
        "instances": list(profile.instances.keys()),
        "primary_instance": profile.primary_instance,
        "did": local.did,
        "relays": relays,
        "trusted_keys": trusted,
        "last_checked": last_checked,
    }
    return _text(result)


# ── dispatcher ───────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "aya_status": lambda args: _handle_status(),
    "aya_inbox": _handle_inbox,
    "aya_send": _handle_send,
    "aya_receive": _handle_receive,
    "aya_schedule_remind": _handle_schedule_remind,
    "aya_schedule_watch": _handle_schedule_watch,
    "aya_ack": _handle_ack,
    "aya_read": _handle_read,
    "aya_config_set": _handle_config_set,
    "aya_config_show": _handle_config_show,
    "aya_packets": _handle_packets,
    "aya_sent": _handle_sent,
    "aya_relay_status": _handle_relay_status,
}


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(f"Unknown tool: {name}")
    try:
        return await handler(arguments)
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return _error(str(exc))


# ── entry point ──────────────────────────────────────────────────────────────


async def main() -> None:
    """Run the MCP server over stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
