---
name: pack-for-home
description: >
  Pack the current session's relevant context into an aya packet and send it
  to the home instance via relay. Invoke when the user says "pack for home",
  "send this to home", "send this home", "pack this up", or equivalent.
argument-hint: "[intent]"
---

# Pack for Home

Gather the session's home-relevant context, build a packet, and dispatch it
to the home instance in one step.

---

## 1. Identify what to pack

Review the current conversation for content worth sending home. Prioritise:

- **Open decisions** — questions still unresolved, choices being weighed
- **In-progress notes** — working docs, drafts, research in progress
- **Action items** — things flagged for follow-up at home
- **Context switches** — project state that would be lost without a handoff

Do NOT include: work-only content (tickets, PRs, code reviews), sensitive credentials,
or content the user explicitly marked as work-only.

If the user provided an argument (e.g. "pack for home — dinner party notes"), use that
as the intent. Otherwise derive the intent from the content: one short sentence, first person,
e.g. "Pick up dinner party guest count decision" or "Continue reading list research".

---

## 2. Decide the packet type

**Content packet** (`text/markdown`, default):
Use when there is substantive content to carry — notes, decisions, research, a document.

**Seed packet** (`--seed`):
Use when what matters is *what to pick up*, not raw content — an open question, a thread
to resume, a reminder to ask something. Lighter and harder to prompt-inject.

Default to a content packet unless the session has no document-like content, in which
case prefer a seed.

---

## 3. Build the packet content

For a **content packet**: write a clean markdown summary of the home-relevant material.
Structure it clearly — headings for topics, bullet points for open questions. Keep it
focused: 100–500 words. Omit work jargon the home context won't have.

For a **seed packet**: write a crisp opener question (one sentence) and a 2–3 sentence
context summary. List any open questions as bullets.

---

## 4. Dispatch

Run the appropriate command. If `aya` is not installed or the profile is not initialised,
stop and tell the user — do not attempt workarounds.

**Content packet (stdin):**

```bash
echo "<markdown content>" | aya dispatch \
  --to home \
  --intent "<one-line intent>" \
  --context "Home context handoff from work session"
```

**Content packet (file):**

```bash
aya dispatch \
  --to home \
  --intent "<one-line intent>" \
  --files path/to/file.md
```

**Seed packet:**

```bash
aya dispatch \
  --to home \
  --intent "<one-line intent>" \
  --seed \
  --opener "<opening question>" \
  --context "<2-3 sentence background>"
```

---

## 5. Confirm

After a successful dispatch, report back to the user:

- Intent of the packet sent
- Packet ID (first 8 chars)
- Relay it was sent to
- A one-sentence note on what to expect at home: "When you open a session at home,
  this packet will surface automatically for ingestion."

If dispatch fails (relay unreachable, profile not found, no trusted home key),
surface the error clearly and suggest the fix — do not retry silently.
