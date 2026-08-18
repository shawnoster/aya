# Architecture

## System Overview

aya is a personal AI assistant toolkit that spans multiple machines. Each machine runs its own assistant instance with its own context, connected by signed async packets through Nostr relays.

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│         MACHINE A               │     │         MACHINE B               │
│                                 │     │                                 │
│  ┌───────────┐  ┌────────────┐  │     │  ┌───────────┐  ┌────────────┐ │
│  │ Claude    │  │ aya CLI   │  │     │  │ Claude    │  │ aya CLI   │ │
│  │ Code      │──│ + Plugin   │  │     │  │ Code      │──│ + Plugin   │ │
│  └─────┬─────┘  └─────┬──────┘  │     │  └─────┬─────┘  └─────┬──────┘ │
│        │              │         │     │        │              │        │
│  ┌─────┴──────────────┴──────┐  │     │  ┌─────┴──────────────┴──────┐ │
│  │      Workspace            │  │     │  │      Workspace            │ │
│  │  Projects, notes, code    │  │     │  │  Projects, notes, code    │ │
│  └───────────────────────────┘  │     │  └───────────────────────────┘ │
│                                 │     │                                │
│  ┌───────────────────────────┐  │     │  ┌───────────────────────────┐ │
│  │ Profile (~/.aya/)         │  │     │  │ Profile (~/.aya/)         │ │
│  │   profile.json            │  │     │  │   profile.json           │ │
│  │   ├── label: "alice"      │  │     │  │   ├── label: "bob"       │ │
│  │   ├── did:key (ed25519)   │  │     │  │   ├── did:key (ed25519)  │ │
│  │   ├── nostr (secp256k1)   │  │     │  │   ├── nostr (secp256k1)  │ │
│  │   └── trusted_keys:[bob]  │  │     │  │   └── trusted_keys:[alice]│
│  └───────────────────────────┘  │     │  └───────────────────────────┘ │
└──────────────┬──────────────────┘     └──────────────┬─────────────────┘
               │                                       │
               │         ┌───────────────┐             │
               │         │  Nostr Relay  │             │
               └────────►│  (nos.lol /   │◄────────────┘
                         │  relay.damus) │
                         │               │
                         │  kind: 5999   │
                         │  NIP-44 E2E   │
                         │  encrypted    │
                         └───────────────┘
```

Labels can be anything: `home`/`work` for personal multi-machine setups, first names for sharing with friends or coworkers, hostnames for server fleets.

## Identity Model

Each instance has two keypairs serving different purposes:

```
┌─────────────────────────────────────────────────┐
│                   Identity                       │
│                                                  │
│  ┌─────────────────────┐  ┌──────────────────┐  │
│  │  did:key (ed25519)  │  │ Nostr (secp256k1)│  │
│  │                     │  │                  │  │
│  │  • W3C standard     │  │  • BIP-340       │  │
│  │  • Packet signing   │  │    Schnorr sigs  │  │
│  │  • Identity proof   │  │  • Relay         │  │
│  │  • Works offline    │  │    transport     │  │
│  │  • Zero infra       │  │  • Event routing │  │
│  └─────────────────────┘  └──────────────────┘  │
│                                                  │
│  Trust: explicit registry in profile             │
│  Pairing: relay-mediated short code exchange     │
└─────────────────────────────────────────────────┘
```

## Packet Lifecycle

```
SENDER (alice)                   RELAY                    RECEIVER (bob)
──────────────                   ─────                    ──────────────

1. User: "send this to bob"
   │
2. Assistant gathers context
   │
3. aya send
   ├── Create JSON envelope
   ├── Sign with ed25519
   ├── Set TTL, intent, conflict strategy
   ├── Encrypt content (NIP-44 ECDH + ChaCha20)
   ├── Wrap in Nostr event (kind 5999)
   ├── Sign with secp256k1 (Schnorr)
   └── Publish to relay ──────────────► 4. Relay stores event
                                           tagged with
                                           recipient pubkey
                                           (content is encrypted)
                                                │
                         5. SessionStart hook ◄──┘
                            aya receive --quiet
                            │
                         6. Query relay for
                            packets to my pubkey
                            │
                         7. Decrypt content
                            (NIP-44 ECDH)
                            │
                         8. Verify ed25519
                            signature
                            │
                         9. Surface to user
                            "1 packet from alice"
                            │
                        10. User approves
                            (or auto-ingest
                             if trusted)
                            │
                        11. Ingest into context
```

## Pairing Flow

```
MACHINE A (alice)                RELAY                    MACHINE B (bob)
─────────────────                ─────                    ───────────────

1. aya pair --peer bob
   │
2. Generate code: ANCHOR-NORTH-0045
   │
3. Hash code (SHA-256)
   │
4. Publish pair-request ────────► 5. Stored with
   (kind 5999, tag: as-pair-req)     code hash tag
   │
6. Display code to user                              7. User enters code
   "ANCHOR-NORTH-0045"                                  aya pair --code
                                                        ANCHOR-NORTH-0045
                                                        --peer alice
                                                        │
                                 8. Query by ◄────── 9. Hash code, query
                                    code hash           for matching request
                                        │
                                        └──────────► 10. Found! Extract
                                                         alice's DID + pubkey
                                                         │
                                 11. Stored ◄─────── 12. Publish pair-response
                                                         (kind 5999, tag:
                                                          as-pair-resp)
13. Poll finds response ◄───────
    │
14. Extract bob's DID + pubkey
    │
15. Both instances now trust              16. Both instances now trust
    each other                                each other
```

## Adaptive Commands

Skills adapt to available integrations — the same command produces different output depending on what's connected:

```
┌──────────────────────────────────────────────────────┐
│              Adaptive Briefing                       │
│                                                      │
│  1. Detect available data sources                    │
│     `aya status --json`                              │
│                                                      │
│  2. Branch by what's available:                      │
│                                                      │
│  ┌─────────────────────┐  ┌────────────────────────┐ │
│  │  Full (many MCPs)   │  │  Light (minimal MCPs)  │ │
│  │                     │  │                        │ │
│  │  • Issue tracker    │  │  • Calendar            │ │
│  │  • GitHub PRs       │  │  • aya inbox           │ │
│  │  • Messaging        │  │  • Project status      │ │
│  │  • Calendar         │  │  • Scheduler           │ │
│  │  • aya inbox        │  │                        │ │
│  │  • Project status   │  │                        │ │
│  │  • Scheduler        │  │                        │ │
│  └─────────┬───────────┘  └───────────┬────────────┘ │
│            │                          │              │
│            ▼                          ▼              │
│  Full briefing with          Light briefing with     │
│  tiered priorities           projects + todos        │
└──────────────────────────────────────────────────────┘
```

## Setup Flow

aya is a CLI tool — workspace scaffolding is your responsibility, not aya's. Set up a new machine by installing aya and initializing identity:

```
Fresh machine
     │
     ▼
uv tool install aya-ai-assist   # install aya globally
     │
     ▼
aya init --label <your-label>
     │
     ▼
aya pair --code <CODE> --peer <other-label>   # exchange trust with another instance
     │
     ▼
Ready. Packets auto-surface at session start.
```

Workspace structure (CLAUDE.md, AGENTS.md, skills, hooks) is defined in your workspace and maintained there — not by aya.

## Component Map

Layered inward to outward. Source dependencies point inward only, and the
boundaries are enforced by `tests/test_architecture.py` — not left to
convention.

```
src/aya/
├── entities/           rules that hold without this application; no I/O
│   ├── packet.py       Packet, ContentType, ConflictStrategy, signing
│   ├── identity.py     Identity, TrustedKey, Profile
│   └── encryption.py   NIP-44 v2
│
├── usecases/           what aya does; no printing, no exit codes
│   ├── relay_ops.py    send / ack / receive / inbox, once for both surfaces
│   ├── ingest.py       persist a packet, alert on seeds
│   ├── triage.py       which fetched packets to act on
│   ├── packet_view.py  how a packet is projected for reading, once for both surfaces
│   ├── resolve.py      instance, recipient, relay and label resolution
│   ├── pair.py         the pairing exchange
│   ├── watch_chains.py multi-stage watches that advance as stages complete
│   ├── status.py       gather workspace readiness (facts only)
│   ├── context.py      context-block builder
│   └── log.py          daily-notes logger
│
├── adapters/           everything that touches the outside world
│   ├── cli/            driving: the Typer app
│   │   ├── _kernel.py    app, sub-apps, output formats, error codes
│   │   ├── _render.py    all terminal output
│   │   ├── send_cmds.py  send, send-raw, ack
│   │   ├── poll_cmds.py  receive, inbox
│   │   ├── packet_cmds.py read, drop, sent, packets
│   │   ├── pair_cmds.py  pair
│   │   ├── schedule_cmds.py, config_cmds.py, identity_cmds.py,
│   │   └── hook_cmds.py, workspace_cmds.py
│   ├── mcp_server.py   driving: MCP tools over stdio
│   ├── status_view.py  presenters for `aya status` (json / plain / rich)
│   ├── relay.py        driven: Nostr transport
│   ├── clock.py        driven: the system clock, in one place
│   ├── paths.py        driven: AYA_HOME resolution, on access
│   ├── atomic.py       driven: file lock + atomic replace
│   ├── profile_store.py driven: load/save profile.json
│   ├── ledger.py       driven: ingested / sent / dropped logs
│   ├── outbox.py       driven: idempotency, delivery, sent log
│   ├── config.py       driven: workspace config
│   ├── credentials.py  driven: credential checks
│   ├── install.py      driven: crontab + Claude Code hooks
│   └── rewake.py       driven: asyncRewake for PostToolUse watch hits
│
└── scheduler/          bounded subsystem, layered internally
    ├── core.py         CRUD, poll, tick, pending, watch validation
    ├── storage.py      persistence, locking, atomic writes
    ├── providers.py    github-pr, jira, ci-checks, relay-inbox pollers
    ├── display.py      alert rendering
    ├── time_utils.py   due-date parsing, timezones
    └── types.py        SchedulerItem, AlertItem, SuppressedCron
```

The two driving adapters are peers: each parses its own input, calls a use
case, and renders the result. Neither imports the other — `cli` imports
`mcp_server` in one direction only, to start it.

### Why the layers

`send`, `ack`, `receive` and `inbox` used to exist twice, once per surface.
The copies drifted: read receipts fired on one of four ingest paths, one
surface encrypted acks and the other did not, one honoured `--dismiss` and
the other hardcoded it, and a packet dropped with `aya drop` was silently
re-ingested by the next poll. Every one of those was the same shape — one
rule, written more than once. The use-case layer exists so there is one
place for each to be written.

## Security Model

```
┌─────────────────────────────────────────────┐
│              Security Layers                 │
│                                              │
│  1. Signature verification                   │
│     └── Packet from known did:key?           │
│                                              │
│  2. Trust registry                           │
│     └── DID in trusted_keys list?            │
│                                              │
│  3. User approval                            │
│     └── Always surface before ingest         │
│         (unless --auto-ingest from trusted)   │
│                                              │
│  4. Role separation                          │
│     └── Packet content = user role context   │
│         Never system instructions            │
│                                              │
│  5. End-to-end encryption (default)           │
│     └── NIP-44 v2: ECDH + ChaCha20 + HMAC   │
│         Relay sees size + metadata only      │
│                                              │
│  6. TTL / expiration                         │
│     └── Packets expire (default 7 days)      │
│         Relay discards after expiration      │
└─────────────────────────────────────────────┘
```
