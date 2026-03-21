# helm

**Personal AI assistant toolkit.**

`helm` is a CLI for managing your AI assistant across machines — sync context between instances, schedule reminders, and bootstrap new workspaces.

## Install

```bash
git clone https://github.com/shawnoster/helm.git
cd helm
uv sync
```

## Quick start

```bash
# Bootstrap a workspace
uv run helm bootstrap --root ~

# Set up identity
uv run helm init --label work

# Pair with another machine
uv run helm pair --label work        # shows a code
uv run helm pair --code WORD-WORD-0000 --label home  # on the other machine

# Send a packet
echo "Hello from work" | uv run helm pack --to home --intent "test" | uv run helm send /dev/stdin

# Check inbox
uv run helm inbox
```

## Commands

| Command | What it does |
| ---- | ---- |
| `helm init` | Generate identity keypair for this instance |
| `helm pair` | Pair two instances via short-lived relay code |
| `helm trust` | Manually trust a DID |
| `helm pack` | Create a signed knowledge packet |
| `helm send` | Publish a packet to a Nostr relay |
| `helm inbox` | List pending packets |
| `helm receive` | Review and ingest packets |

## How it works

- **Identity**: `did:key` (ed25519) for packet signing + secp256k1 for Nostr transport
- **Transport**: Nostr relays (NIP-01, kind 5999) — async, federated, self-hostable
- **Packets**: Signed JSON envelopes with markdown content, TTL, and conflict strategies
- **Security**: Signature verification, user approval before ingest, trust registry

## License

MIT
