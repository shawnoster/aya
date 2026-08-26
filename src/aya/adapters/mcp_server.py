"""MCP server — expose aya capabilities as Claude-native tools via stdio transport.

Every tool answers with a ``types.CallToolResult``: one JSON text block plus
``is_error`` — the protocol's failure flag, serialised as ``isError``. Build
results through :func:`_rendered` or :func:`_error` so the flag is never left to
its default.

Unknown tool names and missing arguments are answered in-band with
``is_error=True`` rather than as JSON-RPC protocol errors, which is what the spec
suggests for them. Deliberate: a protocol error surfaces client-side as a raised
``McpError``, which an agent handles worse than a readable payload it can act on.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from aya.adapters.error_map import ErrorCode, describe
from aya.adapters.outbox import (
    NOT_INGESTED_HINT,
    delivery_from_report,
    record_sent,
)
from aya.adapters.profile_store import load_profile
from aya.usecases import relay_ops
from aya.usecases.packet_view import read_view
from aya.usecases.resolve import (
    NoNostrPubkeyError,
    label_for_did,
    nostr_pubkey_for,
    resolve_instance,
    resolve_recipient,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool catalogue
# ---------------------------------------------------------------------------

_TOOLS: list[types.Tool] = [
    types.Tool(
        name="aya_status",
        description=(
            "Return workspace readiness status (systems, alerts, reminders, watches). "
            "Each watch carries target — what it is pointed at, e.g. owner/repo#N — "
            "which is null when the stored config cannot produce one; fall back to "
            "message."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_inbox",
        description=(
            "List pending (un-ingested) relay packets for an instance. Each carries "
            "signature_valid and trusted: signature_valid false means the claimed "
            "sender could not be authenticated, so from_did is an unverified claim "
            "and from_label is null."
        ),
        input_schema={
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
        input_schema={
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
        input_schema={
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
        input_schema={
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
        input_schema={
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
        input_schema={
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
        description=(
            "Read a stored packet by ID or prefix. Returns {id, body}; with "
            "meta, adds from, sent_at, intent and in_reply_to. Same shape as "
            "`aya read`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "packet_id": {
                    "type": "string",
                    "description": "Packet ID or prefix (min 8 chars).",
                },
                "meta": {
                    "type": "boolean",
                    "description": (
                        "If true, add the envelope fields (from, sent_at, "
                        "intent, in_reply_to) alongside id and body."
                    ),
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
        input_schema={
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
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="aya_packets",
        description=(
            "List packets stored on this machine — received ones plus your own "
            "sent packets, whose bodies are saved so they can be read back. "
            "Ordered by local write time, newest first. For delivery status of "
            "what you sent, use aya_sent."
        ),
        input_schema={
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
        input_schema={
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
        input_schema={
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


async def list_tools() -> list[types.Tool]:
    """The advertised catalogue. Kept as a plain function so it stays testable."""
    return _TOOLS


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _rendered(payload: str) -> types.CallToolResult:
    """A successful result whose single block is already-serialised JSON.

    The one place a success is constructed, so a field added here (an annotation,
    ``structured_content``) cannot reach some tools and miss others.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=payload)],
        is_error=False,
    )


def _text(data: object) -> types.CallToolResult:
    """Wrap *data* as a successful single-block JSON result."""
    return _rendered(json.dumps(data, indent=2, default=str))


def _error(
    message: str, *, code: str | None = None, context: dict[str, Any] | None = None
) -> types.CallToolResult:
    """A failed tool call.

    *code* and *context* come from ``adapters.error_map`` for a domain error, so an
    agent gets the same machine-readable fields the CLI emits. Without them the DID
    in a truncated message was unrecoverable here while the CLI carried it in full.

    ``is_error`` is what tells a client this was a failure. Set here rather than
    at the dispatch boundary because handlers construct their own errors too, and
    the flag cannot be recovered afterwards: a successful payload may legitimately
    carry an ``error`` key — ``relay_ops`` puts ``error: "persist_failed"`` on a
    packet whose body would not write — so there is nothing in the content to sniff.
    """
    payload: dict[str, Any] = {"error": message}
    if code is not None:
        payload["code"] = code
    if context:
        payload["context"] = context
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, default=str))],
        is_error=True,
    )


def _load_profile() -> Any:
    from aya.adapters.paths import PROFILE_PATH

    return load_profile(PROFILE_PATH)


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


async def _handle_sent(arguments: dict[str, Any]) -> types.CallToolResult:
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


async def _handle_status() -> types.CallToolResult:
    from aya.adapters.status_view import _render_json
    from aya.usecases.status import _gather_status

    data = _gather_status()
    return _rendered(_render_json(data))


def _poll_result(result: relay_ops.PollResult) -> types.CallToolResult:
    """A poll's envelope, flagged as a failure when no relay answered.

    ``packets: []`` with ``is_error`` unset reads as "nothing new", when the truth
    may be "could not check" — the two are indistinguishable to an agent, and the
    quiet one is far more common. The envelope is kept rather than replaced with a
    bare error so the caller can still see which instance and relays were tried.
    """
    payload = result.envelope()
    if result.relay_reachable:
        return _text(payload)
    payload["error"] = (
        f"No relay answered, so the inbox could not be read: {', '.join(result.relays)}. "
        "An empty packet list here means unknown, not empty."
    )
    payload["code"] = ErrorCode.RELAY_UNREACHABLE
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))],
        is_error=True,
    )


async def _handle_inbox(arguments: dict[str, Any]) -> types.CallToolResult:
    profile = _load_profile()
    result, _packets = await relay_ops.inbox(
        profile,
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
    )
    return _poll_result(result)


async def _handle_send(arguments: dict[str, Any]) -> types.CallToolResult:
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


async def _handle_receive(arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.adapters.paths import PROFILE_PATH

    profile = _load_profile()
    # MCP is always non-interactive: take trusted senders, hold the rest.
    result = await relay_ops.receive(
        profile,
        PROFILE_PATH,
        instance=arguments.get("instance"),
        relay=arguments.get("relay"),
    )
    return _poll_result(result)


async def _handle_schedule_remind(arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.scheduler import add_reminder

    item = add_reminder(arguments["message"], arguments["due"])
    return _text(item)


async def _handle_schedule_watch(arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.scheduler import add_watch

    item = add_watch(
        provider=arguments["provider"],
        target=arguments["target"],
        message=arguments["message"],
        condition=arguments.get("condition", ""),
    )
    return _text(item)


async def _handle_ack(arguments: dict[str, Any]) -> types.CallToolResult:
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


async def _handle_read(arguments: dict[str, Any]) -> types.CallToolResult:
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

    # Same projection as `aya read`, so both surfaces return the same keys.
    return _text(read_view(pkt, meta=meta))


async def _handle_config_set(arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.adapters.config import set_config_value

    key = arguments["key"]
    value = arguments["value"]
    config = set_config_value(key, value)
    return _text(config)


async def _handle_config_show(_arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.adapters.config import load_config

    config = load_config()
    return _text(config)


async def _handle_packets(arguments: dict[str, Any]) -> types.CallToolResult:
    from aya.adapters.paths import PACKETS_DIR
    from aya.entities.packet import Packet

    limit = max(int(arguments.get("limit", 20)), 1)

    if not PACKETS_DIR.exists():
        return _text([])

    def _safe_mtime(f: Path) -> float:
        try:
            return float(f.stat().st_mtime)
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
        except Exception as exc:  # noqa: BLE001 — any unreadable file must not abort the listing
            logger.warning("Skipping unreadable packet file %s: %s", f.name, exc)
    return _text(summaries)


async def _handle_relay_status(arguments: dict[str, Any]) -> types.CallToolResult:
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

Handler = Callable[[dict[str, Any]], Awaitable[types.CallToolResult]]

_HANDLERS: dict[str, Handler] = {
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


def _missing_required(name: str, arguments: dict[str, Any]) -> list[str]:
    """Required fields the caller omitted, per the tool's own declared schema."""
    tool = next((t for t in _TOOLS if t.name == name), None)
    if tool is None:
        return []
    required = tool.input_schema.get("required", [])
    return [field for field in required if field not in arguments]


async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Dispatch one tool call. Transport-independent, so tests can call it directly."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(f"Unknown tool: {name}")

    # mcp 2.0 stopped validating arguments against input_schema on the way in —
    # the schema is advisory now. Without this, a caller that omits a required
    # field gets the repr of a KeyError ({"error": "'to'"}), which names neither
    # the tool nor the fact that the field was required.
    if missing := _missing_required(name, arguments):
        return _error(f"{name} is missing required argument(s): {', '.join(missing)}")

    try:
        return await handler(arguments)
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        described = describe(exc)
        if described is None:
            return _error(str(exc))
        code, detail, context = described
        return _error(detail, code=code, context=context)


# ── transport wiring ─────────────────────────────────────────────────────────
#
# mcp 2.0 dropped the `@server.list_tools()` / `@server.call_tool()` decorators
# in favour of `on_*` callbacks passed to the constructor, which is why these
# two adapters exist: they translate the SDK's (context, params) -> Result
# shape to and from the plain functions above. Keeping the dispatch itself out
# of them means a tool call can be exercised without a transport.


async def _on_list_tools(
    _ctx: object, _params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=await list_tools())


async def _on_call_tool(_ctx: object, params: types.CallToolRequestParams) -> types.CallToolResult:
    return await call_tool(params.name, params.arguments or {})


# Constructed here rather than at import top: the handlers close over _TOOLS and
# _HANDLERS, which are defined above.
server: Server[None] = Server(
    "aya",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


# ── entry point ──────────────────────────────────────────────────────────────


async def main() -> None:
    """Run the MCP server over stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
