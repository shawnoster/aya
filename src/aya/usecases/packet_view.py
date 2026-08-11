"""One definition of how a packet is projected for reading.

Both surfaces answer "read this packet". They used to answer it differently:
the CLI returned ``{id, body}`` plus ``{from, sent_at, intent, in_reply_to}``
under ``--meta``, while MCP returned ``{content}`` plus ``{id, intent, from,
sent_at, content_type}``. Same request, different keys, and only the CLI shape
was ever written down in the skills — so an agent following the docs over MCP
looked for a ``body`` that was never there.

Keeping the projection here means neither surface owns it and neither can drift
from the other. Pure functions only: no I/O, no printing, no Rich.
"""

from __future__ import annotations

import json
from typing import Any

from aya.entities.packet import ContentType, Packet


def extract_body(content: object, content_type: ContentType | None = None) -> str:
    """Render raw packet content as a display string.

    Seed packets (``application/aya-seed``) carry a dict of ``opener``,
    ``context_summary`` and ``open_questions``, which is flattened into labelled
    sections. Content packets carry a plain string. Any other dict is dumped as
    indented JSON; anything else falls back to ``str``.
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


def read_view(packet: Packet, *, meta: bool) -> dict[str, Any]:
    """The JSON shape of a read packet, for every surface.

    ``body`` stays a readable string except for non-seed dict content, which is
    passed through as a dict so structured payloads survive a round trip.
    ``meta`` adds the envelope fields; without it the caller gets id and
    body only.
    """
    body: Any
    if isinstance(packet.content, dict) and packet.content_type != ContentType.SEED:
        body = packet.content
    else:
        body = extract_body(packet.content, packet.content_type)

    view: dict[str, Any] = {"id": packet.id, "body": body}
    if meta:
        view["from"] = packet.from_did
        view["sent_at"] = packet.sent_at
        view["intent"] = packet.intent
        view["in_reply_to"] = getattr(packet, "in_reply_to", None)
    return view
