"""One mapping from domain errors to what a surface reports.

The CLI and the MCP server both have to turn an exception into a code, a message
and machine-readable context. Held here rather than in each surface because they
drifted: ``ack`` never mapped ``NoNostrPubkeyError`` at all and exited through a
traceback, and MCP reported typed errors as bare prose with the DID unrecoverable —
both while the CLI's other commands handled them correctly.

Context comes from the exception's own attributes rather than a per-class
extractor, so an attribute added to an error surfaces on both surfaces at once and
cannot be listed in one table and forgotten in the other.
"""

from __future__ import annotations

from typing import Any

from aya.adapters.relay import RelayError, RelayUnreachableError
from aya.entities.identity import InstanceResolutionError
from aya.usecases.pair import PairingError
from aya.usecases.relay_ops import (
    AckSenderNotTrustedError,
    AmbiguousAckRecipientError,
    AmbiguousPrefixError,
    NoTrustedPeerError,
    PacketNotIngestedError,
    SendFailedError,
)
from aya.usecases.resolve import NoNostrPubkeyError, UnknownRecipientError


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


# Every domain error a surface can be handed. A subclass without its own entry
# resolves to its nearest mapped ancestor, so the table stays small; a *new*
# error with no ancestor here is caught by tests/test_error_mapping.py rather
# than surfacing as an untyped crash.
_CODES: dict[type[Exception], str] = {
    PacketNotIngestedError: ErrorCode.PACKET_NOT_FOUND,
    AmbiguousPrefixError: ErrorCode.AMBIGUOUS_PREFIX,
    AckSenderNotTrustedError: ErrorCode.PEER_NOT_TRUSTED,
    AmbiguousAckRecipientError: ErrorCode.PEER_NOT_TRUSTED,
    NoTrustedPeerError: ErrorCode.PEER_NOT_TRUSTED,
    SendFailedError: ErrorCode.SEND_FAILED,
    UnknownRecipientError: ErrorCode.UNKNOWN_RECIPIENT,
    NoNostrPubkeyError: ErrorCode.NO_NOSTR_PUBKEY,
    InstanceResolutionError: ErrorCode.INSTANCE_NOT_FOUND,
    PairingError: ErrorCode.PAIR_FAILED,
    RelayUnreachableError: ErrorCode.RELAY_UNREACHABLE,
    # Base of RelayUnreachableError, and raised bare when every relay rejects a
    # publish — listed last so the subclass above wins the MRO walk.
    RelayError: ErrorCode.SEND_FAILED,
}


def error_code_for(exc: BaseException) -> str | None:
    """The reportable code for *exc*, or None if it is not a domain error."""
    for cls in type(exc).__mro__:
        code = _CODES.get(cls)
        if code is not None:
            return code
    return None


def error_context(exc: BaseException) -> dict[str, Any]:
    """The exception's own public attributes, as machine-readable context."""
    return {k: v for k, v in vars(exc).items() if not k.startswith("_")}


def describe(exc: BaseException) -> tuple[str, str, dict[str, Any]] | None:
    """``(code, message, context)`` for a domain error, else None."""
    code = error_code_for(exc)
    if code is None:
        return None
    return code, str(exc), error_context(exc)
