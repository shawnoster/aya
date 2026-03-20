"""Identity management — did:key generation, keypair storage, trusted key registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import base58
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Multicodec prefix for ed25519 public keys: 0xed 0x01
_ED25519_MULTICODEC = bytes([0xED, 0x01])


@dataclass
class Identity:
    """A local assistant instance identity."""

    did: str
    label: str  # "work", "home", "laptop", etc.
    private_key_hex: str
    public_key_hex: str

    @classmethod
    def generate(cls, label: str) -> Identity:
        """Generate a new ed25519 keypair and derive a did:key DID."""
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes_raw()
        priv_bytes = private_key.private_bytes_raw()

        multicodec = _ED25519_MULTICODEC + pub_bytes
        did = "did:key:z" + base58.b58encode(multicodec).decode()

        return cls(
            did=did,
            label=label,
            private_key_hex=priv_bytes.hex(),
            public_key_hex=pub_bytes.hex(),
        )

    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.private_key_hex))

    def public_key(self) -> Ed25519PublicKey:
        return self.private_key().public_key()

    def sign(self, data: bytes) -> bytes:
        return self.private_key().sign(data)

    def nostr_pubkey(self) -> str:
        """Hex-encoded public key for Nostr protocol use."""
        return self.public_key_hex


@dataclass
class TrustedKey:
    did: str
    label: str  # "home", "friend:alice", etc.
    nostr_pubkey: str | None = None


@dataclass
class Profile:
    """
    Persistent assistant profile — personality + identity.
    Stored at ~/.copilot/assistant_profile.json (or configured path).
    """

    alias: str
    ship_mind_name: str
    user_name: str
    instances: dict[str, Identity] = field(default_factory=dict)
    trusted_keys: dict[str, TrustedKey] = field(default_factory=dict)
    default_relay: str = "wss://relay.damus.io"
    last_checked: dict[str, str] = field(default_factory=dict)  # relay → ISO timestamp

    @classmethod
    def load(cls, path: Path) -> Profile:
        """Load from assistant_profile.json, merging ace-sync fields if present."""
        data = json.loads(path.read_text())
        instances = {
            k: Identity(**v)
            for k, v in data.get("ace_sync", {}).get("instances", {}).items()
        }
        trusted = {
            k: TrustedKey(**v)
            for k, v in data.get("ace_sync", {}).get("trusted_keys", {}).items()
        }
        return cls(
            alias=data.get("alias", "Ace"),
            ship_mind_name=data.get("ship_mind_name", ""),
            user_name=data.get("user_name", ""),
            instances=instances,
            trusted_keys=trusted,
            default_relay=data.get("ace_sync", {}).get("default_relay", "wss://relay.damus.io"),
            last_checked=data.get("ace_sync", {}).get("last_checked", {}),
        )

    def save(self, path: Path) -> None:
        """Write ace-sync fields back into the profile without clobbering other keys."""
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault("ace_sync", {})
        data["ace_sync"]["instances"] = {
            k: {
                "did": v.did,
                "label": v.label,
                "private_key_hex": v.private_key_hex,
                "public_key_hex": v.public_key_hex,
            }
            for k, v in self.instances.items()
        }
        data["ace_sync"]["trusted_keys"] = {
            k: {"did": v.did, "label": v.label, "nostr_pubkey": v.nostr_pubkey}
            for k, v in self.trusted_keys.items()
        }
        data["ace_sync"]["default_relay"] = self.default_relay
        data["ace_sync"]["last_checked"] = self.last_checked
        path.write_text(json.dumps(data, indent=2))

    def active_instance(self, label: str = "default") -> Identity | None:
        return self.instances.get(label) or next(iter(self.instances.values()), None)

    def is_trusted(self, did: str) -> bool:
        return did in {k.did for k in self.trusted_keys.values()}
