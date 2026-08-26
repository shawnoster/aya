"""Shared plumbing for the CLI: the Typer app, the sub-apps, output
formatting, structured error codes and the renderers.

Command modules import from here and register themselves on ``app``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from aya.adapters import paths as _paths

# Explicit re-export (mypy strict forbids the implicit form): the CLI modules
# have always imported ErrorCode from here, and the codes now live beside the
# mapping that MCP shares.
# The redundant-looking alias is mypy's explicit re-export form, which strict
# mode requires and ruff's PLC0414 objects to. Keeping it means the nine CLI
# modules that import ErrorCode from here need no change.
from aya.adapters.error_map import ErrorCode as ErrorCode  # noqa: PLC0414
from aya.adapters.profile_store import load_profile, save_profile

# Subcommand modules — imported at top-level; each is only invoked when its
# subcommand is actually called, so startup cost is acceptable.
from aya.entities.identity import (
    Identity,
    InstanceResolutionError,
    Profile,
    TrustedKey,
)
from aya.entities.packet import ConflictStrategy
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

# emoji=False: Rich substitutes `:key:` for 🔑, and error messages carry
# did:key: identifiers the reader is meant to copy into another command.
err = Console(stderr=True, emoji=False)

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
        # Same reason as _output_json: this is parsed, not read.
        sys.stderr.write(json.dumps(payload, default=str) + "\n")
    else:
        # escape(): the message carries user input and str(exc) text, and Rich
        # reads brackets as markup. Unescaped, a message containing a closing tag
        # raises MarkupError *instead of* the Exit below — a traceback where an
        # exit code belongs — and a bracketed token is deleted, so the error
        # echoes back something the user did not type.
        err.print(f"[red]{escape(message)}[/red]")
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
        # `context or ""` is a real fallback; `opener` cannot be empty here.
        return relay_ops.PacketBody.seed(opener, context_summary=context or "")
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


def _record_pairing(
    p: Profile,
    profile_path: Path,
    peer: str,
    trusted: TrustedKey,
    used_relay: str | None,
) -> str | None:
    """Persist everything a successful pairing just proved.

    *used_relay* is the relay that actually carried the exchange — reported by
    :class:`~aya.usecases.pair.PairResult`, not guessed from the configured
    order. It is demonstrably one both sides can reach, so it becomes primary;
    without this the fact is discarded and every later send/receive needs
    ``--relay`` to rediscover it.

    Passing ``relay_urls[0]`` here instead would name whichever relay was
    configured first even when it failed and a fallback did the work.

    Returns the promoted relay URL, or None if the order was already right.
    """
    trusted.label = peer
    p.trusted_keys[peer] = trusted
    promoted = p.add_relay(used_relay, first=True) if used_relay else False
    save_profile(p, profile_path)
    return used_relay if promoted else None


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
    """Write JSON to stdout, unrendered.

    Deliberately not via the Rich console: ``console.out`` highlights
    JSON-looking text, so in any environment that forces colour (``FORCE_COLOR``,
    much of CI) ``--format json`` emitted ANSI escapes and no parser could read
    it. Machine output must not pass through a renderer.
    """
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")


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


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """aya — personal AI assistant toolkit."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)
