# Webhook/Push Support & Always-On Aya

**Issue:** #158 (parent), #185 (chains), #186 (always-on), #187 (noise reduction)
**Date:** 2026-04-03
**Status:** Design approved, pending implementation plan

## Summary

Evolve aya from a REPL-bound polling tool into a persistent assistant layer
that can receive events, accept input from anywhere (mobile, voice, share
sheet), and run autonomous multi-stage workflows (watch chains).

**Approach:** Hybrid — local aya server for execution + stateless cloud bridge
for inbound connectivity.

## System Architecture

Three layers, each independently deployable:

```
┌─────────────────────────────────────────────────────┐
│  Input surfaces                                      │
│  (GitHub webhooks, iOS Shortcuts, Telegram bot,      │
│   Siri voice, share sheet)                           │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS POST
                       ▼
┌─────────────────────────────────────────────────────┐
│  Cloud Bridge (stateless)                            │
│  - Receives inbound webhooks + mobile inputs         │
│  - Validates sender (API key / signature)            │
│  - Translates to Nostr event                         │
│  - Forwards to relay                                 │
│  No state. No execution. Protocol translation only.  │
└──────────────────────┬──────────────────────────────┘
                       │ Nostr relay
                       ▼
┌─────────────────────────────────────────────────────┐
│  Aya Server (local, persistent)                      │
│  - Listens on Nostr relay for events                 │
│  - Runs watch chains (state machine)                 │
│  - Manages action queue                              │
│  - Spawns Claude Code sessions (headless) for work   │
│  - Falls back to polling when no push available      │
│  - Serves local HTTP for REPL ↔ server interaction   │
└─────────────────────────────────────────────────────┘
```

**Without the bridge:** Everything still works. Watches poll (current
behavior). Mobile capture isn't available. The bridge is an accelerator,
not a dependency.

**REPL ↔ server:** The local aya server exposes a localhost API. The REPL
session queries it for events, pushes state to it, and receives events
without cron noise — replacing the current `aya schedule tick` cron approach
during active sessions.

## Cloud Bridge

A single stateless container (FastAPI, ~200 lines) deployed to a free tier
(Fly.io, Railway, or Cloudflare Workers).

### Responsibilities

1. **Webhook receiver** — GitHub sends PR/check events here. Bridge verifies
   `X-Hub-Signature-256`, extracts relevant fields (repo, PR number, action,
   state), wraps as a Nostr event, publishes to relay.

2. **Mobile input endpoint** — `POST /inbox` accepts JSON
   `{ "type": "note|todo|calendar|thought", "body": "...", "project": "optional" }`.
   Authenticated via API key in header. Bridge wraps as Nostr event, publishes
   to relay.

3. **Voice endpoint** — `POST /voice` accepts audio file. Bridge transcribes
   (Whisper API or local whisper.cpp if self-hosted), then routes through the
   same `/inbox` path.

### What it does NOT do

- Store state
- Execute actions
- Make decisions about what to do with events
- Know about watch chains

### Auth

- API key for mobile endpoints (generated at `aya bridge init`, stored in profile)
- GitHub webhook secret for signature verification
- Nostr event signing with the bridge's own keypair (trusted by receiving aya instance)

### CLI

```bash
aya bridge deploy                        # provision container, print URL
aya bridge status                        # health check
aya bridge configure-github owner/repo   # register webhook URL on the repo
```

For others: `aya bridge deploy` handles provisioning. Or self-host the
container anywhere. Or skip it entirely and stay on polling.

## Aya Server (local persistent process)

### Lifecycle

```bash
aya serve                  # foreground (dev/debug)
aya serve --daemon         # background, or managed by systemd/launchd
aya serve stop             # graceful shutdown
aya serve status           # is it running, what's it doing
```

### Responsibilities

**A. Event listener** — Maintains a persistent Nostr subscription. When an
event arrives (webhook, mobile input, relay packet), it classifies and routes:
- Webhook event → check against active watch chains, advance if matched
- Inbox item → append to `notebook/inbox.md`
- Relay packet → ingest (same as `aya receive --auto-ingest`)

**B. Watch chain engine** — Runs chain state machines. Checks conditions,
advances stages, triggers actions. Polls as fallback for watches without push
events.

**C. Action queue** — When a chain stage triggers an action, the server either:
- Spawns a headless Claude Code session via the SDK if autonomous execution
  is allowed for that step
- Queues it for the next REPL session if the step requires human confirmation
- Sends a heartbeat notification regardless

**D. Local API** — `localhost:PORT` for REPL interaction:
- `GET /events` — pending events since last check (replaces cron tick noise)
- `POST /chain` — register a new chain
- `GET /chain/:id` — chain status
- `GET /health` — server liveness

### REPL integration

When a REPL session starts, it checks `aya serve status`. If the server is
running, the session pulls events from the local API instead of running
`aya schedule tick`. No more cron alerts dropping mid-session — the REPL asks
for events at natural breakpoints (between tasks, at session start/end).

When the server isn't running, falls back to current behavior — cron tick,
polling. Nothing breaks.

## Watch Chains

A chain is an ordered list of stages. Each stage has a condition to wait for,
an action to take when met, and an autonomy level.

### Definition format

```yaml
chain: "ship-pr"
source: "PR #190"
stages:
  - name: wait-for-review
    watch: github-pr owner/repo#190
    condition: has_comments
    action: notify

  - name: address-feedback
    action: dispatch           # spawn Claude Code: /address-pr-feedback 190
    autonomy: autonomous

  - name: wait-for-approval
    watch: github-pr owner/repo#190
    condition: approved_or_merged
    action: notify

  - name: wait-for-merge
    watch: github-pr owner/repo#190
    condition: merged
    action: notify

  - name: wait-for-deploy-dev
    watch: github-check owner/repo@main
    condition: deploy_dev_succeeded
    action: notify

  - name: wait-for-deploy-prod
    watch: github-check owner/repo@main
    condition: deploy_prod_succeeded
    action: notify
    autonomy: notify-only
```

### Stage types

- **watch** — wait for a condition on an external system (existing provider
  model, extended)
- **dispatch** — spawn a Claude Code session with a task, runs headless via SDK
- **notify** — send a heartbeat
- **gate** — pause and ask the human before proceeding

### Autonomy per stage

- `autonomous` — execute action without asking (default)
- `confirm` — notify and wait for explicit go-ahead
- `notify-only` — tell the human, don't act

### Heartbeat

While a chain is active, the server sends periodic status updates at a
configurable interval (default: every 2 hours). Delivered via alert when REPL
opens, or push notification if mobile is set up.

### CLI

```bash
aya chain start ship-pr --pr owner/repo#190    # start from template
aya chain status                                # all active chains
aya chain status <id>                           # detail view
aya chain advance <id>                          # manually advance
aya chain cancel <id>                           # stop a chain
```

Templates like "ship-pr" are pre-defined in `~/.aya/chain-templates/` as
YAML files. `aya chain start <template>` copies the template, substitutes
parameters, and registers it as an active chain in `~/.aya/chains.json`.
Custom one-off chains can also be built inline via `aya chain create`.

## Mobile Input Surfaces

Three input paths, all funneling through the cloud bridge's `/inbox` endpoint
into `notebook/inbox.md`:

### A. iOS Shortcuts / Share Sheet

- Shortcut sends `POST /inbox` with API key header
- "Share to aya" action available in the share sheet — captures URL, text,
  image (as description)
- Pre-built shortcuts for common actions:
  - "Quick note" — text input → type: note
  - "Todo" — text input → type: todo
  - "Calendar" — text + date → type: calendar
  - "Project thought" — text + project picker → type: thought
- `aya bridge shortcuts` generates the Shortcut files with the bridge URL and
  API key baked in

### B. Telegram Bot

- Bot runs inside the cloud bridge (or as a sidecar)
- Conversational — text it naturally: "remind me to follow up on the
  electrician invoice tomorrow"
- Classifies intent (note, todo, calendar, fetch) and routes:
  - Capture types → `/inbox` → Nostr → aya server → notebook
  - Fetch requests → `/query` → Nostr → aya server reads notebook/projects →
    replies back through relay → bot responds
- Authenticated by Telegram user ID allowlist
- Lightweight — no AI in the bot, just pattern matching for routing. Ambiguous
  messages land as raw notes in inbox for later triage

### C. Voice (Siri)

- Siri Shortcut captures voice memo → sends audio to `POST /voice`
- Bridge transcribes (Whisper API) → routes through `/inbox` as text
- Same classification as Telegram: note, todo, calendar, thought
- Transcription result returned to Siri for confirmation

### Inbox entry format

All surfaces produce the same format:
```markdown
- [2026-04-03 14:22] (mobile/telegram) Follow up on electrician invoice tomorrow
  tags: todo
```

Triage happens later — either `/triage` in a REPL session, or the aya server
auto-routes obvious types (calendar → calendar event, todo → todos.md).

## Noise Reduction (ships first, independent)

### Problem

`aya schedule tick` runs on cron every 5 minutes. During an active REPL
session, the SessionStart hook calls `aya schedule pending`, which dumps
alerts into the conversation — even mid-thought, even when nothing actionable
changed.

### A. Session-aware delivery

When the REPL is active, stop delivering via cron. The REPL pulls events at
natural breakpoints:
- Session start (already happens)
- Between tasks (after `/finish` or `/next`)
- Session end
- On explicit ask ("any alerts?")

Implementation: a flag in the scheduler that says "a REPL is active, suppress
cron delivery." The REPL sets it on start, clears it on exit.

### B. Alert filtering

Add `severity` to alerts:
- `actionable` — something changed that needs a response
- `info` — status update, no action needed
- `heartbeat` — periodic chain status

During active sessions, only `actionable` alerts deliver immediately. `info`
and `heartbeat` batch until the next natural breakpoint or session end.

## Out of Scope

- **AI in the bridge** — Bridge is dumb. No LLM calls. Intelligence lives in
  the aya server or REPL sessions.
- **Multi-user** — Personal tool. One user, two machines. No auth beyond API
  keys and Nostr keypairs.
- **Custom webhook providers beyond GitHub** — Start with GitHub. Jira
  webhooks, deploy status, etc. come later as providers using the same
  infrastructure.
- **Mobile app** — No native app. Shortcuts + Telegram + voice covers it.
- **Bridge HA / scaling** — Single container, free tier. If it goes down, aya
  falls back to polling. No redundancy needed.

## Delivery Order

1. **Noise reduction** (#187) — session-aware delivery + alert filtering.
   No new infrastructure. Ships first.
2. **Aya server** (#186) — `aya serve`, local API, REPL integration, event
   listener. Foundation for everything else.
3. **Watch chains** (#185) — chain state machine, templates, CLI. Requires
   the server.
4. **Cloud bridge** (#158) — stateless webhook/mobile forwarder. Requires
   the server to receive events.
5. **Mobile surfaces** — Shortcuts, Telegram bot, voice. Requires the bridge.
