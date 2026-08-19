"""The watch target spec — one grammar, both directions.

``validate_watch`` parses the target string a user types into the ``watch_config``
a watch stores; ``watch_target`` renders it back for display. They are inverses,
so they live together: the failure this module exists to prevent is the two
drifting apart, which is how a documented ``target`` field ended up being emitted
by no display surface at all.

Kept out of ``core`` because ``core`` imports ``display`` and both need the
renderer. Neither function touches storage or the clock, so nothing is lost by
sitting below them.
"""

from __future__ import annotations

import re

from .types import (
    CONDITION_APPROVED_OR_MERGED,
    CONDITION_CHECKS_COMPLETE,
    CONDITION_CHECKS_FAILED,
    CONDITION_MERGED,
    CONDITION_NEW_COMMENTS,
    CONDITION_NEW_PACKETS,
    CONDITION_NEW_RESULTS,
    CONDITION_STATUS_CHANGED,
    PROVIDER_CI_CHECKS,
    PROVIDER_GITHUB_PR,
    PROVIDER_JIRA_QUERY,
    PROVIDER_JIRA_TICKET,
    PROVIDER_RELAY_INBOX,
    CiChecksConfig,
    GithubPrConfig,
    JiraQueryConfig,
    JiraTicketConfig,
    RelayInboxConfig,
    SchedulerItem,
)


def validate_watch(
    provider: str,
    target: str,
    condition: str = "",
    interval: int = 30,
) -> tuple[
    GithubPrConfig | JiraQueryConfig | JiraTicketConfig | CiChecksConfig | RelayInboxConfig,
    str,
    int,
]:
    """Validate a watch spec and normalise it to ``(config, condition, interval)``.

    Separate from :func:`add_watch` so a caller can check a spec without
    creating anything — the CLI needs that for ``--dry-run``. Keeping it here
    means there is one definition of which providers and conditions are valid;
    the CLI previously re-implemented a narrower gate that never learned about
    ``ci-checks`` and rejected specs the MCP surface accepted.

    Raises ``ValueError`` describing the problem.
    """
    watch_config: (
        GithubPrConfig | JiraQueryConfig | JiraTicketConfig | CiChecksConfig | RelayInboxConfig
    )

    if provider == PROVIDER_GITHUB_PR:
        m = re.match(r"([^/]+)/([^#]+)#(\d+)", target)
        if not m:
            raise ValueError("Format: owner/repo#123")
        watch_config = {"owner": m.group(1), "repo": m.group(2), "pr": int(m.group(3))}
        condition = condition or CONDITION_APPROVED_OR_MERGED
        _valid = {CONDITION_APPROVED_OR_MERGED, CONDITION_MERGED, CONDITION_NEW_COMMENTS, ""}
        if condition not in _valid:
            raise ValueError(
                f"Unknown condition '{condition}' for github-pr. "
                f"Valid: approved_or_merged, merged, new_comments"
            )
        if interval == 30:
            interval = 5
    elif provider == PROVIDER_CI_CHECKS:
        m = re.match(r"([^/]+)/([^#]+)#(\d+)", target)
        if not m:
            raise ValueError("Format: owner/repo#123")
        watch_config = {
            "owner": m.group(1),
            "repo": m.group(2),
            "pr": int(m.group(3)),
        }
        condition = condition or CONDITION_CHECKS_FAILED
        _valid_ci = {CONDITION_CHECKS_FAILED, CONDITION_CHECKS_COMPLETE, ""}
        if condition not in _valid_ci:
            raise ValueError(
                f"Unknown condition '{condition}' for ci-checks. "
                f"Valid: checks_failed, checks_complete"
            )
        if interval == 30:
            interval = 1
    elif provider == PROVIDER_JIRA_QUERY:
        watch_config = {"jql": target}
        condition = condition or CONDITION_NEW_RESULTS
        _valid_jq = {CONDITION_NEW_RESULTS, ""}
        if condition not in _valid_jq:
            raise ValueError(f"Unknown condition '{condition}' for jira-query. Valid: new_results")
    elif provider == PROVIDER_JIRA_TICKET:
        watch_config = {"ticket": target.upper()}
        condition = condition or CONDITION_STATUS_CHANGED
        _valid_jt = {CONDITION_STATUS_CHANGED, ""}
        if condition not in _valid_jt:
            raise ValueError(
                f"Unknown condition '{condition}' for jira-ticket. Valid: status_changed"
            )
    elif provider == PROVIDER_RELAY_INBOX:
        # The target names the local identity to poll as; "default" or "-" means
        # the primary instance, matching `aya receive` with no --as.
        watch_config = {} if target in {"", "default", "-"} else {"instance": target}
        condition = condition or CONDITION_NEW_PACKETS
        _valid_ri = {CONDITION_NEW_PACKETS, ""}
        if condition not in _valid_ri:
            raise ValueError(f"Unknown condition '{condition}' for relay-inbox. Valid: new_packets")
        if interval == 30:
            # The relay is cheap to poll and the point is conversational
            # latency, but every poll is a network round trip on a hook that
            # fires after each tool call, so two minutes rather than one.
            interval = 2
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return watch_config, condition, interval


def watch_target(item: SchedulerItem) -> str | None:
    """The target a watch points at, as one readable string.

    The inverse of :func:`validate_watch` above: a watch stores only the parsed
    ``watch_config``, so the target the user typed exists nowhere on the item and
    every display surface would otherwise reassemble it by hand. Rendering is
    canonical rather than literal — ``validate_watch`` upper-cases a Jira key and
    collapses the three ways of naming the primary relay instance into one, and
    the stored form is the truth.

    Returns None when the provider is unknown or the config lacks the fields it
    needs, so a caller falls back to the watch's ``message`` rather than printing
    half a target.
    """
    provider = item.get("provider")
    config = item.get("watch_config") or {}
    if not isinstance(config, dict):
        return None

    if provider in {PROVIDER_GITHUB_PR, PROVIDER_CI_CHECKS}:
        owner, repo, pr = config.get("owner"), config.get("repo"), config.get("pr")
        if owner is not None and repo is not None and pr is not None:
            return f"{owner}/{repo}#{pr}"
        return None
    if provider == PROVIDER_JIRA_QUERY:
        jql = config.get("jql")
        return str(jql) if jql else None
    if provider == PROVIDER_JIRA_TICKET:
        ticket = config.get("ticket")
        return str(ticket) if ticket else None
    if provider == PROVIDER_RELAY_INBOX:
        # An empty config is the documented "poll as the primary instance"
        # case, so it has a target to show rather than nothing.
        instance = config.get("instance")
        return str(instance) if instance else "default"
    return None


_TARGET_DISPLAY_LIMIT = 40


def truncate_target(target: str) -> str:
    """Bound a target for the width-constrained text surfaces.

    A ``jira-query`` target is raw JQL with no length limit, and every other
    field on these lines is already truncated; leaving one field unbounded pushes
    the others off-screen. The JSON surface keeps the full value.
    """
    if len(target) <= _TARGET_DISPLAY_LIMIT:
        return target
    return target[: _TARGET_DISPLAY_LIMIT - 1] + "\u2026"
