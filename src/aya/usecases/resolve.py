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
        super().__init__(f"No Nostr pubkey for recipient {did[:24]}…. Pair first: 'aya pair'.")
        self.did = did


def resolve_instance(profile: Profile, instance: str | None) -> tuple[Identity, str]:
    """Return ``(identity, label)`` for *instance*. Raises InstanceResolutionError."""
    label, _reason = profile.resolve_instance_name(instance)
    return profile.instances[label], label


def resolve_recipient(profile: Profile, to: str) -> tuple[str, str]:
    """Resolve a label or raw DID to ``(did, label)``.

    A raw DID passes through. A known label maps to its DID. When exactly one
    peer is trusted, any label resolves to it — the same single-candidate
    convenience ``resolve_instance_name`` applies locally.
    """
    if to.startswith("did:"):
        return to, to
    key = profile.trusted_keys.get(to)
    if key:
        return key.did, to

    available = list(profile.trusted_keys)
    if len(available) == 1:
        label = available[0]
        return profile.trusted_keys[label].did, label
    raise UnknownRecipientError(to, available)


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


def resolve_relays(profile: Profile, relay: str | None) -> list[str]:
    """Relays to use: an explicit override, else the profile's defaults."""
    return [relay] if relay else list(profile.default_relays)
