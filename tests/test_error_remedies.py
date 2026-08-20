"""Every command aya suggests in an error message must be runnable as written.

Four separate remedies shipped in this repo telling the reader to run something
that could not work: a `cp` that landed the file under the wrong name, an
`aya trust` without the `--nostr-pubkey` delivery needs, and `aya pair` without
the `--peer` it has always required. Each read fine and each moved the reader
from one error to another.

The messages are *rendered* rather than scraped out of the source, because a
remedy is only wrong once assembled — the defects above were all in f-strings
whose pieces looked fine individually.
"""

from __future__ import annotations

import importlib
import inspect
import itertools
import pkgutil
import re
import shlex

import pytest
import typer

import aya
from aya.adapters.cli import app

# A command a user could type: `aya <sub> [<sub>…] [args]`. Stops at anything
# that is not an option, a <placeholder>, or a bare token.
_COMMAND = re.compile(r"\baya\s+[a-z][\w-]*(?:\s+(?:--?[\w-]+|<[^>]+>|[\w./#:@-]+))*")
_PLACEHOLDER = re.compile(r"^<.+>$")


def _variants(param: inspect.Parameter) -> list[object]:
    """Dummy values for one constructor parameter.

    Lists get both an empty and a populated variant: several messages switch
    branch on "are there any candidates", and only one branch would otherwise be
    rendered. That is what surfaced the bare `aya trust`.
    """
    annotation = param.annotation
    origin = getattr(annotation, "__origin__", None)
    if annotation is list or origin is list or str(annotation).startswith("list"):
        return [[], ["alpha", "beta"]]
    if annotation is int or annotation == "int":
        return [1]
    return ["x"]


def _rendered_messages() -> dict[str, set[str]]:
    """Every aya exception message, across each branch we can reach."""
    messages: dict[str, set[str]] = {}
    seen: set[type] = set()
    for module in pkgutil.walk_packages(aya.__path__, prefix="aya."):
        try:
            mod = importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 — an unimportable module is not this test's business
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, Exception) or obj in seen:
                continue
            if obj.__module__.split(".")[0] != "aya":
                continue
            seen.add(obj)
            signature = inspect.signature(obj.__init__)
            required = [
                p
                for _n, p in list(signature.parameters.items())[1:]
                if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY) and p.default is p.empty
            ]
            for combo in itertools.product(*[_variants(p) for p in required]) or [()]:
                try:
                    messages.setdefault(obj.__name__, set()).add(str(obj(*combo)))
                except Exception:  # noqa: BLE001 — some need real objects; others cover them
                    continue
    return messages


def _parse_failure(command: str) -> str | None:
    """None if *command* parses against the real CLI, else why it does not."""
    tokens = ["PLACEHOLDER" if _PLACEHOLDER.match(t) else t for t in shlex.split(command)[1:]]
    node = typer.main.get_command(app)
    path: list[str] = []
    # hasattr rather than isinstance(click.Group): in click 8.4 TyperGroup's MRO
    # reports Command, and the Group hierarchy is being reworked for click 9.
    while tokens and hasattr(node, "get_command"):
        import click

        sub = node.get_command(click.Context(node), tokens[0])
        if sub is None:
            break
        path.append(tokens.pop(0))
        node = sub
    if not path:
        return "names no aya subcommand"
    try:
        with node.make_context(" ".join(path), list(tokens), resilient_parsing=False):
            pass
    except SystemExit:
        return "the parser exited"
    except Exception as exc:  # noqa: BLE001 — typer vendors its own click exceptions
        detail = exc.format_message() if hasattr(exc, "format_message") else str(exc)
        return f"{type(exc).__name__}: {detail}"
    return None


@pytest.fixture(scope="module")
def suggested_commands() -> dict[str, set[str]]:
    """``command -> exception classes that suggest it``."""
    found: dict[str, set[str]] = {}
    for name, texts in _rendered_messages().items():
        for text in texts:
            for command in _COMMAND.findall(text):
                found.setdefault(command.strip(" .'\""), set()).add(name)
    return found


def test_the_guard_finds_commands_to_check(suggested_commands):
    """Without this, a broken extractor reports success by checking nothing."""
    assert len(suggested_commands) >= 4, (
        f"expected several suggested commands, found {sorted(suggested_commands)}"
    )
    assert any("--" in c for c in suggested_commands), (
        "no suggestion carries an option, so option handling is untested"
    )


def test_every_suggested_command_is_runnable(suggested_commands):
    failures = [
        f"{command!r} (from {', '.join(sorted(classes))}): {reason}"
        for command, classes in sorted(suggested_commands.items())
        if (reason := _parse_failure(command))
    ]
    assert not failures, "error messages suggest commands that do not work:\n" + "\n".join(failures)


def test_a_suggested_aya_trust_carries_the_delivery_key(suggested_commands):
    """`--nostr-pubkey` is optional to the parser and required in practice.

    `aya trust <did> --peer <label>` parses cleanly and leaves a peer with no
    delivery key, so a remedy that omits it hands the reader the next error —
    which is exactly how one of the four shipped. The parse check above cannot
    see this, because the flag is genuinely optional; the rule has to be named.
    """
    offenders = [
        f"{command!r} (from {', '.join(sorted(classes))})"
        for command, classes in sorted(suggested_commands.items())
        if "aya trust" in command and "--nostr-pubkey" not in command
    ]
    assert not offenders, (
        "these suggest trusting a peer without a delivery key, which leaves the "
        "problem the message is trying to solve:\n" + "\n".join(offenders)
    )
