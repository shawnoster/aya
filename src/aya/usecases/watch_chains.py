"""Watch chains: multi-stage watches that advance as each stage completes.

This lived inside ``cli.py`` — 635 lines of state machine reachable only by
invoking a Typer command. It is application logic, not presentation: it decides
when a stage is satisfied, what the next one watches, and which alerts to
raise. The CLI keeps only the ``aya hook watch`` entry point.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta
from typing import Any, cast

from aya.adapters import clock
from aya.adapters.rewake import emit as rewake_emit
from aya.scheduler import (
    SEVERITY_ACTIONABLE,
    SEVERITY_HEARTBEAT,
    SEVERITY_INFO,
    AlertDetails,
    AlertItem,
    AlertSeverity,
    SchedulerItem,
    WatchState,
    _format_watch_alert,
    add_watch,
    get_active_watches,
    poll_watch,
    record_poll_attempt,
    should_warn_for_failures,
)
from aya.scheduler.storage import _file_lock, _load_items_unlocked

logger = logging.getLogger(__name__)

# How long a chain may sit quiet before it emits a heartbeat alert.
DEFAULT_WATCH_CHAIN_HEARTBEAT_MINUTES = 120


def _hook_watch_now() -> datetime:
    """Clock helper for hook-watch tests."""
    return clock.now().astimezone()


def _is_watch_chain(item: SchedulerItem) -> bool:
    """Return True when a scheduler watch item represents a multi-stage chain."""
    return item.get("type") == "watch" and isinstance(item.get("stages"), list)


def _chain_name(item: SchedulerItem) -> str:
    raw = item.get("chain") or item.get("message") or "watch chain"
    return str(raw)


def _chain_stage_name(stage: dict[str, Any], index: int) -> str:
    raw = stage.get("name") or f"stage-{index + 1}"
    return str(raw)


def _chain_stage_action(stage: dict[str, Any]) -> str:
    action = stage.get("action")
    if isinstance(action, str) and action:
        return action
    return "notify" if _chain_stage_watch_spec(stage) is not None else "dispatch"


def _chain_stage_autonomy(item: SchedulerItem, stage: dict[str, Any]) -> str:
    raw = stage.get("autonomy") or item.get("default_autonomy") or "autonomous"
    return raw if raw in {"autonomous", "confirm", "notify-only"} else "autonomous"


def _chain_stage_watch_spec(stage: dict[str, Any]) -> tuple[str, str] | None:
    watch = stage.get("watch")
    if isinstance(watch, str):
        parts = watch.split(maxsplit=1)
        if len(parts) == 2:
            return parts[0], parts[1]
    provider = stage.get("provider")
    target = stage.get("target")
    if isinstance(provider, str) and isinstance(target, str) and provider and target:
        return provider, target
    return None


def _build_chain_stage_watch_item(
    chain: SchedulerItem, stage: dict[str, Any], index: int
) -> SchedulerItem | None:
    """Build an ephemeral watch item for the current chain stage."""
    watch_spec = _chain_stage_watch_spec(stage)
    if watch_spec is None:
        return None

    provider, target = watch_spec
    watch_config: dict[str, Any]
    if provider in {"github-pr", "ci-checks"}:
        match = re.match(r"([^/]+)/([^#]+)#(\d+)", target)
        if not match:
            return None
        watch_config = {
            "owner": match.group(1),
            "repo": match.group(2),
            "pr": int(match.group(3)),
        }
    elif provider == "jira-query":
        watch_config = {"jql": target}
    elif provider == "jira-ticket":
        watch_config = {"ticket": target.upper()}
    else:
        return None

    interval = stage.get("interval", stage.get("poll_interval_minutes"))
    if not isinstance(interval, int):
        interval = 30
    # Mirror the provider-specific tightening in add_watch()
    if interval == 30 and provider == "github-pr":
        interval = 5
    elif interval == 30 and provider == "ci-checks":
        interval = 1

    watch_item: SchedulerItem = {
        "id": chain["id"],
        "type": "watch",
        "status": "active",
        "created_at": chain.get("created_at", _hook_watch_now().isoformat()),
        "message": (
            stage.get("message") or f"{_chain_name(chain)} · {_chain_stage_name(stage, index)}"
        ),
        "tags": chain.get("tags", []),
        "session_required": False,
        "provider": provider,
        # The stage spec is parsed from user config, so its shape is only
        # known to the provider that consumes it.
        "watch_config": cast(Any, watch_config),
        "condition": stage.get("condition", ""),
        "poll_interval_minutes": interval,
        "last_checked_at": chain.get("last_checked_at"),
        "last_state": chain.get("last_state"),
        "remove_when": stage.get("remove_when", ""),
    }
    return watch_item


def _chain_stage_details(
    chain: SchedulerItem, stage: dict[str, Any], index: int, **extra: Any
) -> AlertDetails:
    details: dict[str, Any] = {
        "type": "watch-chain",
        "intent": _chain_name(chain),
        "opener": _chain_stage_name(stage, index),
        "context_summary": stage.get("action", ""),
    }
    # *extra* is caller-supplied and open-ended, so the narrowing happens here
    # rather than pretending the literal above is already an AlertDetails.
    details.update(extra)
    return cast(AlertDetails, details)


def _append_chain_alert(
    *,
    alerts: list[AlertItem],
    source_item_id: str,
    now: datetime,
    message: str,
    details: AlertDetails,
    severity: AlertSeverity,
) -> None:
    from aya.scheduler.display import _create_alert as create_alert

    alerts.append(
        create_alert(
            source_item_id=source_item_id,
            message=message,
            details=details,
            now=now,
            severity=severity,
        )
    )


def _advance_watch_chain(item: SchedulerItem, next_index: int, now: datetime) -> None:
    item["current_stage_index"] = next_index
    item["current_stage_started_at"] = now.isoformat()
    item["last_checked_at"] = None
    item["last_state"] = None
    item.pop("awaiting_confirmation", None)
    item.pop("pending_stage_index", None)
    item.pop("pending_dispatch", None)


def _chain_dispatch_message(
    chain: SchedulerItem, stage: dict[str, Any], index: int, autonomy: str, command: str
) -> str:
    label = f"{_chain_name(chain)} · {_chain_stage_name(stage, index)}"
    if autonomy == "confirm":
        return f"{label} — awaiting confirmation to run {command}"
    if autonomy == "notify-only":
        return f"{label} — notify-only: {command}"
    return f"{label} — dispatching {command}"


def _run_chain_action(
    chain: SchedulerItem,
    stage: dict[str, Any],
    index: int,
    now: datetime,
    alerts: list[AlertItem],
    rewake_messages: list[str],
) -> tuple[bool, bool, bool]:
    """Run the current chain stage action.

    Returns (items_modified, alerts_modified, should_advance).
    """
    action = _chain_stage_action(stage)
    autonomy = _chain_stage_autonomy(chain, stage)

    if action == "notify":
        # Watch-backed notify stages already emitted an alert from the watch trigger;
        # only emit here for non-watch stages so the caller isn't notified twice.
        if _chain_stage_watch_spec(stage) is None:
            message = stage.get("message") or (
                f"{_chain_name(chain)} · {_chain_stage_name(stage, index)}"
            )
            _append_chain_alert(
                alerts=alerts,
                source_item_id=chain["id"],
                now=now,
                message=message,
                details=_chain_stage_details(chain, stage, index, autonomy=autonomy),
                severity=SEVERITY_INFO,
            )
            rewake_messages.append(message)
            return False, True, True
        return False, False, True

    if action == "gate":
        message = (
            f"{_chain_name(chain)} · {_chain_stage_name(stage, index)} — awaiting confirmation"
        )
        _append_chain_alert(
            alerts=alerts,
            source_item_id=chain["id"],
            now=now,
            message=message,
            details=_chain_stage_details(chain, stage, index, autonomy=autonomy),
            severity=SEVERITY_ACTIONABLE,
        )
        rewake_messages.append(message)
        chain["awaiting_confirmation"] = True
        chain["pending_stage_index"] = index
        return True, True, False

    if action != "dispatch":
        return False, False, True

    command = stage.get("dispatch") or stage.get("command") or stage.get("prompt")
    if not isinstance(command, str) or not command:
        logger.warning(
            "Chain %s stage %d has action 'dispatch' but no command; stage halted",
            chain.get("id", "?"),
            index,
        )
        return False, False, False

    message = _chain_dispatch_message(chain, stage, index, autonomy, command)
    severity = SEVERITY_INFO if autonomy != "confirm" else SEVERITY_ACTIONABLE
    _append_chain_alert(
        alerts=alerts,
        source_item_id=chain["id"],
        now=now,
        message=message,
        details=_chain_stage_details(chain, stage, index, autonomy=autonomy, body=command),
        severity=severity,
    )
    rewake_messages.append(message)

    if autonomy == "confirm":
        chain["awaiting_confirmation"] = True
        chain["pending_stage_index"] = index
        chain["pending_dispatch"] = command
        return True, True, False

    return False, True, True


def _heartbeat_due(item: SchedulerItem, now: datetime) -> bool:
    interval = item.get("heartbeat_interval_minutes", DEFAULT_WATCH_CHAIN_HEARTBEAT_MINUTES)
    if not isinstance(interval, int) or interval <= 0:
        interval = DEFAULT_WATCH_CHAIN_HEARTBEAT_MINUTES
    last = (
        item.get("last_heartbeat_at")
        or item.get("current_stage_started_at")
        or item.get("created_at")
    )
    if not isinstance(last, str) or not last:
        return True
    try:
        return now >= datetime.fromisoformat(last) + timedelta(minutes=interval)
    except ValueError:
        return True


def _emit_watch_chain_heartbeat(
    item: SchedulerItem, now: datetime, alerts: list[AlertItem], rewake_messages: list[str]
) -> bool:
    stages = item.get("stages")
    if not isinstance(stages, list) or item.get("status") != "active" or not stages:
        return False
    if not _heartbeat_due(item, now):
        return False

    index = item.get("current_stage_index", 0)
    if not isinstance(index, int) or index < 0:
        index = 0
    if index >= len(stages):
        return False

    stage = stages[index]
    if not isinstance(stage, dict):
        return False

    stage_name = _chain_stage_name(stage, index)
    stage_count = len(stages)
    prefix = "awaiting confirmation for" if item.get("awaiting_confirmation") else "waiting on"
    message = f"{_chain_name(item)} heartbeat — {prefix} {stage_name} ({index + 1}/{stage_count})"
    _append_chain_alert(
        alerts=alerts,
        source_item_id=item["id"],
        now=now,
        message=message,
        details=_chain_stage_details(item, stage, index, total=stage_count),
        severity=SEVERITY_HEARTBEAT,
    )
    rewake_messages.append(message)
    item["last_heartbeat_at"] = now.isoformat()
    return True


def _process_watch_chain(
    item: SchedulerItem,
    now: datetime,
    alerts: list[AlertItem],
    rewake_messages: list[str],
) -> tuple[bool, bool]:
    """Advance a watch chain as far as possible for this hook invocation."""
    stages = item.get("stages")
    if not isinstance(stages, list) or not stages:
        return False, False

    items_modified = False
    alerts_modified = False
    stage_progressed = False
    index = item.get("current_stage_index", 0)
    if not isinstance(index, int) or index < 0:
        index = 0
        item["current_stage_index"] = 0
        items_modified = True

    while item.get("status") == "active" and index < len(stages):
        stage = stages[index]
        if not isinstance(stage, dict):
            break
        if item.get("awaiting_confirmation"):
            break

        watch_item = _build_chain_stage_watch_item(item, stage, index)
        if watch_item is not None:
            last = item.get("last_checked_at")
            interval = watch_item.get("poll_interval_minutes", 30)
            if last:
                try:
                    next_check = datetime.fromisoformat(last) + timedelta(minutes=interval)
                except ValueError:
                    next_check = now
                if now < next_check:
                    break

            new_state, changed = poll_watch(watch_item)
            # Record the attempt before bailing out. A stage whose poll keeps
            # failing would otherwise never advance last_checked_at, so it would
            # re-poll on every tick and stall the chain with nothing logged.
            failures = record_poll_attempt(item, now.isoformat(), new_state)
            items_modified = True
            if new_state is None:
                log = logger.warning if should_warn_for_failures(failures) else logger.debug
                log(
                    "chain %s stage %d failed to return state — %d consecutive failure(s)",
                    item["id"][:8],
                    index,
                    failures,
                )
                break

            item["last_state"] = new_state

            if not changed:
                break

            autonomy = _chain_stage_autonomy(item, stage)
            severity = SEVERITY_INFO if autonomy == "notify-only" else SEVERITY_ACTIONABLE
            message = _format_watch_alert(watch_item, new_state)
            _append_chain_alert(
                alerts=alerts,
                source_item_id=item["id"],
                now=now,
                message=message,
                details=_chain_stage_details(
                    item, stage, index, body=json.dumps(new_state, sort_keys=True)
                ),
                severity=severity,
            )
            rewake_messages.append(message)
            alerts_modified = True

        action_items_modified, action_alerts_modified, should_advance = _run_chain_action(
            item, stage, index, now, alerts, rewake_messages
        )
        items_modified = items_modified or action_items_modified
        alerts_modified = alerts_modified or action_alerts_modified
        if not should_advance:
            break

        stage_progressed = True
        index += 1
        if index >= len(stages):
            item["current_stage_index"] = index
            item["status"] = "done"
            item["completed_at"] = now.isoformat()
            items_modified = True
            message = f"{_chain_name(item)} complete"
            _append_chain_alert(
                alerts=alerts,
                source_item_id=item["id"],
                now=now,
                message=message,
                details=_chain_stage_details(item, stage, max(index - 1, 0)),
                severity=SEVERITY_INFO,
            )
            rewake_messages.append(message)
            alerts_modified = True
            break

        _advance_watch_chain(item, index, now)
        items_modified = True

    if not stage_progressed and _emit_watch_chain_heartbeat(item, now, alerts, rewake_messages):
        items_modified = True
        alerts_modified = True

    return items_modified, alerts_modified


def _extract_watch_updates(raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized pushed watch updates from a hook payload."""
    updates: list[dict[str, Any]] = []
    for container in (raw_payload, raw_payload.get("tool_input", {})):
        if not isinstance(container, dict):
            continue
        singular = container.get("watch_update")
        if isinstance(singular, dict):
            updates.append(singular)
        plural = container.get("watch_updates")
        if isinstance(plural, list):
            updates.extend(update for update in plural if isinstance(update, dict))
    return updates


def _watch_update_key(provider: str, watch_config: dict[str, Any] | None) -> str | None:
    """Build a stable lookup key for matching pushed updates to active watches."""
    if not provider or not isinstance(watch_config, dict):
        return None
    try:
        return json.dumps({"provider": provider, "watch_config": watch_config}, sort_keys=True)
    except TypeError:
        return None


def _process_hook_watch_state(
    item: SchedulerItem,
    new_state: WatchState,
    now: datetime,
    alerts: list[AlertItem],
    rewake_messages: list[str],
) -> tuple[bool, bool]:
    """Persist a watch state update and emit any resulting alert."""
    from aya.scheduler.display import _create_alert as create_alert
    from aya.scheduler.providers import _evaluate_auto_remove, detect_watch_change

    changed = detect_watch_change(item, new_state)
    # Reached both from a poll and from a pushed hook update. Going through
    # record_poll_attempt keeps one owner of the stamp-and-counter bookkeeping,
    # so a push that supplies state also clears any accumulated failures. It is
    # idempotent, so the poll path calling it first is harmless.
    record_poll_attempt(item, now.isoformat(), new_state)
    item["last_state"] = new_state

    alerts_modified = False
    if changed:
        alert_msg = _format_watch_alert(item, new_state)
        alert = create_alert(
            source_item_id=item["id"],
            message=alert_msg,
            # WatchState carries provider-specific keys AlertDetails does not
            # declare; the alert store keeps them verbatim.
            details=cast(AlertDetails, dict(new_state)),
            now=now,
        )
        alerts.append(alert)
        alerts_modified = True
        rewake_messages.append(alert_msg)

    if _evaluate_auto_remove(item, new_state):
        item["status"] = "dismissed"

    return True, alerts_modified


def _hook_watch_impl(payload: dict[str, Any]) -> int:
    """Core logic for hook watch — testable without typer.Exit."""
    from aya.scheduler.storage import (
        _alerts_file,
        _atomic_write,
        _load_alerts_unlocked,
        _scheduler_file,
    )
    from aya.scheduler.types import _alerts_data, _scheduler_data

    now = _hook_watch_now()
    rewake_messages: list[str] = []
    push_updates_by_key: dict[str, list[dict[str, Any]]] = {}
    for update in _extract_watch_updates(payload):
        key = _watch_update_key(update.get("provider", ""), update.get("watch_config"))
        if key is None:
            continue
        push_updates_by_key.setdefault(key, []).append(update)

    # ── Step 1: detect git push → create ci-checks watch ────────────────
    command = payload.get("tool_input", {}).get("command", "")
    if "git push" in command:
        _maybe_create_ci_watch()

    # ── Step 2: poll all due watches ────────────────────────────────────
    with _file_lock():
        items = _load_items_unlocked()
        alerts = _load_alerts_unlocked()
        items_modified = False
        alerts_modified = False
        # Alerts already on disk before this run. Anything not in here was
        # raised by this hook, which reports it directly — the sweep below must
        # stamp those without announcing them a second time.
        pre_existing_alert_ids = {a["id"] for a in alerts}

        for item in items:
            if _is_watch_chain(item) and item.get("status") == "active":
                chain_items_modified, chain_alerts_modified = _process_watch_chain(
                    item, now, alerts, rewake_messages
                )
                items_modified = items_modified or chain_items_modified
                alerts_modified = alerts_modified or chain_alerts_modified
                continue

            if item.get("type") != "watch" or item.get("status") != "active":
                continue

            update_key = _watch_update_key(
                item.get("provider", ""), cast("dict[str, Any] | None", item.get("watch_config"))
            )
            matching_updates = push_updates_by_key.get(update_key or "", [])
            if matching_updates:
                push_consumed = False
                for update in matching_updates:
                    state = update.get("state")
                    if not isinstance(state, dict):
                        logger.debug("Skipping malformed watch update for %s", item.get("id", "?"))
                        continue
                    try:
                        item_changed, alerts_changed = _process_hook_watch_state(
                            item,
                            cast(Any, state),
                            now,
                            alerts,
                            rewake_messages,
                        )
                    except (KeyError, TypeError) as e:
                        logger.warning(
                            "Skipping bad pushed state for watch %s: %s", item.get("id", "?"), e
                        )
                        continue
                    push_consumed = True
                    items_modified = items_modified or item_changed
                    alerts_modified = alerts_modified or alerts_changed
                    if item.get("status") != "active":
                        break
                if push_consumed:
                    continue

            # Respect poll interval
            last = item.get("last_checked_at")
            interval = item.get("poll_interval_minutes", 30)
            if last:
                next_check = datetime.fromisoformat(last) + timedelta(minutes=interval)
                if now < next_check:
                    continue

            new_state, _changed = poll_watch(item)
            failures = record_poll_attempt(item, now.isoformat(), new_state)
            items_modified = True
            if new_state is None:
                log = logger.warning if should_warn_for_failures(failures) else logger.debug
                log(
                    "hook watch %s (%s) failed to return state — %d consecutive failure(s)",
                    item["id"][:8],
                    item.get("provider", "unknown"),
                    failures,
                )
                continue

            item_changed, alerts_changed = _process_hook_watch_state(
                item,
                new_state,
                now,
                alerts,
                rewake_messages,
            )
            items_modified = items_modified or item_changed
            alerts_modified = alerts_modified or alerts_changed

        if items_modified:
            _atomic_write(_scheduler_file(), _scheduler_data(items))
        if alerts_modified:
            _atomic_write(_alerts_file(), _alerts_data(alerts))

    # ── Step 2b: announce alerts this session has not been told about ───
    #
    # The crontab tick polls the same watches on a shorter cadence, so it
    # usually wins the race and consumes the change itself. It has no session to
    # speak into, so its alert sat unseen while this hook — finding nothing new
    # — stayed silent. Delivering here decouples "who polled" from "who tells
    # the agent", so a packet ingested by the tick still surfaces.
    #
    # Called outside the lock above: claim_alerts_for_delivery takes the same
    # file lock to stamp its receipts.
    from aya.scheduler.core import claim_alerts_for_delivery

    for alert in claim_alerts_for_delivery(skip_delivered=True):
        # Alerts raised by this run are already in rewake_messages; the claim
        # call still stamps them, which is what stops the next tool call from
        # announcing them again.
        if alert["id"] in pre_existing_alert_ids:
            rewake_messages.append(alert["message"])

    # ── Step 3: emit single asyncRewake with all changes ────────────────
    if rewake_messages:
        rewake_emit(" | ".join(rewake_messages))
        return 2
    return 0


def _maybe_create_ci_watch() -> None:
    """If this was a git push to a GitHub PR branch, create a ci-checks watch."""
    timeout = 15

    def _run_cmd(cmd: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            return result.returncode, (result.stdout or "").strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return 127, ""

    rc, remote = _run_cmd(["git", "remote", "get-url", "origin"])
    if rc != 0 or "github.com" not in remote:
        return

    rc, branch = _run_cmd(["git", "branch", "--show-current"])
    if rc != 0 or not branch or branch in ("main", "master"):
        return

    # Parse owner/repo via gh CLI (handles all URL formats including dots in names)
    rc, name_with_owner = _run_cmd(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]
    )
    if rc != 0 or "/" not in name_with_owner:
        return
    owner, repo = name_with_owner.split("/", 1)

    # Check if PR exists for this branch
    rc, pr_num = _run_cmd(
        [
            "gh",
            "pr",
            "view",
            branch,
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "number",
            "-q",
            ".number",
        ]
    )
    if rc != 0 or not pr_num:
        return

    # Check if we already have an active ci-checks watch for this PR
    existing = get_active_watches()
    for w in existing:
        if w.get("provider") != "ci-checks":
            continue
        cfg: dict[str, Any] = dict(w.get("watch_config") or {})
        if cfg.get("owner") == owner and cfg.get("repo") == repo and cfg.get("pr") == int(pr_num):
            return  # already watching

    add_watch(
        provider="ci-checks",
        target=f"{owner}/{repo}#{pr_num}",
        message=f"CI checks on PR #{pr_num} ({owner}/{repo}, branch: {branch})",
        condition="checks_failed",
        interval=1,
        remove_when="checks_complete",
    )
