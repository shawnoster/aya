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
  -p "Run: aya receive --as alice --auto-ingest --skip-untrusted --quiet. If any packets were ingested, surface their content to the user."
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

> `--as` is the local identity, `--label` names a new one at `aya init`, and
> `--peer` names a remote machine. See
> [README](README.md#identity-flags---as---label---peer) for how the primary
> instance resolves when `--as` is omitted.

## Plugin Skills

`/aya` manages identity, pairing, health and updates. `/relay` sends and
receives packets. Both work in any project once the plugin is loaded — see
[README](README.md#claude-code-plugin) for the `--plugin-dir` setup.

After editing skill files, run `/reload-plugins` to pick up changes live.

## Session Cron Mechanics

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
| `github-pr` | `owner/repo#123` | `approved_or_merged` (default), `merged`, `new_comments` | Uses `gh` CLI. `new_comments` fires when the total count of general PR comments (issue comments) or inline review comments increases since the last poll — does not fire on the first poll. `--remove-when merged_or_closed` auto-cleans. |
| `jira-query` | Jira Query Language (JQL) string | `new_results` | Requires `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, `ATLASSIAN_SERVER_URL` env vars. |
| `jira-ticket` | `CSD-225` | `status_changed` | Same Jira env vars. |

## Packet Types

**Content packets** (default) carry knowledge — the receiver integrates it.

**Seed packets** (`--seed`) carry questions — the receiver investigates and reports back. Use `--opener` for the opening prompt.

Conflict strategies: `last_write_wins` (default), `surface_to_user`, `append`, `skip_if_newer`.

## Data Layout

All aya data lives under `~/.aya/`:

```
~/.aya/
  profile.json      # Identity, keypairs, trusted keys, relay list
  config.json       # Workflow config
  scheduler.json    # Reminders, watches, recurring crons — written lazily by
                    #   the first `aya schedule` command; absence is normal
  alerts.json       # Unseen alerts from watchers
  activity.json     # Last activity timestamp (idle tracking)
  ledger.json       # Packet ledgers: ingested, sent, dropped (7-day TTL).
                    #   Split from profile.json so polling does not rewrite
                    #   the keystore. `aya sent` reads the sent log here.
  sent_cache.json   # Idempotency cache, keyed by SHA-256 of the
                    #   `--idempotency-key` value, 24-hour TTL. Only written
                    #   when a key is passed; nothing reads it but the
                    #   duplicate-send check.
  packets/          # Packet bodies, one <ulid>.json per packet, mode 0600.
                    #   Holds both received packets and your own sent ones,
                    #   so `aya read` works on either.
```

## Claude Code Integration

### Quick setup

```bash
aya schedule install        # installs crontab + Claude Code hooks + OpenCode plugin
aya schedule install --dry-run  # preview without changing anything
```

This installs the system crontab entry for background polling, all required
Claude Code hooks in `~/.claude/settings.json`, and the OpenCode plugin at
`~/.config/opencode/plugins/aya-reminders.js`. Run it once per machine.
To remove everything: `aya schedule uninstall`.

## OpenCode Integration

aya ships an OpenCode plugin (`opencode-plugin/aya-reminders.js`) that
proactively surfaces due reminders and unseen alerts inside OpenCode sessions.

### How it works

The plugin hooks into OpenCode's `session.idle` event (fires when you stop
typing). On each idle tick it calls `aya schedule pending --format json`,
and if anything is due it:

1. Shows a `tui.toast.show` notification in the TUI status bar for each item
2. Injects a summary into `tui.prompt.append` so the agent sees it on your next message

A 15-second debounce prevents hammering aya on every brief pause.

### Install

`aya schedule install` copies the plugin automatically. To install manually:

```bash
cp opencode-plugin/aya-reminders.js ~/.config/opencode/plugins/
```

Or add it to your `opencode.json` by path:

```json
{
  "plugin": ["/path/to/aya/opencode-plugin/aya-reminders.js"]
}
```

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
