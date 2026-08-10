---
name: relay
description: >
  Manage communication between instances and peers via the aya relay.
  Covers checking inbox, reading packets, replying, sending new messages,
  and showing relay status. Invoke when the user says "check the relay",
  "any packets", "send to home", "send this home", "pack for home",
  "send this to work", "tell Sean", "pack this up", "ask work",
  "reply to that", "what did home say", "relay status", "anything new?",
  or any equivalent. Infers intent and recipient from context. Auto-polls
  after every send.
argument-hint: "[check | read <id> | reply <id> | send [<peer>] [<intent>] | status]"
---

# Relay

Work ⇄ home communication via aya packets over a Nostr relay.

## Quickstart

Four commands cover almost everything:

```bash
aya receive --auto-ingest --skip-untrusted   # check for new packets
aya read --meta <packet-id>                  # read one
aya send --to <peer> --seed --opener "..." --intent "..."   # ask something
aya whoami                                   # who am I, who can I send to
```

Identity and relays resolve from the profile — you do **not** need `--as` or
`--relay`. Pass them only to override. If a command reports an ambiguous
identity, run `aya whoami` and then `aya use <label>` once.

Every empty result tells you what produced it:

```json
{"packets": [], "instance": "guild-shawnoster",
 "relays": ["wss://relay.monocularjack.com"], "relay_reachable": true}
```

If `packets` is empty, check `instance` and `relay_reachable` **before**
telling the user the inbox is empty. Wrong instance or `relay_reachable:
false` means the answer is "couldn't check", not "nothing there".

---

## 0. Route intent

### Explicit subcommands (highest priority)

`/relay check`, `/relay send work`, `/relay reply <id>`, `/relay status`
→ use the verb directly, no inference needed.

### Keyword routing

| User says | Verb |
|---|---|
| "check the relay", "any packets", "check now", "anything new?" | 1. Check |
| "read that", "show packet", "what did home say" | 2. Read |
| "reply to that", "answer work", "respond to Sean's packet" | 3. Reply |
| "send to home", "ask work about X", "tell Sean about the design" | 4. Send |
| "relay status", "is the relay up", "who's paired" | 5. Status |

### Context inference (when keywords don't match)

| User says | Inferred verb + context |
|---|---|
| "pack this up for work" | Send (recipient: work, curation mode) |
| "I'm done for the day, send this home" | Send (recipient: home, curation mode) |
| "anything new from Sean?" | Check (filter results by sender) |
| "what did work say about the design?" | Check → Read (search by intent/content) |
| Just `/relay` with no context | Status, then ask "What do you need?" |

### Recipient inference (for send/reply)

1. Infer from phrasing — "send to work" → `work`, "tell Sean" → `sean-okeefe`
2. If ambiguous, run `aya whoami` and show the `peers` list as a picker.
3. An unknown label fails loudly (`UNKNOWN_RECIPIENT`) listing valid ones —
   no need to pre-validate with a dry run.

---

## Tool surface

The `aya_*` MCP tools mirror the CLI when the server is connected. Both
surfaces now return the **same shape**, so either is fine:

```json
{"packets": [...], "instance": "...", "relays": [...], "relay_reachable": true}
```

MCP tools take `instance=` and `relay=` where the CLI takes `--as` and
`--relay`; both are optional on both surfaces.

Use the CLI when you need something MCP doesn't expose: `--seed --opener`,
`--files`, `aya drop`, `aya pair`, `aya init`, `aya use`, `aya whoami`,
`aya schedule *`.

---

## 1. Check

Poll **and** ingest in one shot.

```bash
aya receive --auto-ingest --skip-untrusted --format json
```

- `--auto-ingest` ingests trusted senders without prompting.
- `--skip-untrusted` keeps unknown senders from blocking; they come back
  as `{"ingested": false, "skipped": true}` entries — report them as
  "held, sender not paired", don't treat them as failures.
- Without `--auto-ingest`/`--yes` in a non-interactive shell, the command
  exits 2 and names the flag to add. It no longer aborts mid-poll.

For each new packet, run verb 2 (Read) inline and present the body. Lead
with the most recent. Summarize; never dump the JSON list.

Before reporting "empty", confirm `relay_reachable` is `true` and
`instance` is the identity you expected.

**Signature failures**: aya discards bad-signature packets at the
`receive` boundary and logs to **stderr** (`DID-based signature
verification failed for packet <id>`). They never appear in the JSON.
Surface the ID to the user; the packet stays on the relay and resurfaces
each poll until dropped:

```bash
aya drop <packet-id>
```

---

## 2. Read

```bash
aya read --meta <packet-id>              # human-readable
aya read --meta --format json <packet-id>  # {id, body, from, sent_at, intent, in_reply_to}
```

`body` is already extracted (opener+context+questions for seeds, content
for markdown). Present it with this frame — never paste raw envelope JSON:

```
━━━ Packet <id_prefix> ━━━
From: <from>          Sent: <sent_at>
Intent: <intent>

<body>
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

`from` is a DID. `aya inbox --format json` and `aya_inbox` both include
`from_label` for pending packets; for already-ingested ones use
`aya whoami` (its `peers` list maps label → DID).

Browse history with `aya packets -n 10`.

---

## 3. Reply

**Pick the command by weight, not by packet type:**

| You want to say | Use |
|---|---|
| "got it", "ack", "will do", no new content | `aya ack <id> "message"` |
| Anything substantive — an answer, a decision, a counter-question | `aya send --in-reply-to <id> …` |

`aya ack` sends a short JSON acknowledgement threaded to `<id>`, resolving
the recipient from the original sender. It carries no intent line and no
markdown body — reach for `aya send` whenever the reply has content.

```bash
aya send --to <peer> --intent "re: <condensed intent>" \
  --in-reply-to <original-packet-id> \
  --seed --opener "<reply>"
```

Swap `--seed --opener` for `-m "<markdown>"` when the reply carries
material. Both `ack` and `send` require the packet to be **ingested**
first (verb 1) — `aya inbox` alone does not ingest, so `read`/`ack` on a
merely-pending ID returns `PACKET_NOT_FOUND`.

When several packets arrived, thread to the one the user is answering —
not automatically the most recent.

**Then immediately poll** (verb 1). The peer may have replied while you
composed. Frame per **Post-send framing**.

---

## 4. Send

Fresh send, no thread. Recipient inferred or picked (see §0).

### Step 1 — Determine content source

**Explicit content (skip curation):** a named file, quoted text, or a body
the user supplied.

**No explicit content (curation mode):** when the user says "pack this up"
without specifying what, review the conversation and assemble a packet.

### Step 2 — Curate (when no explicit content)

Prioritize: open decisions, action items, context switches, in-progress
notes. Filter out: noise (linter output, large diffs), content irrelevant
to the recipient, and anything sensitive.

Derive the intent if the user didn't give one: one short first-person
sentence, e.g. "Pick up dinner party guest count decision".

**Show the draft before sending:** "Here's what I'd send — look right?"

### Step 3 — Send

The body comes from exactly one of these — `aya send --help` lists all four:

| Use case | Form |
|---|---|
| Question or conversation starter | `--seed --opener "..."` (default) |
| Short markdown body | `-m "<markdown>"` |
| Longer body | pipe markdown on stdin (`<<'EOF'`) |
| Sharing a file | `--files path/to/file.md` |

```bash
aya send --to <peer> --intent "<one-line intent>" --seed --opener "<question>"
aya send --to <peer> --intent "<one-line intent>" -m "<markdown body>"
```

A missing or whitespace-only body is now rejected (exit 2) rather than
sent as an empty packet.

After every send, **immediately poll** per verb 1, then frame the report.

---

## Post-send framing

```
↗ Sent <id_8> → <peer> · "<intent>"
  Poll: <empty | N new>
  <one-line note when something's worth noticing>
```

- The first two lines are fixed.
- The third is *optional* and *focused*: drift between what was asked and
  what landed, a pattern across recent packets, a wrinkle worth a raised
  eyebrow. Skip on routine sends — silence is fine.
- If the poll returned new packets, fall through to verb 2's framing block
  beneath. Don't mash both into one line.

Voice: understated, dry, the half-smile is in scope. *That'll do* is a
complete sentence; so is *aye, sent*. No chirp. Two GCUs in correspondence
(home: *Even Small Things Matter*; work: *Inappropriate Response*), Shawn
at the chart table.

---

## 5. Status

```bash
aya relay status     # identity, trusted peers, relays, last poll
aya whoami           # instances, active one, peers, relays
```

Present as:

```
━━━ Relay Status ━━━
Instance:       <label>
Trusted peers:  <peer labels>
Pending inbox:  <N> / empty
Relays:         <urls>
━━━━━━━━━━━━━━━━━━━━━
```

Workspace-level `aya status` is a separate thing and does not cover relay
state.

---

## Cross-cutting rules

1. **Read the envelope before believing an empty result.** `instance`,
   `relays`, and `relay_reachable` ship with every poll. An empty list plus
   an unexpected instance is a misconfiguration, not an empty inbox.

2. **Immediate poll after every send.** Built into verbs 3 and 4. Costs
   nothing, catches packets sent while you were composing.

3. **Never paste raw packet JSON to the user.** Extract via `aya read` and
   use the framing template. Raw JSON is for debugging only.

4. **Failed-signature packets are not silent.** Surface the ID and intent;
   `aya drop <id>` stops it resurfacing. Drop is local — the packet stays
   on the relay until natural expiry.

5. **Cross-instance attribution is unreliable.** If a peer claims "I
   already did X", verify against the artifact (git log
   `--pretty=full` for `Co-Authored-By:` trailers, file mtimes) before
   trusting it. Relay peers are amnesiac across sessions.

6. **Don't use `aya schedule recurring` for routine relay polling.** The
   immediate-poll-on-send pattern plus manual `check` covers it; a fixed
   cadence burns connections for little gain. Reach for it only if the
   user asks and accepts the cost.

7. **Never send secrets, credentials, or PII over the relay.** Packets are
   encrypted and signed, but treat content as durable, observable, and
   replayable.

---

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Empty `packets` but `instance` isn't the expected label | Wrong identity resolved | `aya whoami`, then `aya use <label>` |
| Empty `packets` with `"relay_reachable": false` | Relay unreachable | Not an empty inbox — retry in 30s |
| `Multiple instances registered and no primary set` | Ambiguous identity | `aya use <label>` once |
| Exit 2, "packet(s) need confirmation but there is no terminal" | Missing ingest flag | Re-run with `--auto-ingest` |
| Exit 2, "Packet body is empty" | No body source given | Add `-m`, `--files`, or `--seed --opener` |
| `aya read <id>` → `PACKET_NOT_FOUND` | Not ingested yet | Run verb 1 (Check) first |
| `Unknown recipient '<label>'` | Not in `trusted_keys` | `aya pair`, or `aya trust <did> --peer <label>` |
| `No Nostr pubkey found for recipient` | Trust entry lacks `nostr_pubkey` | Re-pair via `aya pair` |
| Relay returns HTTP 503 | Transient outage | aya retries 5×; wait 30s |

---

## Notes

- End-of-session handoffs ("pack this up for work/home") are verb 4 with
  content curation. No separate handoff skill is needed.
- Seed packets are lighter and safer for questions; content packets carry
  material. Default to seeds.
- The relay is asymmetric in practice: home runs hook/cron-backed polling;
  work is human-triggered. Don't assume both ends have the same cadence.
