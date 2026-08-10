"""Reading and writing ``profile.json``.

Persistence is a gateway concern, not an entity one. ``Profile`` used to load
and save itself, which meant the innermost layer imported the storage
primitives — an Active Record that inverted the dependency rule and made the
entity impossible to construct without touching disk.

The ledgers are written to their own file with their own lock: they change on
every poll, while this file holds private keys and changes rarely.
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

from coincurve import PrivateKey as Secp256k1PrivateKey

from aya.adapters.atomic import atomic_write_json, file_lock
from aya.adapters.ledger import Ledger
from aya.entities.identity import (
    _DEFAULT_RELAYS,
    PROFILE_SCHEMA_VERSION,
    Profile,
    _is_valid_ulid,
    _validate_instance,
    _validate_trusted_key,
)

logger = logging.getLogger(__name__)

__all__ = ["load_profile", "save_profile"]


def _profile_lock_path(profile_path: Path) -> Path:
    """Lock co-located with the profile, so a custom --profile locks itself."""
    return profile_path.parent / ".profile.lock"


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


def load_profile(path: Path) -> Profile:
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

    return Profile(
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
            e for e in ledger.sent if isinstance(e, dict) and _is_valid_ulid(str(e.get("id", "")))
        ],
        dropped_ids=_normalize_dropped_ids(ledger.dropped),
    )


def save_profile(profile: Profile, path: Path) -> None:
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
        ingested=profile.ingested_ids,
        sent=profile.sent_ids,
        dropped=profile.dropped_ids,
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
            for k, v in profile.instances.items()
        }
        if profile.primary_instance:
            aya["primary_instance"] = profile.primary_instance
        else:
            aya.pop("primary_instance", None)
        aya["trusted_keys"] = {
            k: {"did": v.did, "label": v.label, "nostr_pubkey": v.nostr_pubkey}
            for k, v in profile.trusted_keys.items()
        }
        aya["default_relays"] = profile.default_relays
        aya["last_checked"] = profile.last_checked

        if json.dumps(data, sort_keys=True) == before:
            return
        atomic_write_json(path, data, mode=0o600)
