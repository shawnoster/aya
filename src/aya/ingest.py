"""Shared packet-ingest logic used by both the CLI and the MCP server."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from aya.packet import Packet

logger = logging.getLogger(__name__)


def ingest(packet: Packet, *, quiet: bool = False) -> None:
    """
    Ingest a packet: surface it (console/alert) and persist the body to PACKETS_DIR.

    Called by both the CLI receive flow and the MCP ``aya_receive`` handler. Pass
    ``quiet=True`` to suppress all console output — required when invoked from
    the MCP stdio path, where stray stdout writes would corrupt JSON-RPC.
    """
    is_seed = packet.content_type == "application/aya-seed"
    seed: dict[str, Any] = (
        (packet.content if isinstance(packet.content, dict) else {}) if is_seed else {}
    )

    if not quiet:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print(f"\n[bold]Ingesting:[/bold] {packet.intent}")
        if is_seed:
            console.print(
                Panel(
                    f"[bold]Opening question:[/bold]\n{seed.get('opener', '')}\n\n"
                    f"[bold]Context:[/bold]\n{seed.get('context_summary', '')}\n\n"
                    + (
                        "[bold]Open questions:[/bold]\n"
                        + "\n".join(f"  • {q}" for q in seed.get("open_questions", []))
                        if seed.get("open_questions")
                        else ""
                    ),
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

    if is_seed:
        # Persist seed as an unseen alert so it surfaces via `aya schedule pending`
        # on the next session start, even if ingested via the async SessionStart hook
        # (where stdout is not captured by Claude).
        from aya.scheduler import add_seed_alert

        from_label = packet.from_did[:16]
        add_seed_alert(
            intent=packet.intent,
            opener=seed.get("opener", ""),
            context_summary=seed.get("context_summary", ""),
            open_questions=seed.get("open_questions", []),
            from_label=from_label,
            packet_id=packet.id,
        )

    # Persist packet content for later retrieval (best-effort — never break ingest)
    try:
        from aya.paths import PACKETS_DIR

        PACKETS_DIR.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            PACKETS_DIR.chmod(0o700)
        packet_file = PACKETS_DIR / f"{packet.id}.json"
        packet_file.write_text(packet.to_json())
        with suppress(OSError):
            packet_file.chmod(0o600)

        # Prune old packets (>7 days based on file mtime)
        cutoff = datetime.now(UTC).timestamp() - 7 * 86400
        for old in PACKETS_DIR.glob("*.json"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
            except OSError:
                continue
    except Exception:
        logger.debug("Failed to persist packet %s", packet.id, exc_info=True)
