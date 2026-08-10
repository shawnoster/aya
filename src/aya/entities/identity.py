"""Identity entities — did:key generation, keypairs, trusted-key registry.

Pure data and the rules that operate on it. Reading and writing
``profile.json`` lives in ``adapters.profile_store``: an entity that persists
itself would have to reach outward for storage, which is the dependency rule
backwards.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

import base58
from coincurve import PrivateKey as Secp256k1PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from ulid import ULID

logger = logging.getLogger(__name__)

# ── schema version ────────────────────────────────────────────────────────────
PROFILE_SCHEMA_VERSION = 1

# Multicodec prefix for ed25519 public keys: 0xed 0x01
_ED25519_MULTICODEC = bytes([0xED, 0x01])


@dataclass
class Identity:
    """A local assistant instance identity.

    Two keypairs:
      - ed25519: for did:key identity and packet signing (W3C standard)
      - secp256k1: for Nostr transport (BIP-340 Schnorr signatures)
    """

    did: str
    label: str  # "work", "home", "laptop", etc.
    private_key_hex: str  # ed25519 — identity / packet signing
    public_key_hex: str  # ed25519
    nostr_private_hex: str  # secp256k1 — Nostr transport
    nostr_public_hex: str  # secp256k1 x-only (32 bytes)

    @classmethod
    def generate(cls, label: str) -> Identity:
        """Generate ed25519 (did:key) + secp256k1 (Nostr) keypairs."""
        # ed25519 for did:key
        ed_private = Ed25519PrivateKey.generate()
        ed_pub_bytes = ed_private.public_key().public_bytes_raw()
        ed_priv_bytes = ed_private.private_bytes_raw()

        multicodec = _ED25519_MULTICODEC + ed_pub_bytes
        did = "did:key:z" + base58.b58encode(multicodec).decode()

        # secp256k1 for Nostr
        nostr_secret = secrets.token_bytes(32)
        nostr_key = Secp256k1PrivateKey(nostr_secret)
        # x-only public key (BIP-340): drop the 0x02/0x03 prefix byte
        nostr_pub_full = nostr_key.public_key.format(compressed=True)
        nostr_pub_xonly = nostr_pub_full[1:]  # 32 bytes

        return cls(
            did=did,
            label=label,
            private_key_hex=ed_priv_bytes.hex(),
            public_key_hex=ed_pub_bytes.hex(),
            nostr_private_hex=nostr_secret.hex(),
            nostr_public_hex=nostr_pub_xonly.hex(),
        )

    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.private_key_hex))

    def public_key(self) -> Ed25519PublicKey:
        return self.private_key().public_key()

    def sign(self, data: bytes) -> bytes:
        """Sign with ed25519 (for packet signatures)."""
        return self.private_key().sign(data)

    def nostr_sign(self, message_bytes: bytes) -> bytes:
        """Sign with secp256k1 Schnorr (BIP-340, for Nostr events)."""
        key = Secp256k1PrivateKey(bytes.fromhex(self.nostr_private_hex))
        return key.sign_schnorr(message_bytes)

    def nostr_pubkey(self) -> str:
        """Hex-encoded x-only secp256k1 public key for Nostr."""
        return self.nostr_public_hex


@dataclass
class TrustedKey:
    did: str
    label: str  # "home", "friend:alice", etc.
    nostr_pubkey: str | None = None


_DEFAULT_RELAYS = ["wss://relay.damus.io", "wss://nos.lol"]


class InstanceResolutionError(ValueError):
    """Raised when ``--as``/``instance`` cannot be resolved to one instance.

    Subclasses ``ValueError`` so existing callers that catch it keep working.
    """

    def __init__(self, message: str, available: list[str], requested: str | None) -> None:
        super().__init__(message)
        self.available = available
        self.requested = requested


def _is_valid_ulid(value: str) -> bool:
    """Check if a string is a valid ULID."""
    try:
        ULID.from_str(value)
        return True
    except (ValueError, TypeError):
        return False


def _validate_instance(key: str, data: dict[str, Any]) -> Identity:
    """Validate and create an Instance from a dict, with helpful error messages.

    Raises ValueError with context if the dict is malformed.
    """
    try:
        return Identity(**data)
    except TypeError as e:
        raise ValueError(f"Instance '{key}' is malformed: {e}") from e
    except Exception as e:
        raise ValueError(f"Instance '{key}' could not be loaded: {e}") from e


def _validate_trusted_key(key: str, data: dict[str, Any]) -> TrustedKey:
    """Validate and create a TrustedKey from a dict, with helpful error messages.

    Raises ValueError with context if the dict is malformed.
    """
    try:
        return TrustedKey(**data)
    except TypeError as e:
        raise ValueError(
            f"Trusted key '{key}' is malformed: missing or invalid required field. {e}"
        ) from e
    except Exception as e:
        raise ValueError(f"Trusted key '{key}' could not be loaded: {e}") from e


def _assert_valid_ulid(id_: str) -> None:
    """Raise ``ValueError`` if *id_* is not a valid 26-character ULID.

    Call this before appending to ``ingested_ids`` so that truncated display
    prefixes or other malformed values are rejected at write time.
    """
    if not _is_valid_ulid(id_):
        raise ValueError(
            f"Refusing to store invalid ULID in ingested_ids (len={len(id_)}): {id_!r}"
        )


@dataclass
class Profile:
    """Local identities, trusted peers, relays and packet-ledger state.

    Read and written by :mod:`aya.adapters.profile_store`, which resolves the
    file under ``AYA_HOME`` (``~/.aya/profile.json`` by default). This class
    holds the data and the rules over it — instance resolution, relay
    ordering, trust checks — and knows nothing about storage.
    """

    instances: dict[str, Identity] = field(default_factory=dict)
    # Label of the instance to act as when ``--as``/``instance`` is omitted.
    # Without it, a profile holding both a real instance and a leftover
    # ``default`` stub silently resolves to the stub, whose Nostr keypair
    # differs — every poll then returns empty with exit 0.
    primary_instance: str | None = None
    trusted_keys: dict[str, TrustedKey] = field(default_factory=dict)
    default_relays: list[str] = field(default_factory=lambda: list(_DEFAULT_RELAYS))
    last_checked: dict[str, str] = field(default_factory=dict)  # relay → ISO timestamp
    # {id, ingested_at, from_did?} — dedup
    ingested_ids: list[dict[str, str]] = field(default_factory=list)
    # Outbound log: {id, sent_at, to_did, to_label, intent, event_id,
    # relays_ok, relays_failed}. `aya send` used to leave no local trace, so
    # "did that actually go out, and to which relays?" was unanswerable.
    sent_ids: list[dict[str, Any]] = field(default_factory=list)
    # Packet IDs explicitly dropped from inbox view (e.g. bad-sig packets,
    # spam, anything the user wants to ignore permanently). Filtered out of
    # `aya inbox` listings on every poll.
    dropped_ids: list[str] = field(default_factory=list)

    def add_relay(self, url: str, *, first: bool = False) -> bool:
        """Ensure *url* is in ``default_relays``. Returns True if the list changed.

        With ``first=True`` the relay is moved to the front even when already
        present — "make this the primary relay" must hold regardless of where
        it started, since polling order is what decides reachability.
        """
        relays = list(self.default_relays)
        if not first:
            if url in relays:
                return False
            relays.append(url)
        else:
            if relays[:1] == [url]:
                return False
            relays = [url, *(u for u in relays if u != url)]
        self.default_relays = relays
        return True

    def resolve_instance_name(self, requested: str | None) -> tuple[str, str]:
        """Resolve *requested* to a registered instance label.

        Returns ``(label, reason)`` where *reason* explains which rule applied —
        callers surface it so a resolved identity is never a silent guess.

        Raises :class:`InstanceResolutionError` when the choice is ambiguous.
        Ambiguity must be an error: picking arbitrarily yields a wrong-keypair
        poll that looks exactly like an empty inbox.
        """
        available = list(self.instances.keys())
        if not available:
            raise InstanceResolutionError(
                "No instances registered. Run 'aya init' first.", available, requested
            )

        if requested is not None:
            if requested in self.instances:
                return requested, "explicit"
            # Single-instance profiles: honour the long-standing smart default.
            if len(available) == 1:
                return available[0], "only-instance"
            raise InstanceResolutionError(
                f"Instance '{requested}' not found. Available: {', '.join(available)}.",
                available,
                requested,
            )

        if self.primary_instance and self.primary_instance in self.instances:
            return self.primary_instance, "primary_instance"
        if len(available) == 1:
            return available[0], "only-instance"
        # A leftover 'default' stub alongside exactly one real instance is the
        # common shape after `aya init --label <name>`; prefer the real one.
        non_stub = [name for name in available if name != "default"]
        if len(non_stub) == 1:
            return non_stub[0], "sole-non-default"
        raise InstanceResolutionError(
            "Multiple instances registered and no primary set — pass --as <label> "
            f"or run 'aya use <label>' to set one. Available: {', '.join(available)}.",
            available,
            requested,
        )

    def is_trusted(self, did: str) -> bool:
        return did in {k.did for k in self.trusted_keys.values()}
