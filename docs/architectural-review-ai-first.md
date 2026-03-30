# Architectural Review: aya as an AI-First Tool with Human Oversight

**Date:** 2026-03-30  
**Status:** Research — no implementation expected  
**Scope:** Broad architectural review covering landscape, current design assessment, and directional options

---

## Table of Contents

1. [Landscape Summary](#1-landscape-summary)
2. [Current Architecture: Strengths and Weaknesses](#2-current-architecture-strengths-and-weaknesses)
3. [Directional Options](#3-directional-options)
4. [Recommended Direction](#4-recommended-direction)

---

## 1. Landscape Summary

### 1.1 Persistent AI Memory Tools

| Tool | Core Idea | Transport / Storage | AI Integration | Key Gap vs. aya |
|------|-----------|-------------------|---------------|-----------------|
| **mem0** | Hierarchical memory graph (user, session, agent layers); auto-extracts facts from conversation history | Postgres + vector DB (Qdrant/Chroma) + Redis | OpenAI-compatible API; SDKs for Python/Node; MCP server available | Cloud-centric; no offline-first or decentralized relay; no agent-to-agent sync; no scheduling |
| **Letta (MemGPT)** | Stateful LLM agents with paged in-memory "context windows"; memory blocks auto-summarised and recalled | SQLite (local) or managed cloud | REST API + Python SDK; first-class "agent" abstraction | Full agent runtime — much heavier than aya; not designed for cross-machine context sync; no decentralized transport |
| **OpenMem** | Open-source mem0 clone, self-hostable | Postgres + vector store | REST API | Minimal scheduling / dispatch; no relay model |
| **MCP Memory Server** (Anthropic reference) | Simple in-session key-value and entity graph over a local JSON/SQLite store | Local file; surfaced as MCP tools | Native MCP — zero-friction for Claude sessions | No cross-machine sync; ephemeral per-session unless user manages persistence |
| **Zep** | Session-aware long-term memory for LLM apps; extracts facts and temporal relationships | Postgres + custom graph | Python/Node SDK; REST | SaaS; closed transport; no relay concept |

**Gap aya fills:** None of these tools combine (a) identity-signed packets, (b) decentralized relay transport, (c) session-scoped scheduling with human-in-the-loop oversight, and (d) a dual-keypair trust model in a single installable CLI. aya's primary differentiation is the *signed async relay packet* as a first-class primitive — something the memory tools above treat as out-of-scope.

### 1.2 Agent-to-Agent Communication Protocols

| Protocol | Model | Status | Notes |
|----------|-------|--------|-------|
| **Google A2A (Agent-to-Agent)** | HTTP-based RPC; agents advertise an "Agent Card" (JSON) describing capabilities; tasks routed via structured messages | Open draft spec (2025) | Heavyweight for two-instance personal use; requires addressable HTTP endpoints — bad fit for intermittent laptop sessions |
| **Anthropic ACP (Agent Communication Protocol)** | Async message passing with attachments; agents identified by URI; messages carry structured `parts` (text, data, file) | Draft, experimental | Aligns well with aya's packet/intent model; attachments ≈ aya context blobs; no identity/trust layer defined yet |
| **OpenAI Swarm / Handoffs** | In-process agent delegation; not a network protocol | Stable (library) | Local only; no relay concept; not relevant to cross-machine use case |
| **CrewAI / LangGraph messaging** | In-process message buses between agents in a pipeline | Stable (libraries) | Same: local, not async relay |
| **ActivityPub** | Federated actor model; actors send/receive signed JSON-LD activities via inboxes/outboxes | W3C standard | Strong federation model; too heavyweight for two-device personal sync; actor/inbox model maps loosely to aya's sender/receiver pattern |

**Observation:** aya's packet model is conceptually closest to ACP "messages with parts" + ActivityPub's signed actor identity. Neither existing protocol provides aya's exact combination of features at personal scale.

### 1.3 Nostr-Native AI Tooling

Nostr as an AI transport is still nascent. Known efforts include:

- **NIP-90 (Data Vending Machines):** Defines a request/result pattern for off-loading computation to Nostr relay subscribers. Directionally interesting (AI task outsourcing over relay), but the request/result model is coarser than aya's signed-packet sessions.
- **Nostr MCP relays (experimental):** A handful of projects attempting to expose Nostr events as MCP tool calls. None production-ready as of early 2026.
- **kind 5999 (aya's current choice):** No formal NIP. aya uses an application-defined kind, which is pragmatic but limits interop if the broader Nostr ecosystem develops conflicting conventions.

### 1.4 Protocol Fit: Nostr vs. Alternatives

| Transport | Strengths | Weaknesses | Fit for aya |
|-----------|-----------|------------|-------------|
| **Nostr (current)** | Permissionless, censorship-resistant; relays cheap/plentiful; secp256k1 identity already in place; kind 5999 is working today | No message ordering guarantee; relays may drop events; no guaranteed delivery without ACK; two-keypair overhead (ed25519 + secp256k1); limited message size | **Good short-term.** Right level of decentralization for personal use. Upgrade path unclear. |
| **Matrix** | Federated; strong E2E encryption (MegOLM); persistent room history; room membership = trust | Homeserver required; higher ops burden; SDK is heavy; designed for multi-party chat not async packet relay | **Viable but complex.** Adds E2E encryption for free but requires homeserver. |
| **HTTPS relay (custom)** | Simple; reliable delivery; ACKs; dead simple client; works on every network | Centralized; requires hosting; no decentralized identity | **Practical for two-machine personal use** but loses the permissionless quality. |
| **Local SQLite sync** | Zero latency; no network required; trivially correct | Requires shared filesystem or explicit sync (git, syncthing); breaks for geographically separate machines | Only works as a cache layer, not primary transport. |
| **IPFS / libp2p** | Content-addressed; peer-to-peer | High complexity; slow content discovery; overkill for structured short messages | Not a good fit. |

**Verdict:** Nostr remains a reasonable transport choice for aya's use case *as long as* aya treats it as a transport detail, not a core identity primitive. The secp256k1 keypair should remain for Nostr signing, but aya's identity story (`did:key` ed25519) is already correctly decoupled. The biggest protocol risk is relay availability and lack of delivery guarantees — mitigated today by polling multiple relays.

### 1.5 AI Tool Design Patterns

Research into well-designed AI-consumed CLIs (based on tooling used by LLM agents in the wild — `gh`, `jq`, AWS CLI `--output json`, `kubectl`, Stripe CLI) surfaces the following patterns:

- **Machine-readable by default, human-readable on request:** `--format json` should be the *default* (or at least `--format` should always be available). Human-formatted Rich output is a debugging aid, not the primary interface.
- **Idempotent operations:** Every mutating command should be safe to call twice. Packet sending with content-addressed IDs, scheduler item idempotency keys, etc.
- **Structured exit codes:** Exit 0 = success + data. Exit 1 = error with structured error payload on stderr. Never mix machine-parseable output with error messages on the same stream.
- **Minimal required arguments:** Agents shouldn't need to track state to call a command. Commands that require a preceding step should accept that context inline.
- **Predictable side effects:** Avoid commands that implicitly mutate state without declaring it (e.g., `--auto-ingest` should always be explicit).
- **Version-stable schemas:** Output schemas should be versioned or at least additive. Agents break when field names change silently.

---

## 2. Current Architecture: Strengths and Weaknesses

### 2.1 Strengths

**Dual-keypair identity is a genuine asset.** The separation of `did:key` (ed25519, for packet signing and W3C interop) from Nostr's secp256k1 keypair (for relay transport) is architecturally sound. It lets aya stay transport-agnostic at the application level while using Nostr today. This is not something any of the comparable memory tools have considered.

**Packet model maps well to AI workflows.** The intent + conflict-strategy + TTL envelope is a thoughtful design. It encodes enough metadata for an AI agent to make autonomous decisions about how to handle incoming context without human direction. This is exactly what "AI-first" looks like at the protocol level.

**Session-scoped scheduling is uniquely positioned.** None of the landscape tools combine context sync with a scheduler. The ability to say "watch this PR and surface the result at my next session start" is a concrete, useful capability that falls outside what memory tools and A2A protocols offer.

**Human-in-the-loop is an explicit, first-class design choice.** The `--auto-ingest` flag with explicit trust gating, the `User approves` step in the packet lifecycle, and the session-surface-then-approve model are genuinely good defaults. Many AI tools skip this or make it an afterthought.

**Claude Code hook integration is a force multiplier.** `SessionStart` + `PreToolUse` + `PostToolUse` hooks, combined with pending alerts, recurring crons, and CI watching, make aya meaningfully *part of the AI session* rather than a background daemon the user has to remember to check.

### 2.2 Weaknesses

**CLI is the primary interface but was not designed for agent consumption.** The current CLI has rich human-formatted output by default. JSON output requires `--format json` flags and is inconsistently available across subcommands. An AI agent calling `aya status` or `aya schedule list` without JSON mode gets Rich-formatted terminal output that is fragile to parse. This is the single biggest AI-readiness gap.

**Two keypairs add friction without a clear payoff today.** The ed25519/secp256k1 dual-keypair model is future-proofing, but it adds cognitive overhead for users, doubles the identity surface, and complicates the pairing flow. Unless aya is actively using DID-based interop with other systems, the secp256k1 Nostr key *is* the identity from a user's perspective.

**No schema versioning.** Packets, scheduler items, and alerts lack versioned schemas. A field rename or structural change in a future aya version will silently break AI agents relying on the current output shape.

**Scheduler complexity has grown organically.** The scheduler handles reminders, recurring crons, watch providers (GitHub PR, Jira query, Jira ticket), idle back-off, work-hour windows, claim sweeping, and alert surfacing — all in a single 1,400-line file. This is functional but brittle. Adding a new watch provider or alert type requires understanding the entire file.

**No structured error model.** Errors currently propagate as Rich-formatted terminal messages. An AI agent calling `aya dispatch` when the relay is unavailable gets a human-readable error string. There is no machine-parseable error envelope with a code, message, and optional context payload.

**The workspace/guild repo coupling is undocumented in aya itself.** aya's architecture assumes the user maintains a "guild repo" with `CLAUDE.md`, `AGENTS.md`, skills, and hooks — but none of this is scaffolded or validated by aya. The coupling is implicit and undiscoverable from `aya --help`.

**Polling-based watches have inherent latency.** The current watch model polls at 5-minute intervals. For CI/PR workflows, this is often adequate, but the design doesn't support push notifications or webhooks. This is an intentional design choice but becomes a bottleneck if the scheduler grows to manage many watch targets.

---

## 3. Directional Options

### Option A: AI-Native CLI Hardening ("Clean the Foundation")

**Description:** Keep the current architecture intact but raise AI-readiness to first-class status. This means: JSON output as the default for all commands, a structured error model (exit code + JSON error envelope on stderr), schema versioning for packets and scheduler items, and a comprehensive `--dry-run` mode for every mutating operation.

**What it requires:**
- Audit every `cli.py` subcommand; add `--format [json|text]` with `json` as default for machine-facing commands
- Define and document an `aya` JSON schema for packets, alerts, scheduler items, and errors
- Add a schema version field (`"schema_version": 1`) to all persistent JSON files and output payloads
- Write an integration test suite that invokes the CLI as a subprocess and validates JSON output shapes

**Key tradeoffs:**
- ✅ Lowest disruption — existing users and integrations continue to work
- ✅ Highest return per unit of effort — immediately improves every AI use case
- ✅ Required foundation for any other direction
- ❌ Doesn't expand aya's capabilities or address protocol-level concerns
- ❌ Doesn't make aya discoverable by AI agents that don't already know about it

**Fit:** **High.** This should happen regardless of which larger direction is chosen. It's not a "direction" so much as a prerequisite.

---

### Option B: MCP Server Layer ("Speak Claude's Language")

**Description:** Expose aya's capabilities as a proper MCP (Model Context Protocol) server. Any Claude session with aya in its MCP config gains tools like `aya_send_packet`, `aya_schedule_remind`, `aya_receive_packets`, `aya_get_status` without ever knowing the CLI exists.

**What it requires:**
- Implement an MCP server module (Python, using the `mcp` SDK or `fastmcp`) that wraps aya's Python API
- Define MCP tool schemas for: `send`, `receive`, `schedule_remind`, `schedule_watch`, `schedule_list`, `status`, `pair`
- Distribute the MCP server config (or make `aya mcp-server` a first-class command)
- Handle authentication: the MCP server inherits the aya profile from `~/.aya/` — no new auth concept needed

**Key tradeoffs:**
- ✅ MCP is the native interface for Claude — zero prompt engineering required to call aya tools
- ✅ Structured inputs/outputs are enforced by the MCP schema — makes the AI-readiness problem a first-class concern rather than a migration project
- ✅ Any MCP-compatible AI host (not just Claude Code) can consume aya
- ✅ MCP tools compose with other tools in the agent's toolset naturally
- ❌ MCP is a different protocol from the CLI; maintaining both adds surface area
- ❌ MCP server architecture requires the server to be running (either as a daemon or launched on-demand via stdio), adding operational complexity
- ❌ MCP tool invocations are stateless per-call; aya's scheduler watches and recurring items still require background polling outside MCP

**Fit:** **High.** This is the most natural next step for making aya genuinely AI-native. An MCP server doesn't replace the CLI (it's still needed for setup, debugging, and human use) but it makes aya a first-class participant in Claude's tool ecosystem. Combined with Option A, this gives aya a complete AI interface story.

---

### Option C: Decentralized Multi-Agent Mesh ("Nostr as an AI Bus")

**Description:** Lean into Nostr as a coordination layer for multiple AI agents beyond the two-instance personal setup. Define a formal NIP or application-level spec for AI agent identity and messaging on Nostr. Aya becomes the reference implementation of that spec.

**What it requires:**
- Define a Nostr-native AI agent message format (likely a proper NIP proposal, or at minimum a well-documented application spec): kind, required tags, content envelope, agent identity conventions
- Support for multi-agent routing: a packet can be addressed to any Nostr pubkey, not just aya instances
- Agent discovery: define how agents advertise capabilities on Nostr (analogous to A2A "Agent Cards" but on the relay)
- Formal ACP/A2A compatibility mapping: can aya packets be translated to/from ACP messages?

**Key tradeoffs:**
- ✅ If successful, aya becomes a foundational layer in a broader open-source AI agent ecosystem
- ✅ Nostr's permissionless nature means any agent can join without aya's permission
- ✅ Aligns with decentralization values; avoids platform lock-in
- ❌ High complexity — defining interop specs is a research/standards effort, not a product one
- ❌ Requires buy-in from other AI tool developers (who mostly don't know Nostr)
- ❌ Nostr's weak delivery guarantees and lack of message ordering become real problems at mesh scale
- ❌ Risk of building a standard that no one else adopts

**Fit:** **Speculative.** Interesting as a long-term vision but not actionable near-term. The Nostr AI ecosystem is not mature enough to validate this bet. Worth revisiting in 12–18 months.

---

### Option D: Minimal Viable Memory Layer ("Strip and Focus")

**Description:** Distill aya down to its unique value: durable, signed, relay-synced context blobs with a human-approval gate. Remove scheduling, CI watching, and pairing complexity. The result is a focused "AI memory relay" that does one thing extremely well.

**What it requires:**
- Keep: `pack`, `send`, `receive`, `inbox`, `identity`, `pair`
- Remove or externalize: full scheduler (reminders, recurring, Jira/GitHub watches), `status` command, workspace scaffolding assumptions
- Expose a simple MCP server for the retained core
- Document clearly what aya is *not* (not a scheduler, not a workflow engine)

**Key tradeoffs:**
- ✅ Much simpler codebase — easier to maintain, audit, and reason about
- ✅ Forces a cleaner, more composable design (scheduling can be done by Claude Code's native CCR or system cron; aya handles only sync)
- ✅ Easier to onboard new users and contributors
- ❌ Loses the integrated human-oversight loop that makes aya's scheduling unique vs. raw CCR
- ❌ Existing users would need migration paths for any removed features
- ❌ The scheduler's human-in-the-loop value (surface to user, require judgment) is what differentiates aya from "just use GitHub webhooks"

**Fit:** **Moderate.** This is the right move *only if* aya is struggling to maintain its current scope. The scheduler complexity is real, but it also represents genuine accumulated value. A better approach might be to refactor the scheduler into a separate module/service rather than removing it.

---

### Option E: Composable Middleware ("aya as a Workflow Bus")

**Description:** Reframe aya as a lightweight workflow middleware layer between AI sessions and external systems. The packet model becomes a general-purpose intent/event bus. Nostr is the internal transport. Integrations (Jira, Slack, GitHub, Calendar) are first-class "connectors" that emit and consume packets. aya orchestrates but doesn't own the business logic.

**What it requires:**
- Define a formal connector interface (input: event type + payload → output: packet or alert)
- Implement connectors as plugins (entry points or a `connectors/` directory)
- Existing GitHub PR watch and Jira watch become the first connector examples
- Add outbound connectors: "when I receive a packet with intent X, post to Slack / open a Jira ticket"
- The packet's `intent` field becomes a routing key

**Key tradeoffs:**
- ✅ Formalizes what aya is already partially doing (GitHub/Jira watch, CI observation)
- ✅ Opens a clear extension model for integrations without growing the core
- ✅ The intent-routing model is a natural fit for AI workflow orchestration
- ❌ Substantially increases scope — connector ecosystem management is a product, not a feature
- ❌ Risk of becoming a worse version of existing workflow tools (Zapier, Make.com, n8n) without clear differentiation
- ❌ The MCP ecosystem already handles most tool integrations that aya would replicate as connectors

**Fit:** **Low-to-moderate near term, higher long term.** The connector/middleware framing is intellectually compelling but requires more foundational work (Options A and B) first. If aya gains a strong MCP presence, inbound/outbound connectors become natural extensions.

---

## 4. Recommended Direction

### Primary: Option A + Option B (AI-Native CLI Hardening + MCP Server Layer)

**Rationale:**

The single highest-leverage move for aya in 2026 is making it a first-class MCP server while hardening the CLI for AI consumption. These two options are synergistic: the MCP schema design drives the JSON schema work in Option A, and Option A's clean output contracts make the MCP server trivially thin.

This approach preserves everything that makes aya unique — signed relay packets, session-aware scheduling, human-in-the-loop oversight — while dramatically improving the experience for the primary consumer (Claude Code). It doesn't require a protocol change, doesn't increase external dependencies, and doesn't remove features that existing users rely on.

**Concrete sequence:**

1. **Define the aya JSON schema spec** (packet envelope, scheduler item, alert, error response) with explicit `schema_version` fields. Document this in `docs/schema.md`. (~1 week)

2. **Harden CLI output:** audit every subcommand, make `--format json` available everywhere (default for non-interactive/piped sessions via TTY detection), route all errors to stderr as JSON when in machine mode. (~2 weeks)

3. **Build the MCP server:** implement `aya mcp-server` as a stdio MCP server exposing the 7–10 most-used operations as tools. Ship a reference `mcp_config.json` snippet for Claude Code's `~/.claude.json`. (~2 weeks)

4. **Write integration tests** that call aya as a subprocess (both CLI and via the MCP protocol) and assert on JSON output shape. This validates the schema spec and prevents regressions. (~1 week)

### Secondary: Scheduler Refactor (but not removal)

The scheduler is aya's most complex subsystem and its most differentiated feature relative to the landscape. Rather than removing it (Option D) or dramatically expanding it (Option E), the right move is to refactor it into a cleaner internal module boundary — separating storage, polling, and alert delivery into distinct layers. This doesn't need to be done before the MCP work but should happen in parallel to prevent the complexity from compounding.

### Watch for: Option C maturation

If the Nostr-native AI tooling space meaningfully develops over the next 12 months, revisit Option C. The infrastructure is not ready today, but aya's dual-keypair identity model and kind 5999 packet format position it well to participate in that ecosystem if a viable standard emerges.

---

## Appendix: Summary Decision Matrix

| Option | AI-Native Fit | Human Oversight | Implementation Cost | Risk | Recommended? |
|--------|--------------|----------------|--------------------|----|---|
| A: CLI Hardening | ★★★★★ | ★★★★☆ | Low | Low | **Yes — required** |
| B: MCP Server | ★★★★★ | ★★★☆☆ | Medium | Low-Med | **Yes — primary bet** |
| C: Multi-Agent Mesh | ★★★☆☆ | ★★☆☆☆ | Very High | High | No (too early) |
| D: Strip to Core | ★★★★☆ | ★★★☆☆ | Medium | Medium | No (value loss) |
| E: Middleware Bus | ★★★☆☆ | ★★★☆☆ | High | Medium | Not yet |
