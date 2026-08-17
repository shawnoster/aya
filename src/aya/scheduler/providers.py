"""Watch providers — GitHub PR, Jira query, Jira ticket polling and change detection."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from typing import Any, cast

from .types import (
    CiChecksConfig,
    CiChecksState,
    GithubPrConfig,
    GithubPrState,
    JiraQueryConfig,
    JiraQueryState,
    JiraTicketConfig,
    JiraTicketState,
    SchedulerItem,
    WatchState,
)

logger = logging.getLogger(__name__)

# ── Jira credentials ─────────────────────────────────────────────────────────


def _get_jira_credentials() -> tuple[str, str, str]:
    """Extract Jira credentials from environment. Returns (email, token, server)."""
    email = os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("ATLASSIAN_API_TOKEN", "")
    server = os.environ.get("ATLASSIAN_SERVER_URL", "").rstrip("/")
    return email, token, server


# ── watch providers ──────────────────────────────────────────────────────────

_gh_missing_warned: bool = False


def _run_gh(args: list[str], timeout: int = 15) -> dict[str, Any] | list[Any] | None:
    """Run the gh CLI and parse its JSON output.

    Parseable JSON on stdout is the success signal, not the exit code. ``gh pr
    checks`` reports check state *through* its exit code — 1 when a check has
    failed, 8 while checks are still pending — and writes the requested JSON
    either way, so a non-zero exit there carries a result rather than an error.

    Genuine failures (an invalid field, auth, no such pull request) write to
    stderr and leave stdout empty or non-JSON, and resolve to ``None``.
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if not result.stdout.strip():
            if result.returncode != 0:
                logger.debug(
                    "gh %s exited %d with no stdout: %s",
                    " ".join(args[:2]),
                    result.returncode,
                    result.stderr.strip()[:200],
                )
            return None
        parsed: dict[str, Any] | list[Any] | None = json.loads(result.stdout)
        return parsed
    except FileNotFoundError:
        global _gh_missing_warned  # noqa: PLW0603
        if not _gh_missing_warned:
            logger.warning(
                "GitHub CLI ('gh') not installed — GitHub watch features disabled. "
                "Install: https://cli.github.com/"
            )
            _gh_missing_warned = True
        return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.debug("gh command failed: %s", e)
        return None


_GITHUB_PR_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      state
      merged
      isDraft
      title
      reviews(first: 100) {
        nodes {
          author { login }
          state
        }
      }
      comments { totalCount }
      reviewThreads(first: 100) {
        nodes {
          comments { totalCount }
        }
      }
    }
  }
}
"""


def _check_github_pr(config: GithubPrConfig) -> GithubPrState | None:
    """Check GitHub PR status, reviews, and comment counts via a single GraphQL call."""
    owner = config["owner"]
    repo = config["repo"]
    pr = config["pr"]

    data = _run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={_GITHUB_PR_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
            "-F",
            f"pr={pr}",
        ]
    )
    if not data or not isinstance(data, dict):
        return None

    repository = (data.get("data") or {}).get("repository")
    if not isinstance(repository, dict):
        return None
    pr_data = repository.get("pullRequest")
    if not pr_data or not isinstance(pr_data, dict):
        return None

    raw_state = pr_data.get("state", "")
    # GraphQL uses OPEN/CLOSED/MERGED; map to lowercase REST-style
    # (REST returns state:"closed" for both merged and unmerged closed PRs)
    if raw_state == "MERGED":
        pr_state: str | None = "closed"
    elif raw_state:
        pr_state = raw_state.lower()
    else:
        pr_state = None

    reviews_nodes = pr_data.get("reviews", {}).get("nodes", [])
    # NOTE: reviews are fetched up to first 100; PRs with >100 reviews may have
    # incomplete approval status. This is an accepted limitation.
    reviews: list[dict[str, Any]] = [
        {"user": node["author"]["login"], "state": node["state"]}
        for node in reviews_nodes
        if node.get("author")
    ]

    review_thread_nodes = (pr_data.get("reviewThreads") or {}).get("nodes", [])
    review_comment_count = sum(
        (node.get("comments") or {}).get("totalCount", 0) for node in review_thread_nodes
    )
    comment_count = (pr_data.get("comments") or {}).get("totalCount", 0) + review_comment_count

    return GithubPrState(
        pr_state=pr_state,
        merged=pr_data.get("merged", False),
        draft=pr_data.get("isDraft", False),
        title=pr_data.get("title", ""),
        reviews=reviews,
        has_approval=any(r.get("state") == "APPROVED" for r in reviews),
        comment_count=comment_count,
    )


def _check_jira_query(config: JiraQueryConfig) -> JiraQueryState | None:
    """Run a JQL query and return results."""
    jql = config["jql"]
    email, token, server = _get_jira_credentials()

    if not all([email, token, server]):
        return None

    try:
        import httpx

        resp = httpx.post(
            f"{server}/rest/api/3/search",
            auth=(email, token),
            json={"jql": jql, "maxResults": 20, "fields": ["key", "summary", "status"]},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "total": data.get("total", 0),
            "issues": [
                {
                    "key": i["key"],
                    "summary": i["fields"]["summary"],
                    "status": i["fields"]["status"]["name"],
                }
                for i in data.get("issues", [])
            ],
        }
    except Exception as e:  # noqa: BLE001 — network, auth and payload-shape all land here
        # Warning, not debug: a failed check returns None, which the caller
        # cannot tell apart from "no change", so the log is the only signal
        # that a watch has silently stopped working.
        logger.warning("Jira query watch failed for %s: %s", config.get("jql", "?"), e)
        return None


def _check_jira_ticket(config: JiraTicketConfig) -> JiraTicketState | None:
    """Check a specific Jira ticket's status."""
    ticket = config["ticket"]
    email, token, server = _get_jira_credentials()

    if not all([email, token, server]):
        return None

    try:
        import httpx

        resp = httpx.get(
            f"{server}/rest/api/3/issue/{ticket}",
            auth=(email, token),
            params={"fields": "summary,status,assignee,priority"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        fields = data.get("fields", {})
        return {
            "key": data["key"],
            "summary": fields.get("summary", ""),
            "status": fields.get("status", {}).get("name", ""),
            "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
        }
    except Exception as e:  # noqa: BLE001 — network, auth and payload-shape all land here
        logger.warning("Jira ticket watch failed for %s: %s", ticket, e)
        return None


def _check_ci_checks(config: CiChecksConfig) -> CiChecksState | None:
    """Check CI status for a PR via gh pr checks."""
    owner = config["owner"]
    repo = config["repo"]
    pr = config["pr"]

    data = _run_gh(
        [
            "pr",
            "checks",
            str(pr),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "name,state,bucket",
        ]
    )
    if not isinstance(data, list):
        return None

    passed: list[str] = []
    failed: list[str] = []
    pending: list[str] = []

    for check in data:
        name = check.get("name", "unknown")
        # `bucket` is gh's rollup of a check's outcome: pass, fail, pending,
        # skipping, or cancel. `gh pr checks` exposes no `conclusion` field —
        # asking for one makes gh exit non-zero having emitted no JSON at all,
        # so keep the requested fields to what `gh pr checks --json` accepts.
        # `state` is the raw upstream status, kept as a fallback for pending.
        bucket = check.get("bucket") or ""
        status = check.get("state", "")

        if bucket == "pending" or status in ("PENDING", "IN_PROGRESS", "QUEUED"):
            pending.append(name)
        elif bucket in ("fail", "cancel"):
            failed.append(name)
        else:
            # pass and skipping both count as done-and-not-blocking.
            passed.append(name)

    return CiChecksState(
        all_complete=len(pending) == 0,
        passed=passed,
        failed=failed,
        pending=pending,
    )


WATCH_PROVIDERS: dict[str, Callable[..., WatchState | None]] = {
    "github-pr": _check_github_pr,
    "jira-query": _check_jira_query,
    "jira-ticket": _check_jira_ticket,
    "ci-checks": _check_ci_checks,
}


# ── change detection strategies ──────────────────────────────────────────────


def _detect_json_diff(new: WatchState, last: WatchState | None) -> bool:
    """Detect change by comparing JSON dumps."""
    return json.dumps(new, sort_keys=True) != json.dumps(last, sort_keys=True)


def _detect_github_approved_or_merged(new: GithubPrState, last: GithubPrState | None) -> bool:
    """Detect if PR was approved or merged."""
    was_approved = last["has_approval"] if last else False
    was_merged = last["merged"] if last else False
    return (new["has_approval"] and not was_approved) or (new["merged"] and not was_merged)


def _detect_github_merged(new: GithubPrState, last: GithubPrState | None) -> bool:
    """Detect if PR was merged."""
    return new["merged"] and not (last["merged"] if last else False)


def _detect_github_new_comments(new: GithubPrState, last: GithubPrState | None) -> bool:
    """Detect if new comments have been added to the PR since last poll.

    Does not fire on the first poll (no baseline to diff against).
    Does not fire if the count decreased (comment deleted).
    """
    if last is None:
        return False
    return new["comment_count"] > last["comment_count"]


def _detect_jira_new_results(new: JiraQueryState, last: JiraQueryState | None) -> bool:
    """Detect new issues in Jira query results."""
    old_keys = {i["key"] for i in last["issues"]} if last else set()
    new_keys = {i["key"] for i in new["issues"]}
    return bool(new_keys - old_keys)


def _detect_jira_count_change(new: JiraQueryState, last: JiraQueryState | None) -> bool:
    """Detect change in Jira query result count."""
    return new["total"] != (last["total"] if last else 0)


def _detect_jira_status_changed(new: JiraTicketState, last: JiraTicketState | None) -> bool:
    """Detect if Jira ticket status changed."""
    return new["status"] != (last["status"] if last else None)


def _detect_ci_checks_failed(new: CiChecksState, _last: CiChecksState | None) -> bool:
    """Detect if any CI check failed (and checks are no longer pending)."""
    return new["all_complete"] and len(new["failed"]) > 0


def _detect_ci_checks_complete(new: CiChecksState, _last: CiChecksState | None) -> bool:
    """Detect if all CI checks finished (pass or fail)."""
    return new["all_complete"]


_CHANGE_DETECTORS: dict[tuple[str, str], Callable[[Any, Any], bool]] = {
    ("github-pr", "approved_or_merged"): _detect_github_approved_or_merged,
    ("github-pr", "merged"): _detect_github_merged,
    ("github-pr", "new_comments"): _detect_github_new_comments,
    ("github-pr", ""): _detect_json_diff,
    ("jira-query", "new_results"): _detect_jira_new_results,
    ("jira-query", ""): _detect_jira_count_change,
    ("jira-ticket", "status_changed"): _detect_jira_status_changed,
    ("jira-ticket", ""): _detect_json_diff,
    ("ci-checks", "checks_failed"): _detect_ci_checks_failed,
    ("ci-checks", "checks_complete"): _detect_ci_checks_complete,
    ("ci-checks", ""): _detect_ci_checks_complete,
}


def poll_watch(item: SchedulerItem) -> tuple[WatchState | None, bool]:
    """Poll a watch item. Returns (new_state, changed)."""
    provider = item.get("provider", "")
    check_fn = WATCH_PROVIDERS.get(provider)
    if not check_fn:
        return None, False

    watch_config = item.get("watch_config")
    if watch_config is None:
        return None, False
    new_state = check_fn(watch_config)
    if new_state is None:
        return None, False

    return new_state, detect_watch_change(item, new_state)


# Consecutive-failure counts at which a failing watch warrants a WARNING rather
# than a DEBUG log. A watch polls as often as every minute, so warning on every
# failure buries the signal; warning on a widening set of milestones — and then
# every _FAILURE_LOG_EVERY after the last one — keeps a persistent failure
# visible in the log forever without repeating it on every tick.
_FAILURE_LOG_STEPS = frozenset({1, 3, 10, 50, 100, 500})
_FAILURE_LOG_EVERY = 500


def record_poll_attempt(item: SchedulerItem, now_iso: str, new_state: WatchState | None) -> int:
    """Record that a watch was polled, and return its consecutive-failure count.

    Every poll site must call this, because ``last_checked_at`` is both the
    "when did we last look" record and the poll-interval gate. Advancing it only
    on success leaves a watch that can never succeed re-polling on every tick,
    producing no alert and never satisfying its ``remove_when``.

    ``consecutive_failures`` is what stops the stamp from making a broken watch
    look healthy: the status views render ``last_checked_at`` as "checked
    HH:MM", so without a counter a permanent failure is indistinguishable from a
    recent success. Returns 0 when the poll succeeded.
    """
    item["last_checked_at"] = now_iso
    if new_state is None:
        failures = item.get("consecutive_failures", 0) + 1
        item["consecutive_failures"] = failures
        return failures
    item["consecutive_failures"] = 0
    return 0


def should_warn_for_failures(failures: int) -> bool:
    """Whether this consecutive-failure count should be logged at WARNING."""
    return failures in _FAILURE_LOG_STEPS or (
        failures > max(_FAILURE_LOG_STEPS) and failures % _FAILURE_LOG_EVERY == 0
    )


def detect_watch_change(item: SchedulerItem, new_state: WatchState) -> bool:
    """Detect whether a watch's state transition should fire an alert."""
    provider = item.get("provider", "")
    last_state = item.get("last_state")
    condition = item.get("condition", "")
    detector = _CHANGE_DETECTORS.get((provider, condition))
    if not detector:
        return False
    try:
        return detector(new_state, last_state)
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("watch change detection failed for provider %s: %s", provider, exc)
        return False


def _evaluate_auto_remove(item: SchedulerItem, state: WatchState) -> bool:
    """Check if a watch should be auto-removed based on remove_when condition."""
    remove_when = item.get("remove_when", "")
    if not remove_when:
        return False
    if remove_when == "merged_or_closed" and item.get("provider") == "github-pr":
        gh_state = cast(GithubPrState, state)
        return gh_state["merged"] or gh_state["pr_state"] == "closed"
    if remove_when == "checks_complete" and item.get("provider") == "ci-checks":
        ci_state = cast(CiChecksState, state)
        return ci_state["all_complete"]
    return False
