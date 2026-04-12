# Unified Watch + asyncRewake System

**Date:** 2026-04-12
**Status:** Design approved, pending implementation plan

## Summary

Generalize the `ci.py` asyncRewake pattern so that any aya scheduler watch
(github-pr, jira-query, jira-ticket, CI checks) can wake Claude mid-session
when its condition fires. Unify CI into the scheduler's provider system and
replace the special-case `aya ci watch` hook with a single `aya hook watch`
command that handles all watch types.

**Approach:** CI becomes a scheduler watch provider. A shared rewake emitter
module provides the asyncRewake JSON contract. One PostToolUse hook polls all
due watches and emits rewake on change.

## Problem

Two separate watch systems exist that don't talk to each other:

1. **`ci.py`** — runs inside Claude's process as a PostToolUse asyncRewake
   hook. Watches CI checks after `git push`. Session-scoped, transient.
2. **`scheduler/`** — runs outside Claude via `aya schedule tick` (crontab,
   every 5 min). Polls GitHub PRs, Jira queries, Jira tickets. Creates
   alerts delivered on next session start.

When a scheduler watch fires (e.g., PR approved) and Claude is currently
running, there's no way to wake Claude mid-session. The alert sits in the
queue until the next `/session` or `pending` call. Meanwhile, `run_tick`
already *skips polling* when a session is active — leaving a gap where
nothing polls at all until the session checks pending at a breakpoint.

## Design

### 1. CI Checks Watch Provider

CI becomes a standard watch provider persisted to scheduler.json.

**Provider:** `ci-checks`

**Config type:**
```python
class CiChecksConfig(TypedDict):
    owner: str
    repo: str
    branch: str
    pr: int
```

**State type:**
```python
class CiChecksState(TypedDict):
    all_complete: bool
    passed: list[str]
    failed: list[str]
    pending: list[str]
```

**Defaults:**
- `condition: "checks_failed"` — only wake on failure or timeout
- `remove_when: "checks_complete"` — auto-dismiss once all checks finish
- `poll_interval_minutes: 1`

**Lifecycle:** Created dynamically by `aya hook watch` when it detects
`git push` in the hook payload. Persisted to scheduler.json so the crontab
tick can pick it up if the session dies. Auto-removed when checks complete.

**Change detection:** Follows the existing `_CHANGE_DETECTORS` pattern:
- `("ci-checks", "checks_failed")` — fires when any check fails or times out
- `("ci-checks", "checks_complete")` — used for auto-remove evaluation

### 2. Shared asyncRewake Emitter

**New file:** `src/aya/rewake.py`

Extracts the `_emit()` pattern from `ci.py` into a single shared function:

```python
def emit(context: str, event_name: str = "PostToolUse") -> None:
    """Write asyncRewake JSON payload to stdout.

    Claude Code reads this when the hook process exits and injects
    additionalContext into the next agent turn.
    """
    sys.stdout.write(
        json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": context,
            }
        }) + "\n"
    )
```

**Message formatting** per provider reuses `display._format_watch_alert()`.
New CI formatter added for `ci-checks`:
- `"CI FAILED on PR #42 (branch: feat/foo). Failed checks: lint, test — investigate."`
- `"CI checks on PR #42 still running after 10 min — may need manual check."`

### 3. Unified `aya hook watch` Command

Replaces `aya ci watch`. Single PostToolUse hook with `asyncRewake: true`.

**Flow on every Bash tool use:**

```
aya hook watch (stdin: hook payload)
  │
  ├─ Was this a git push?
  │   └─ Yes → resolve PR → add_watch(provider="ci-checks", ...)
  │
  ├─ Load all active watches from scheduler.json
  │   └─ Filter to due watches (last_checked_at + poll_interval elapsed)
  │
  ├─ Poll each due watch (reuses providers.poll_watch)
  │   └─ Update last_checked_at + last_state in scheduler.json
  │
  ├─ For any that changed:
  │   ├─ Create alert (same as crontab path)
  │   └─ rewake.emit(formatted message)
  │
  └─ Exit 0 (no rewake) or 2 (rewake emitted)
```

**Rate limiting:** Respects each watch's `poll_interval_minutes`. CI polls
every 1 min, github-pr every 5 min, jira-ticket every 30 min. Most Bash
calls result in "nothing due, exit 0."

**Fast path:** If no watches are due, loads scheduler.json, checks
timestamps, exits. Target: <50ms.

**Creates alerts AND emits rewake:** The alert persists the event for
history and other sessions. The rewake is the immediate notification.

### 4. Crontab + Session Coordination

No new coordination mechanism needed.

- `aya schedule tick` (crontab) already skips polling when
  `is_session_active()` returns true.
- `aya hook watch` (in-session) updates `last_checked_at` on every poll.
- When a session dies, crontab resumes polling on next tick. It sees
  `last_checked_at` and respects the interval — no double work.
- Alert deduplication: `run_poll` checks `existing_sources` to avoid
  duplicate alerts for the same watch. `aya hook watch` does the same.

The `last_checked_at` + `poll_interval_minutes` fields on each watch item
are the handoff mechanism between the two polling paths.

### 5. Hook Registration

**install.py** replaces the ci-specific PostToolUse entry with:

```python
{
    "matcher": "Bash",
    "hooks": [{
        "type": "command",
        "command": "aya hook watch 2>/dev/null || true",
        "statusMessage": "Checking watches...",
        "asyncRewake": True,
    }]
}
```

One hook entry. All watch types. SessionStart hooks unchanged.

## File Changes

| File | Action | What |
|---|---|---|
| `src/aya/rewake.py` | New | `emit()` — shared asyncRewake JSON contract |
| `src/aya/scheduler/types.py` | Edit | Add `CiChecksState`, `CiChecksConfig`, `PROVIDER_CI_CHECKS`, `CONDITION_CHECKS_FAILED` |
| `src/aya/scheduler/providers.py` | Edit | Add `_check_ci_checks()` provider, change detector, auto-remove for `checks_complete` |
| `src/aya/scheduler/display.py` | Edit | Add CI checks alert formatter |
| `src/aya/cli.py` | Edit | Replace `ci watch` with `hook watch`. Remove `ci_app` if empty. |
| `src/aya/install.py` | Edit | Replace ci-specific PostToolUse hook with unified `aya hook watch` entry |
| `src/aya/ci.py` | Delete | Logic moves to `providers.py` + `rewake.py` |
| `tests/test_ci.py` | Rename/Edit | Tests move to `test_rewake.py` and/or `test_providers.py` |
| `tests/test_install.py` | Edit | Update hook entry assertions |

**Unchanged:** `scheduler/core.py`, `scheduler/storage.py`,
`scheduler/time_utils.py`, SessionStart hooks, crontab entry.

**Estimated scope:** ~200 lines new, ~150 lines deleted (ci.py), ~50 lines
modified.
