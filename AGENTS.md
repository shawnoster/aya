# aya — Agent Guide

aya is a CLI tool that AI agents call to schedule reminders, sync context between machines, and integrate with Claude Code sessions. Agents never import aya as a library — they invoke it via shell commands.

## Quick Reference

### Scheduling

```bash
# One-shot reminder
aya schedule remind -m "Check the PR" --due "in 1 hour"

# Watch a GitHub PR (default polls every 5 min for PRs)
aya schedule watch github-pr owner/repo#123 -m "PR approved" --remove-when merged_or_closed

# Watch a Jira ticket
aya schedule watch jira-ticket CSD-225 -m "Ticket status changed"

# Recurring session cron (fires during active sessions only)
aya schedule recurring -m "health-break" -c "*/20 * * * *" \
  -p "Stand up, stretch, hydrate." --idle-back-off 10m

# Record user activity (resets idle timer)
aya schedule activity

# Check what's pending for this session
aya schedule pending --format json

# List active items
aya schedule list

# Dismiss or snooze
aya schedule dismiss <id-prefix>
aya schedule snooze <id-prefix> --until "in 1 hour"
```

### Dispatch / Relay

```bash
# Send context to another machine (encrypted by default on public relays)
aya send --as alice --to bob \
  --intent "context sync" --files path/to/file.md

# Send a conversation seed (request for research/action)
aya send --as alice --to bob --seed \
  --intent "investigate caching" \
  --opener "Can you trace the auth flow and find where sessions drop?"

# Send plaintext (debug or private relay only)
aya send --as alice --to bob --no-encrypt --intent "test"

# Check inbox
aya inbox --as alice

# Receive and ingest trusted packets (decrypts transparently)
aya receive --as alice --auto-ingest --quiet

# Fully non-interactive receive — ingest everything without prompting (trusted or not)
aya receive --as alice --auto-ingest --yes --quiet

# Set up recurring relay poll (persists across sessions)
aya schedule recurring -m "relay-poll" -c "*/10 * * * *" \
  -p "Run: aya receive --as alice --auto-ingest --quiet. If any packets were ingested, surface their content to the user."
```

> **New machine?** See the "One-prompt setup" section in `README.md` for a single prompt that installs aya, pairs instances, wires hooks, and registers relay polling.

### Identity

```bash
# First-time setup — label can be anything (name, machine role, hostname)
aya init --label alice

# Pair with another machine (initiator)
aya pair --peer bob --as alice
# On the other machine (joiner)
aya pair --code WORD-WORD-1234 --peer alice --as bob

# Check status
aya status
```

> **`--as` vs `--label` vs `--peer`** — three flags, three roles:
> - `--as` is your **local identity** (which keypair to act as). Matches the label from `aya init --label <name>`. Legacy alias: `--instance`.
> - `--label` is used with `aya init` to **name a new local identity**. (In older versions, `--label` was also used where `--peer` is now; some commands still accept it as a legacy alias.)
> - `--peer` names a **remote machine** (used in `pair` and `trust`). Preferred over the legacy `--label` alias.
>
> Common label patterns: `home`/`work` (personal setup), first names (sharing with a friend), `laptop`/`desktop`/`server` (by machine).

## Plugin & Slash Commands

aya ships as a Claude Code plugin. Load it with:

```bash
claude --plugin-dir /path/to/aya
```

Or add a permanent alias to your shell profile:

```bash
alias claude='claude --plugin-dir /path/to/aya'
```

Available plugin skills (work in any project):

| Skill | Verbs | What it does |
|-------|-------|--------------|
| `/aya` | setup, pair, status, refresh, watch | Manage aya — identity, pairing, health, updates, watches |
| `/relay` | check, read, reply, send, status | Relay communication — send/receive packets between instances |

After editing skill files, run `/reload-plugins` to pick up changes live.

## How Session Crons Work

aya persists recurring schedules. Claude Code fires them during sessions. The bridge:

1. `aya schedule recurring` stores the cron in `~/.aya/scheduler.json`
2. At session start, the `aya hook crons` command reads pending crons
3. It outputs `hookSpecificOutput` JSON telling Claude Code to call `CronCreate`
4. Claude Code's native cron system handles the timing from there

Filtering happens at hook-time, not at fire-time. Both filters below are evaluated each time `aya hook crons` runs (SessionStart, then again after every tool call via PostToolUse), so a cron that's suppressed at session start can still register later in the same session if conditions change. Once registered with Claude Code's cron engine, the cron fires on schedule regardless of aya's current idle/window state.

**Idle back-off** (`--idle-back-off 10m`): suppresses registration when the last `aya schedule activity` is older than the threshold. The PreToolUse hook calls `aya schedule activity` on every tool use, so an active session won't be considered idle. After being idle, the next tool boundary refreshes activity and the next PostToolUse `hook crons` registers any previously-suppressed crons.

**Work hours** (`--only-during 08:00-18:00`): suppresses registration when the current time is outside the window. Same evaluation cadence as idle — a cron registered at 5:30pm with a 08:00-18:00 window will keep firing after 6pm because Claude Code's cron engine doesn't know about the window. For strict end-of-window stops, embed the check inside the cron's prompt with `aya schedule is-idle` or a time gate.

## Watch Providers

| Provider | Target | Condition | Notes |
|----------|--------|-----------|-------|
| `github-pr` | `owner/repo#123` | `approved_or_merged` | Uses `gh` CLI. `--remove-when merged_or_closed` auto-cleans. |
| `jira-query` | JQL string | `new_results` | Requires `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, `ATLASSIAN_SERVER_URL` env vars. |
| `jira-ticket` | `CSD-225` | `status_changed` | Same Jira env vars. |

## Packet Types

**Content packets** (default) carry knowledge — the receiver integrates it.

**Seed packets** (`--seed`) carry questions — the receiver investigates and reports back. Use `--opener` for the opening prompt.

Conflict strategies: `last_write_wins` (default), `surface_to_user`, `append`, `skip_if_newer`.

## Data Layout

All aya data lives under `~/.aya/`:

```
~/.aya/
  profile.json      # Identity, keypairs, trusted keys
  config.json       # Workflow config
  scheduler.json    # Reminders, watches, recurring crons
  alerts.json       # Unseen alerts from watchers
  activity.json     # Last activity timestamp (idle tracking)
```

## Claude Code Integration

### Quick setup

```bash
aya schedule install        # installs crontab + Claude Code hooks
aya schedule install --dry-run  # preview without changing anything
```

This installs the system crontab entry for background polling and all required
Claude Code hooks in `~/.claude/settings.json`. Run it once per machine.
To remove everything: `aya schedule uninstall`.

### Hooks installed

`aya schedule install` writes a fixed canonical hook block into
`~/.claude/settings.json`. Order within each event matters and is preserved:

**SessionStart** (run in order, top-to-bottom):

| # | Command | Purpose |
|---|---------|---------|
| 1 | `aya schedule activity` | Reset the idle timer **first** so subsequent SessionStart hooks see a fresh activity timestamp |
| 2 | `aya hook crons --reset` | Clear the per-session registered-crons tracker, then emit `CronCreate` instructions for every active session cron passing idle/work-hours filters |
| 3 | `aya receive --quiet --auto-ingest` (async) | Ingest packets from trusted senders in the background |
| 4 | `aya schedule pending --format text` | Surface due reminders and alerts into session context |

**PreToolUse:**

| Command | Purpose |
|---------|---------|
| `aya schedule activity` (async) | Refresh the idle timer on every tool use |

**PostToolUse:**

| Matcher | Command | Purpose |
|---------|---------|---------|
| (any) | `aya hook crons --event PostToolUse` (async) | Re-evaluate idle/work-hours filters and register any session crons newly eligible since the last hook run. This is what makes mid-session `aya schedule recurring` calls actually fire. |
| `Bash` | `aya hook watch` (asyncRewake) | Poll all due scheduler watches; if any condition changed, emit `asyncRewake` so the session wakes after the user's reply |

**Critical: don't reorder the SessionStart hooks.** `activity` must run before `hook crons` or the very first `get_session_crons()` call sees the stale timestamp from the prior session and falsely suppresses idle-back-off crons.

## Common Patterns

**After user says "remind me":**
```bash
aya schedule remind -m "Review the deploy" --due "tomorrow 9am"
```

**After opening a PR:**
```bash
aya schedule watch github-pr owner/repo#456 -m "PR review" --remove-when merged_or_closed
```

**Sending context to another machine:**
```bash
aya send --as alice --to bob --seed \
  --intent "research request" \
  --opener "What logging do we have for the payment flow?"
```

**Checking scheduler health:**
```bash
aya schedule status
```

## Important Notes

- All `--format json` output uses `console.out()` to avoid Rich wrapping — safe to pipe.
- Item IDs support prefix matching: `aya schedule dismiss 5dc6` works if unambiguous.
- `aya schedule tick --quiet` is the system cron entry point (`*/5 * * * *`), installed via `aya schedule install`.
- Packets expire after 7 days by default.
- Trust is explicit — only paired/trusted DIDs are accepted.

## Troubleshooting

**A recurring cron isn't firing.**

1. Confirm it's registered: `aya schedule list --type recurring` — status should be `active`.
2. Confirm whether it was suppressed at session registration: `aya schedule pending --format json` and inspect `suppressed_crons` for reasons such as `outside work hours (...)` or `session idle (...)`.
3. If suppressed for idleness, check the activity timestamp: `cat ~/.aya/activity.json | jq .last_activity_at`. A new tool call will refresh it; the next PostToolUse `aya hook crons` will then re-evaluate and register the cron.
4. Confirm the SessionStart hook order in `~/.claude/settings.json` runs `aya schedule activity` *before* `aya hook crons --reset`. If reordered, the first filter sees the prior session's stale timestamp.
5. If `--only-during 08:00-18:00` is set and the time is outside that window at session start, the cron is suppressed at registration. Once registered, Claude Code's cron engine fires it regardless of the window — embed `aya schedule is-idle` or a time gate inside the cron's prompt for hard end-of-window stops.

**A `watch` doesn't seem to be polling.**

1. `aya schedule list --type watch` should show it active.
2. Confirm the system crontab entry exists: `crontab -l | grep "aya schedule tick"`. If missing, run `aya schedule install`.
3. Watches fire from the system cron every 5 min by default — they're independent of session activity.
4. Provider-specific deps: `github-pr` needs `gh` CLI logged in; `jira-*` needs `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, `ATLASSIAN_SERVER_URL` in the cron environment (system cron has minimal env — set them in the crontab entry or wrap the call in a script that sources them).
5. For visibility, append `>> ~/.aya/scheduler.log 2>&1` to the cron line and tail it.

**`aya receive` returns nothing but the peer says they sent something.**

1. The peer's packet may not have reached the relay you're polling — confirm both ends share at least one relay: `aya relay list`.
2. The packet may be encrypted to a different DID. Run `aya inbox --format json` (raw) to see what arrived; if it's there but not ingested, it's likely from an untrusted sender (run `aya receive` interactively without `--auto-ingest` to inspect).
3. As of v1.36.2 the `since` cursor is gone — earlier versions could "lose" packets that arrived during a crashed receive. Upgrade if you're on an older build.
