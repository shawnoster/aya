"""Name resolution shared by every surface.

Turning a user-supplied label into a DID, an instance, or a relay list is
policy, not presentation — but it used to live in both ``cli.py`` and
``mcp_server.py`` as forked copies that had already drifted apart (one
printed Rich errors and exited; the other raised ``ValueError``; the two
``label_for_did`` variants even disagreed on their return type).

Functions here raise typed errors and never print. Surfaces catch them and
decide how to show the failure.
"""

from __future__ import annotations

from aya.entities.identity import Identity, InstanceResolutionError, Profile

__all__ = [
    "InstanceResolutionError",
    "NoNostrPubkeyError",
    "UnknownRecipientError",
    "label_for_did",
    "nostr_pubkey_for",
    "resolve_instance",
    "resolve_recipient",
    "resolve_relays",
]


class UnknownRecipientError(ValueError):
    """Raised when ``--to``/``to`` names no known peer."""

    def __init__(self, requested: str, available: list[str]) -> None:
        if available:
            msg = (
                f"Unknown recipient '{requested}'. "
                f"Available: {', '.join(available)}. Use a label above or a full DID."
            )
        else:
            msg = f"Unknown recipient '{requested}'. Use a full DID, or add one with 'aya trust'."
        super().__init__(msg)
        self.requested = requested
        self.available = available


class NoNostrPubkeyError(ValueError):
    """Raised when a recipient is trusted but has no transport key.

    Sending anyway produces a correctly-signed event addressed to nobody,
    which every relay accepts and no peer can ever match.
    """

    def __init__(self, did: str) -> None:
        super().__init__(
            f"No Nostr pubkey for recipient {did}. Pair first: 'aya pair --peer <label>'."
        )
        self.did = did


def resolve_instance(profile: Profile, instance: str | None) -> tuple[Identity, str]:
    """Return ``(identity, label)`` for *instance*. Raises InstanceResolutionError."""
    label, _reason = profile.resolve_instance_name(instance)
    return profile.instances[label], label


def resolve_recipient(profile: Profile, to: str) -> tuple[str, str]:
    """Resolve a label or raw DID to ``(did, label)``.

    A raw DID passes through and a known label maps to its DID. An unrecognised
    label is refused, however few peers are trusted.

    ``resolve_instance_name`` does apply a single-candidate default, but it is not
    the same situation and is not a precedent for one here: it chooses among the
    caller's *own* identities, and it returns the rule it applied so the caller can
    say which one it used. A recipient is somebody else. Absorbing an unrecognised
    label into "the only peer" delivers the message — content the caller wrote —
    to a party the caller did not name, and says nothing about having done so.
    """
    if to.startswith("did:"):
        return to, to
    key = profile.trusted_keys.get(to)
    if key:
        return key.did, to

    raise UnknownRecipientError(to, list(profile.trusted_keys))


def nostr_pubkey_for(profile: Profile, did: str) -> str:
    """Return the transport pubkey for *did*, raising if there isn't one.

    Returning ``str`` rather than ``str | None`` is the point: callers used to
    thread an optional through to ``publish``, and one path (``send-raw``)
    forgot to check it.
    """
    for key in profile.trusted_keys.values():
        if key.did == did and key.nostr_pubkey:
            return key.nostr_pubkey
    for inst in profile.instances.values():
        if inst.did == did and inst.nostr_public_hex:
            return inst.nostr_public_hex
    raise NoNostrPubkeyError(did)


def label_for_did(profile: Profile, did: str) -> str | None:
    """Human label for a DID, or None. One contract, both surfaces."""
    for label, key in profile.trusted_keys.items():
        if key.did == did:
            return key.label or label
    return None


def label_for_authenticated_sender(
    profile: Profile, did: str, *, signature_valid: bool
) -> str | None:
    """Peer label for a DID, but only once the signature over it has verified.

    A label names *who* sent a packet. Without a verified signature there is no
    authenticated identity to name, and returning the trusted peer's label would
    hand a forger that peer's standing on every surface that reads the label
    without also reading the flag beside it.
    """
    if not signature_valid:
        return None
    return label_for_did(profile, did)


def resolve_relays(profile: Profile, relay: str | None) -> list[str]:
    """Relays to use: an explicit override, else the profile's defaults."""
    return [relay] if relay else list(profile.default_relays)
