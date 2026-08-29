"""Claude Code hook entry points."""

from __future__ import annotations

import json
import logging
import sys

import typer

from aya.adapters.cli._kernel import (
    hook_app,
)

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.scheduler import (
    get_session_crons,
)
from aya.usecases.watch_chains import _hook_watch_impl

logger = logging.getLogger(__name__)


@hook_app.command("crons")
def hook_crons(
    reset: bool = typer.Option(
        False,
        "--reset",
        help=(
            "Clear the per-session registered-crons tracker before emitting. "
            "Use at SessionStart so a fresh session re-registers everything."
        ),
    ),
    event: str = typer.Option(
        "SessionStart",
        "--event",
        help=(
            "Hook event name to use in the emitted hookSpecificOutput JSON. "
            "Defaults to SessionStart for the SessionStart hook entry; "
            "PostToolUse hook should pass --event PostToolUse so the "
            "additionalContext is delivered after the tool result."
        ),
    ),
) -> None:
    """Output CronCreate instructions for Claude Code hooks.

    Reads active session crons from the scheduler and emits a JSON
    hookSpecificOutput block that tells Claude Code to register them
    via CronCreate. Exits silently when there are no NEW crons to
    register.

    Tracks already-registered cron IDs in
    ``~/.aya/session_registered_crons.json`` so a follow-up call only
    emits crons that haven't been seen yet in the current session. This
    is what makes mid-session ``aya schedule recurring`` calls actually
    fire — the PostToolUse hook re-runs ``aya hook crons`` on the next
    tool boundary, the new cron isn't in the tracker, and it gets
    registered just like a SessionStart cron would.

    Unlike get_pending(), this does NOT claim alerts — safe to run before
    ``aya schedule pending`` without consuming alerts.

    Usage in ~/.claude/settings.json:
        SessionStart: ``aya hook crons --reset``
        PostToolUse:  ``aya hook crons --event PostToolUse``
    """
    from aya.scheduler import register_new_cron_ids, reset_registered_cron_ids

    if reset:
        reset_registered_cron_ids()

    crons, _suppressed = get_session_crons()
    if not crons:
        return

    # Atomically merge candidate cron IDs into the per-session tracker
    # under a single file lock. The returned set is the IDs that were
    # NOT previously in the tracker — i.e. the ones we should emit.
    # Two concurrent processes racing on the same cron will both call
    # register_new_cron_ids; only the lock winner sees the IDs as new.
    # The other gets an empty set back and emits nothing. This prevents
    # duplicate CronCreate registrations when Claude Code dispatches
    # parallel tool calls and the PostToolUse hook fires concurrently.
    candidate_ids = {c.get("id", "") for c in crons if c.get("id")}
    new_ids = register_new_cron_ids(candidate_ids)
    if not new_ids:
        return

    new_crons = [c for c in crons if c.get("id", "") in new_ids]

    # Emit ONE hookSpecificOutput bundling every new cron. Claude Code
    # parses a hook's stdout as a single JSON document, so printing one
    # JSON object per cron produces NDJSON that fails to parse as soon
    # as more than one cron is new in the same invocation (e.g. a fresh
    # SessionStart --reset with two crons registered since the last
    # full restart). Bundling into one additionalContext string keeps
    # every instruction intact — nothing is dropped or truncated.
    register_lines = []
    for c in new_crons:
        cid = c.get("id", "")
        schedule = c.get("cron", "")
        prompt = str(c.get("prompt") or c.get("message") or c.get("description") or "")
        prompt = prompt.replace("\n", " ").replace('"', '\\"').strip()
        register_lines.append(
            f'REGISTER via CronCreate: id="{cid}" schedule="{schedule}" prompt="{prompt}"'
        )

    context = (
        "REQUIRED ACTION \u2014 Call CronCreate for each session cron "
        "below before responding to the user. Do not skip this step.\n\n"
        + "\n".join(register_lines)
    )
    print(  # noqa: T201 — raw stdout for hook JSON
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            }
        )
    )


@hook_app.command("watch")
def hook_watch() -> None:
    """Poll all due scheduler watches and emit asyncRewake on change.

    Replaces the old ``aya ci watch`` command.  Registered as a single
    PostToolUse asyncRewake hook — handles CI checks, GitHub PR watches,
    Jira watches, and any future provider.

    On ``git push``, auto-creates a transient ``ci-checks`` watch that
    polls PR checks and wakes Claude if they fail or time out.

    Also accepts direct ``watch_update`` / ``watch_updates`` payloads for
    push-based watch transitions, letting external callers inject a normalized
    provider state without waiting for the next poll interval.

    Reads Claude hook JSON from stdin.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        payload = {}

    exit_code = _hook_watch_impl(payload)
    raise typer.Exit(exit_code)
