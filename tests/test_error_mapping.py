"""Both surfaces must report a domain error the same way.

The CLI and the MCP server each used to turn exceptions into user-facing output on
their own, and they drifted twice: `ack` never mapped `NoNostrPubkeyError` at all
and exited through a traceback with no payload, and MCP reported typed errors as
bare prose with the sender DID unrecoverable — while the CLI's other commands
handled both correctly. These tests make that class of drift a failure here rather
than a review finding.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import ClassVar

import pytest

import aya
from aya.adapters.error_map import _CODES, describe, error_code_for, error_context


def _domain_exceptions() -> list[type[BaseException]]:
    """Every exception class aya defines, excluding abstract bases."""
    found: dict[str, type[BaseException]] = {}
    for module in pkgutil.walk_packages(aya.__path__, prefix="aya."):
        try:
            mod = importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 — an unimportable module is not this test's business
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, BaseException)
                and obj.__module__.split(".")[0] == "aya"
                and obj.__name__ not in {"RelayOpError"}  # base class, never raised bare
            ):
                found[obj.__name__] = obj
    return sorted(found.values(), key=lambda c: c.__name__)


class TestEveryDomainErrorIsMapped:
    def test_the_discovery_finds_the_errors(self):
        """Without this, an empty sweep would report success by checking nothing."""
        names = {c.__name__ for c in _domain_exceptions()}
        assert len(names) >= 8, f"expected aya's error family, found {sorted(names)}"
        assert "NoNostrPubkeyError" in names, "the error whose drift prompted this"

    @pytest.mark.parametrize("exc_class", _domain_exceptions(), ids=lambda c: c.__name__)
    def test_it_resolves_to_a_code(self, exc_class):
        """A new domain error must be given a code, not left to surface untyped.

        `CrontabUnreadableError` is exempt: it subclasses subprocess.CalledProcessError
        and is reported through the install result's error list, never a tool result.
        """
        if exc_class.__name__ == "CrontabUnreadableError":
            pytest.skip("reported through InstallResult.errors, not a surface mapping")
        assert error_code_for(exc_class.__new__(exc_class)) is not None, (
            f"{exc_class.__name__} has no entry in error_map._CODES, so both surfaces "
            "would report it as an untyped crash"
        )


class TestContextComesFromTheException:
    def test_public_attributes_become_context(self):
        from aya.usecases.relay_ops import AckSenderNotTrustedError

        exc = AckSenderNotTrustedError("did:key:zSender")
        assert error_context(exc) == {"sender_did": "did:key:zSender"}

    def test_an_attribute_added_later_needs_no_table_change(self):
        """The point of deriving context: one place to add a field, not two."""
        from aya.usecases.resolve import UnknownRecipientError

        exc = UnknownRecipientError("hoem", ["home"])
        exc.hint = "did you mean home?"  # type: ignore[attr-defined]
        assert error_context(exc)["hint"] == "did you mean home?"

    def test_private_attributes_stay_private(self):
        from aya.usecases.relay_ops import SendFailedError

        exc = SendFailedError(["wss://a"])
        exc._internal = "not for callers"  # type: ignore[attr-defined]
        assert "_internal" not in error_context(exc)


class TestBothSurfacesAgree:
    """The CLI and MCP must not disagree about the same exception."""

    CASES: ClassVar[list[tuple[str, tuple]]] = [
        ("AckSenderNotTrustedError", ("did:key:zSender",)),
        ("AmbiguousAckRecipientError", (["home", "work"],)),
        ("NoTrustedPeerError", ()),
        ("PacketNotIngestedError", ("01ABC",)),
        ("SendFailedError", (["wss://a"],)),
    ]

    @pytest.mark.parametrize(("name", "args"), CASES, ids=[c[0] for c in CASES])
    def test_the_same_exception_yields_the_same_code_and_context(self, name, args):
        from aya.usecases import relay_ops

        exc = getattr(relay_ops, name)(*args)
        described = describe(exc)
        assert described is not None, f"{name} is unmapped"
        code, message, context = described

        # Both surfaces call describe(), so agreement is structural — this asserts
        # the shape each one then emits, which is where they previously diverged.
        assert code in set(_CODES.values())
        assert message == str(exc)
        assert context == error_context(exc)

    def test_the_mcp_payload_carries_code_and_context(self):
        """MCP used to emit prose only, so a truncated DID was unrecoverable."""
        import json

        from aya.adapters.mcp_server import _error
        from aya.usecases.relay_ops import AckSenderNotTrustedError

        exc = AckSenderNotTrustedError("did:key:zFullSenderIdentifier")
        code, message, context = describe(exc)  # type: ignore[misc]
        payload = json.loads(_error(message, code=code, context=context).content[0].text)

        assert payload["code"] == "PEER_NOT_TRUSTED"
        assert payload["context"]["sender_did"] == "did:key:zFullSenderIdentifier"
