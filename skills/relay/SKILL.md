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
aya sent                                     # did it go out, and to which relays
aya whoami                                   # who am I, who can I send to
```

Identity and relays resolve from the profile — you do **not** need `--as` or
`--relay` once pairing has run, because pairing promotes the relay it proved.
Pass them only to override, and note `--relay` *replaces* the profile list
rather than narrowing it — see [Relay strategy](#relay-strategy). If a command
reports an ambiguous identity, run `aya whoami` and then `aya use <label>` once.

Every empty result tells you what produced it:

```json
{"packets": [], "instance": "guild-shawnoster",
 "relays": ["wss://nos.lol"], "relay_reachable": true}
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
surfaces return the **same payload shape**, so either is fine:

```json
{"packets": [...], "instance": "...", "relays": [...], "relay_reachable": true}
```

MCP tools take `instance=` and `relay=` where the CLI takes `--as` and
`--relay`; both are optional on both surfaces.

A failed MCP call also carries `is_error: true`. Trust that over the payload,
because an `error` key can ride along with a call that *worked*: a packet whose
body failed to persist comes back as `{"ingested": false, "error":
"persist_failed"}` inside an otherwise fine envelope. So `is_error` means "this
call did not happen"; a payload `error` is per-item detail.

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

`aya inbox` and `aya_inbox` list on the unverified path, so unlike `receive`
they *do* surface bad-signature packets inline. Each carries `signature_valid`
alongside `trusted`. `signature_valid: false` means the claimed `from_did` does
not check out — report it as a sender that could not be authenticated, not as
"held, sender not paired". Such a packet has no `from_label` (it is null, and
the table shows the raw DID): there is no verified identity to name, so don't
supply the claimed peer's name yourself. `trusted` is gated on the signature
too, so it is false for those packets.

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

`send` succeeds if **any** relay accepts, so check `relays_failed` in the
JSON (or the Delivery block in text mode) before reporting success. A
packet that reached only some relays is invisible to a peer polling one of
the failures. `aya sent --failed` lists every such packet from the last
7 days.

After every send, **immediately poll** per verb 1, then frame the report.

---

## Post-send framing

```
↗ Sent <id_8> → <peer> · "<intent>"
  Poll: <empty | N new>
  <one-line note when something's worth noticing>
```

If any relay rejected the packet, say so on the third line — that is
exactly the kind of wrinkle it exists for.

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
aya relay status     # identity, trusted peers, relays, last successful poll
aya whoami           # instances, active one, peers, relays
aya sent --failed    # outbound packets a relay rejected
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

## Relay strategy

The one authoritative account of which relay a command talks to. Everything
below is a property of the code, not a convention.

**`--relay` replaces the profile list — it does not narrow it or fall back.**

```python
# usecases/resolve.py
return [relay] if relay else list(profile.default_relays)
```

So `--relay X` means *only* X. If X is down, the command fails; it will not
try the relays in your profile. Omit `--relay` to use the whole list, which
is published to in full and polled in order.

**Where the list comes from.** `aya init` seeds two public relays,
`wss://relay.damus.io` and `wss://nos.lol`. `aya init --relay X` seeds X as
the *only* relay and drops both — you lose the fallbacks, which is usually
not what you want on a laptop.

**Pairing uses the same list, and fixes it for you.** `aya pair` publishes
the request to every relay in `default_relays` and polls all of them, so
both sides must already share at least one relay for pairing to work at all.
Whichever relay actually carried the exchange is then promoted to primary on
*each* side independently — the initiator promotes the relay the response
came back on, the joiner promotes the relay it found the request on. Neither
side needs `--relay` for that to happen, and neither ends up promoting a
relay that failed.

The practical consequence: **`--relay` on `pair` is for reaching a peer who
is only on a private relay.** Both ends must pass it, because a pairing
request published only to a private relay cannot be found by a peer polling
the public defaults. This is the mistake that looks like
`No matching pairing request found (Relay mismatch)`.

**To make a relay primary without re-pairing:** `aya relay add <url> --first`.
Prefer this to hand-editing `~/.aya/profile.json`.

**To check both ends agree:** `aya relay list` on each machine, or
`aya relay status` for health plus identity.

---

## Delivery, duplicates and idempotency

**`send` reports publish, not delivery.** Exit 0 means at least one relay
accepted the event. Check `relays_failed`: a packet that reached only some
relays is invisible to a peer polling one of the failures. `aya sent --failed`
lists every such packet from the last 7 days.

**There is no delivery receipt.** The receiver does publish a read receipt
(Nostr kind 6999) on ingest, but nothing fetches it — `fetch_pending` filters
on kind 5999 only, so receipts are write-only and invisible to the sender.
`aya ack` is a *reply* the peer chooses to send, not a receipt: its message
is delivered as a body. So "did they get it?" is answered by them acking, or
not at all. Don't describe an ack as confirmation of delivery.

**Duplicate protection is thin, and opt-in.** Inbound dedup is keyed on
packet ID alone, so two packets with byte-identical content and different IDs
are both ingested, stored and rendered with no warning. On the sending side,
`--idempotency-key <key>` is the only guard: a repeat send with the same key
inside 24 h returns the cached result instead of publishing again. Without a
key, every `send` publishes unconditionally. Use a key whenever a retry could
plausibly fire twice.

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
| `Unknown recipient '<label>'` | Not in `trusted_keys` | `aya pair --peer <label>`, or `aya trust <did> --peer <label> --nostr-pubkey <hex>` — trusting without a pubkey leaves delivery with no address |
| `No Nostr pubkey found for recipient` | Trust entry lacks `nostr_pubkey` | Re-pair via `aya pair --peer <label>` |
| `Cannot ACK: the packet's sender … is not a trusted peer` | The packet was ingested from an unknown sender — `aya receive --yes` accepts all senders, `--auto-ingest` only trusted ones | Pair or trust the sender (the error carries the full DID), or reply with `aya send --to <peer> --in-reply-to <id>` |
| Peer unreachable on a fresh install | Only public relays seeded; peer is on a private one | Re-pair with `aya pair --relay <url>` **on both machines** — each promotes the relay that carried it |
| `No matching pairing request found (Relay mismatch)` | One end pinned `--relay`, the other polled the public defaults | Both ends must pass the same `--relay`, or neither |
| Peer received the same content twice | Inbound dedup is by packet ID only — a resend with a new ID is a new packet | Send with `--idempotency-key` so a retry cannot double-publish |
| Relay returns HTTP 503 | Transient outage | aya retries 5×; wait 30s |
| Peer says they never got a packet you sent | Partial delivery — a relay they poll rejected it | `aya sent --failed`; re-send once the relay recovers |

---

## Notes

- End-of-session handoffs ("pack this up for work/home") are verb 4 with
  content curation. No separate handoff skill is needed.
- Seed packets are lighter and safer for questions; content packets carry
  material. Default to seeds.
- The relay is asymmetric in practice: home runs hook/cron-backed polling;
  work is human-triggered. Don't assume both ends have the same cadence.
