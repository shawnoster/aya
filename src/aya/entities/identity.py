"""Identity management — did:key generation, keypair storage, trusted key registry."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import base58
from coincurve import PrivateKey as Secp256k1PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from ulid import ULID

from aya.adapters.atomic import atomic_write_json, file_lock
from aya.adapters.ledger import Ledger

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


def _profile_lock_path(profile_path: Path) -> Path:
    """Lock co-located with the profile, so a custom --profile locks itself."""
    return profile_path.parent / ".profile.lock"


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


def _normalize_ingested_ids(raw: object) -> list[dict[str, str]]:
    """Keep only entries whose ``id`` is a valid 26-character ULID.

    A truncated display prefix stored here would never match a real packet ID,
    so the entry would silently fail to dedup.
    """
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        entry_id = entry.get("id", "")
        if not _is_valid_ulid(entry_id):
            logger.warning("Dropping ingested_id with invalid ULID: %r", entry_id)
            continue
        result.append(entry)
    return result


def _normalize_dropped_ids(raw: object) -> list[str]:
    """Validate and coerce ``dropped_ids`` from a profile load.

    Defensive against corrupted or hand-edited profiles where the field
    might be a dict, string, or other non-list value (which would
    silently iterate keys/characters and persist garbage). Returns a
    list of valid ULID strings; logs a warning when the stored value
    has the wrong type.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        logger.warning(
            "Profile dropped_ids has invalid type %s (expected list); resetting to empty.",
            type(raw).__name__,
        )
        return []
    result: list[str] = []
    for entry in raw:
        if isinstance(entry, str) and _is_valid_ulid(entry):
            result.append(entry)
        else:
            logger.warning(
                "Dropping dropped_ids entry with invalid value: %r",
                entry,
            )
    return result


@dataclass
class Profile:
    """
    Persistent assistant profile — personality + identity.
    Stored at ~/.copilot/assistant_profile.json (or configured path).
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

    @classmethod
    def load(cls, path: Path) -> Profile:
        """Load from assistant_profile.json.


        Validates profile structure and logs warnings for deprecated keys or malformed data.
        """
        logger.debug("Loading profile from %s", path)
        data = json.loads(path.read_text())
        # Migrate profiles written by older versions (assistant_sync → aya)
        aya_data = data.get("aya", {})

        # Forward compatibility: warn if schema is newer than expected
        if isinstance(aya_data, dict):
            raw_version = aya_data.get("schema_version", 0)
            file_version = raw_version if isinstance(raw_version, int) else 0
            if not isinstance(raw_version, int) and raw_version is not None:
                logger.warning(
                    "profile has non-integer schema_version: %r — treating as 0", raw_version
                )
            if file_version > PROFILE_SCHEMA_VERSION:
                logger.warning(
                    "profile schema_version %d > expected %d",
                    file_version,
                    PROFILE_SCHEMA_VERSION,
                )

        # Validate aya_data is a dict before calling methods on it
        if not isinstance(aya_data, dict):
            raise ValueError(
                f"Profile 'aya' section must be a dictionary, got {type(aya_data).__name__}. "
                "Profile may be corrupted."
            )

        # Load and validate instances
        instances = {}
        instances_data = aya_data.get("instances", {})
        if not isinstance(instances_data, dict):
            raise ValueError(
                f"Profile 'instances' must be a dictionary, got {type(instances_data).__name__}"
            )
        for k, v in instances_data.items():
            if not isinstance(v, dict):
                raise ValueError(f"Instance '{k}' must be a dictionary, got {type(v).__name__}")
            # Migrate old profiles missing Nostr keys
            if "nostr_private_hex" not in v:
                nostr_secret = secrets.token_bytes(32)
                nostr_key = Secp256k1PrivateKey(nostr_secret)
                nostr_pub_xonly = nostr_key.public_key.format(compressed=True)[1:]
                v["nostr_private_hex"] = nostr_secret.hex()
                v["nostr_public_hex"] = nostr_pub_xonly.hex()
            try:
                instances[k] = _validate_instance(k, v)
            except ValueError as e:
                logger.error("Profile validation error: %s", e)
                raise

        # Load and validate trusted keys
        trusted = {}
        trusted_keys_data = aya_data.get("trusted_keys", {})
        if not isinstance(trusted_keys_data, dict):
            raise ValueError(
                f"Profile 'trusted_keys' must be a dict, got {type(trusted_keys_data).__name__}"
            )
        for k, v in trusted_keys_data.items():
            if not isinstance(v, dict):
                raise ValueError(f"Trusted key '{k}' must be a dictionary, got {type(v).__name__}")
            try:
                trusted[k] = _validate_trusted_key(k, v)
            except ValueError as e:
                logger.error("Profile validation error: %s", e)
                raise

        # Support both default_relays (list) and legacy default_relay (string).
        # Coerce a bare string to a list, strip non-string entries, fall back to
        # _DEFAULT_RELAYS if the result is empty or the key is missing entirely.
        raw_relays = aya_data.get("default_relays")
        relays = (
            [u for u in raw_relays if isinstance(u, str) and u.strip()]
            if isinstance(raw_relays, list)
            else []
        ) or list(_DEFAULT_RELAYS)

        ledger = Ledger.load()

        return cls(
            instances=instances,
            primary_instance=(
                aya_data.get("primary_instance")
                if isinstance(aya_data.get("primary_instance"), str)
                else None
            ),
            trusted_keys=trusted,
            default_relays=relays,
            last_checked=aya_data.get("last_checked", {}),
            ingested_ids=_normalize_ingested_ids(ledger.ingested),
            sent_ids=[
                e
                for e in ledger.sent
                if isinstance(e, dict) and _is_valid_ulid(str(e.get("id", "")))
            ],
            dropped_ids=_normalize_dropped_ids(ledger.dropped),
        )

    def save(self, path: Path) -> None:
        """Persist the profile, and the packet ledgers alongside it.

        The ledgers live in their own file with their own lock: they change on
        every poll, while this file holds private keys and changes rarely.
        Writing both together meant an empty ``aya receive`` rewrote the
        keystore just to move a cursor.

        The profile itself is only rewritten when its contents actually
        change, and always via an atomic replace under an exclusive lock — a
        crash mid-write previously truncated the sole copy of the identity.
        """
        logger.debug("Saving profile to %s", path)

        Ledger(
            ingested=self.ingested_ids,
            sent=self.sent_ids,
            dropped=self.dropped_ids,
        ).save()

        with file_lock(_profile_lock_path(path)):
            data = json.loads(path.read_text()) if path.exists() else {}
            before = json.dumps(data, sort_keys=True)

            aya = data.setdefault("aya", {})
            aya["schema_version"] = PROFILE_SCHEMA_VERSION
            aya["instances"] = {
                k: {
                    "did": v.did,
                    "label": v.label,
                    "private_key_hex": v.private_key_hex,
                    "public_key_hex": v.public_key_hex,
                    "nostr_private_hex": v.nostr_private_hex,
                    "nostr_public_hex": v.nostr_public_hex,
                }
                for k, v in self.instances.items()
            }
            if self.primary_instance:
                aya["primary_instance"] = self.primary_instance
            else:
                aya.pop("primary_instance", None)
            aya["trusted_keys"] = {
                k: {"did": v.did, "label": v.label, "nostr_pubkey": v.nostr_pubkey}
                for k, v in self.trusted_keys.items()
            }
            aya["default_relays"] = self.default_relays
            aya["last_checked"] = self.last_checked

            if json.dumps(data, sort_keys=True) == before:
                return
            atomic_write_json(path, data, mode=0o600)

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
