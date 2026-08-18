"""Tests for scheduler/providers.py — watch provider polling and change detection."""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from aya.scheduler.providers import (
    _check_ci_checks,
    _check_github_pr,
    _check_jira_query,
    _check_jira_ticket,
    _detect_ci_checks_complete,
    _detect_ci_checks_failed,
    _detect_github_approved_or_merged,
    _detect_github_merged,
    _detect_github_new_comments,
    _detect_jira_count_change,
    _detect_jira_new_results,
    _detect_jira_status_changed,
    _detect_json_diff,
    _evaluate_auto_remove,
    _get_jira_credentials,
    _run_gh,
    detect_watch_change,
    poll_watch,
)
from aya.scheduler.types import (
    CiChecksState,
    GithubPrState,
    JiraQueryState,
    JiraTicketState,
    SchedulerItem,
)

# ── _get_jira_credentials ────────────────────────────────────────────────────


class TestGetJiraCredentials:
    def test_returns_empty_strings_when_not_set(self, monkeypatch):
        monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
        monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
        monkeypatch.delenv("ATLASSIAN_SERVER_URL", raising=False)
        email, token, server = _get_jira_credentials()
        assert email == ""
        assert token == ""
        assert server == ""

    def test_returns_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "user@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "secret-token")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com/")
        email, token, server = _get_jira_credentials()
        assert email == "user@example.com"
        assert token == "secret-token"
        assert server == "https://jira.example.com"  # trailing slash stripped

    def test_strips_trailing_slash_from_server(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com///")
        _, _, server = _get_jira_credentials()
        assert not server.endswith("/")


# ── _run_gh ──────────────────────────────────────────────────────────────────


class TestRunGh:
    def test_returns_dict_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"key": "value"}'
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["api", "/repos/owner/repo"])
        assert result == {"key": "value"}

    def test_returns_list_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[{"id": 1}, {"id": 2}]'
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["api", "/repos/owner/repo/pulls"])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_returns_none_on_nonzero_exit_with_no_stdout(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = 'Unknown JSON field: "conclusion"'
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["api", "/repos/owner/repo"])
        assert result is None

    @pytest.mark.parametrize("code", [1, 8])
    def test_returns_json_on_nonzero_exit_when_stdout_parses(self, code):
        # `gh pr checks` reports check state through its exit code — 1 when a
        # check failed, 8 while checks are pending — and still writes the
        # requested JSON. Those are results, not errors.
        mock_result = MagicMock()
        mock_result.returncode = code
        mock_result.stdout = '[{"name": "test", "state": "FAILURE", "bucket": "fail"}]'
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["pr", "checks", "42", "--json", "name,state,bucket"])
        assert isinstance(result, list)
        assert result[0]["bucket"] == "fail"

    def test_returns_none_on_empty_stdout(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   "
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["api", "/repos/owner/repo"])
        assert result is None

    def test_returns_none_when_gh_missing(self):
        import aya.scheduler.providers as prov_mod

        prov_mod._gh_missing_warned = False
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = _run_gh(["api", "/anything"])
        assert result is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 15)):
            result = _run_gh(["api", "/repos/owner/repo"])
        assert result is None

    def test_returns_none_on_json_decode_error(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-json"
        with patch("subprocess.run", return_value=mock_result):
            result = _run_gh(["api", "/repos/owner/repo"])
        assert result is None

    def test_gh_missing_warning_only_once(self, caplog):
        import aya.scheduler.providers as prov_mod

        prov_mod._gh_missing_warned = False
        import logging

        with (
            caplog.at_level(logging.WARNING, logger="aya.scheduler.providers"),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            _run_gh(["api", "/a"])
            _run_gh(["api", "/b"])
        warning_msgs = [r for r in caplog.records if "not installed" in r.message]
        assert len(warning_msgs) == 1


# ── _check_github_pr ─────────────────────────────────────────────────────────


class TestCheckGithubPr:
    def _pr_config(self):
        return {"owner": "acme", "repo": "widget", "pr": 42}

    def _graphql_response(
        self,
        *,
        state="OPEN",
        merged=False,
        is_draft=False,
        title="My PR",
        review_nodes=None,
        comments_count=0,
        review_thread_comment_counts=None,
    ):
        """Build a GraphQL response dict for _check_github_pr.

        review_thread_comment_counts: list of ints, one per review thread,
        where each int is the comment count for that thread.
        """
        thread_nodes = [
            {"comments": {"totalCount": c}} for c in (review_thread_comment_counts or [])
        ]
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "state": state,
                        "merged": merged,
                        "isDraft": is_draft,
                        "title": title,
                        "reviews": {"nodes": review_nodes if review_nodes is not None else []},
                        "comments": {"totalCount": comments_count},
                        "reviewThreads": {"nodes": thread_nodes},
                    }
                }
            }
        }

    def test_returns_none_when_gh_fails(self):
        with patch("aya.scheduler.providers._run_gh", return_value=None):
            result = _check_github_pr(self._pr_config())
        assert result is None

    def test_returns_none_when_pr_data_not_dict(self):
        with patch("aya.scheduler.providers._run_gh", return_value=[{"id": 1}]):
            result = _check_github_pr(self._pr_config())
        assert result is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"message": "Bad credentials", "documentation_url": "https://docs.github.com"},
            {"data": None, "errors": [{"message": "Could not resolve to a Repository"}]},
        ],
        ids=["http-error-body", "graphql-errors"],
    )
    def test_returns_none_on_json_error_payload(self, payload):
        # _run_gh hands back any parseable JSON, including gh's error bodies, so
        # this parsing is what keeps an error from being read as PR state.
        with patch("aya.scheduler.providers._run_gh", return_value=payload):
            result = _check_github_pr(self._pr_config())
        assert result is None

    def test_returns_none_when_pull_request_null(self):
        response = {"data": {"repository": {"pullRequest": None}}}
        with patch("aya.scheduler.providers._run_gh", return_value=response):
            result = _check_github_pr(self._pr_config())
        assert result is None

    def test_returns_none_when_repository_null(self):
        response = {"data": {"repository": None}}
        with patch("aya.scheduler.providers._run_gh", return_value=response):
            result = _check_github_pr(self._pr_config())
        assert result is None

    def test_open_pr_with_no_reviews(self):
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["pr_state"] == "open"
        assert result["merged"] is False
        assert result["has_approval"] is False
        assert result["reviews"] == []
        assert result["comment_count"] == 0

    def test_approved_pr(self):
        review_nodes = [{"author": {"login": "alice"}, "state": "APPROVED"}]
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(review_nodes=review_nodes),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["has_approval"] is True
        assert result["reviews"] == [{"user": "alice", "state": "APPROVED"}]

    def test_merged_pr(self):
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(state="MERGED", merged=True),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["merged"] is True
        assert result["pr_state"] == "closed"  # MERGED maps to "closed" for REST compatibility

    def test_closed_unmerged_pr(self):
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(state="CLOSED", merged=False),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["merged"] is False
        assert result["pr_state"] == "closed"

    def test_draft_pr(self):
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(is_draft=True),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["draft"] is True

    def test_comment_count_sums_comments_and_review_comments(self):
        # 2 issue comments + 1 thread with 1 comment = 3 total
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(comments_count=2, review_thread_comment_counts=[1]),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["comment_count"] == 3

    def test_comment_count_zero_when_no_comments(self):
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["comment_count"] == 0

    def test_review_node_without_author_skipped(self):
        review_nodes = [
            {"author": None, "state": "APPROVED"},
            {"author": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
        ]
        with patch(
            "aya.scheduler.providers._run_gh",
            return_value=self._graphql_response(review_nodes=review_nodes),
        ):
            result = _check_github_pr(self._pr_config())
        assert result is not None
        assert result["reviews"] == [{"user": "bob", "state": "CHANGES_REQUESTED"}]
        assert result["has_approval"] is False

    def test_single_gh_call_made(self):
        """_check_github_pr must issue exactly one gh api graphql call."""
        with patch("aya.scheduler.providers._run_gh") as mock_run:
            mock_run.return_value = self._graphql_response()
            _check_github_pr(self._pr_config())
        assert mock_run.call_count == 1
        args, _ = mock_run.call_args
        assert args[0][0] == "api"
        assert args[0][1] == "graphql"


# ── _check_jira_query ────────────────────────────────────────────────────────


class TestCheckJiraQuery:
    def test_returns_none_without_credentials(self, monkeypatch):
        monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
        monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
        monkeypatch.delenv("ATLASSIAN_SERVER_URL", raising=False)
        result = _check_jira_query({"jql": "project = TEST"})
        assert result is None

    def test_returns_state_on_success(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "total": 2,
            "issues": [
                {
                    "key": "TEST-1",
                    "fields": {"summary": "First issue", "status": {"name": "Open"}},
                },
                {
                    "key": "TEST-2",
                    "fields": {"summary": "Second issue", "status": {"name": "In Progress"}},
                },
            ],
        }
        with patch("httpx.post", return_value=mock_resp):
            result = _check_jira_query({"jql": "project = TEST"})
        assert result is not None
        assert result["total"] == 2
        assert len(result["issues"]) == 2
        assert result["issues"][0]["key"] == "TEST-1"

    def test_returns_none_on_non_200(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("httpx.post", return_value=mock_resp):
            result = _check_jira_query({"jql": "project = TEST"})
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        with patch("httpx.post", side_effect=Exception("connection failed")):
            result = _check_jira_query({"jql": "project = TEST"})
        assert result is None


# ── _check_jira_ticket ───────────────────────────────────────────────────────


class TestCheckJiraTicket:
    def test_returns_none_without_credentials(self, monkeypatch):
        monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
        monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
        monkeypatch.delenv("ATLASSIAN_SERVER_URL", raising=False)
        result = _check_jira_ticket({"ticket": "CSD-123"})
        assert result is None

    def test_returns_state_on_success(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "key": "CSD-123",
            "fields": {
                "summary": "My ticket",
                "status": {"name": "In Review"},
                "assignee": {"displayName": "Alice"},
                "priority": {"name": "High"},
            },
        }
        with patch("httpx.get", return_value=mock_resp):
            result = _check_jira_ticket({"ticket": "CSD-123"})
        assert result is not None
        assert result["key"] == "CSD-123"
        assert result["status"] == "In Review"
        assert result["assignee"] == "Alice"

    def test_unassigned_ticket(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "key": "CSD-456",
            "fields": {
                "summary": "Unassigned ticket",
                "status": {"name": "Open"},
                "assignee": None,
            },
        }
        with patch("httpx.get", return_value=mock_resp):
            result = _check_jira_ticket({"ticket": "CSD-456"})
        assert result is not None
        assert result["assignee"] == "Unassigned"

    def test_returns_none_on_non_200(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("httpx.get", return_value=mock_resp):
            result = _check_jira_ticket({"ticket": "CSD-999"})
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
        monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
        monkeypatch.setenv("ATLASSIAN_SERVER_URL", "https://jira.example.com")
        with patch("httpx.get", side_effect=Exception("timeout")):
            result = _check_jira_ticket({"ticket": "CSD-123"})
        assert result is None


# ── _check_ci_checks ─────────────────────────────────────────────────────────


class TestCheckCiChecks:
    def _config(self):
        return {"owner": "acme", "repo": "widget", "pr": 42}

    def test_returns_none_when_gh_fails(self):
        with patch("aya.scheduler.providers._run_gh", return_value=None):
            result = _check_ci_checks(self._config())
        assert result is None

    def test_returns_none_when_not_list(self):
        with patch("aya.scheduler.providers._run_gh", return_value={"not": "list"}):
            result = _check_ci_checks(self._config())
        assert result is None

    # Payloads below mirror real `gh pr checks --json name,state,bucket` output:
    # uppercase `state`, plus gh's `bucket` rollup. Keep fixtures in that shape —
    # one carrying a field gh does not return (e.g. `conclusion`) passes here
    # while every real poll fails.

    def test_all_passed(self):
        checks = [
            {"name": "lint", "state": "SUCCESS", "bucket": "pass"},
            {"name": "test", "state": "SUCCESS", "bucket": "pass"},
        ]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert result["all_complete"] is True
        assert result["passed"] == ["lint", "test"]
        assert result["failed"] == []
        assert result["pending"] == []

    def test_some_failed(self):
        checks = [
            {"name": "lint", "state": "SUCCESS", "bucket": "pass"},
            {"name": "test", "state": "FAILURE", "bucket": "fail"},
        ]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert result["all_complete"] is True
        assert "test" in result["failed"]
        assert "lint" in result["passed"]

    def test_some_pending(self):
        checks = [
            {"name": "build", "state": "IN_PROGRESS", "bucket": "pending"},
            {"name": "test", "state": "SUCCESS", "bucket": "pass"},
        ]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert result["all_complete"] is False
        assert "build" in result["pending"]

    def test_cancelled_counts_as_failed(self):
        checks = [{"name": "deploy", "state": "CANCELLED", "bucket": "cancel"}]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert result["failed"] == ["deploy"]

    def test_skipped_counts_as_passed(self):
        # A skipped check is done and not blocking, so it must not hold
        # all_complete open or read as a failure.
        checks = [{"name": "optional-e2e", "state": "SKIPPED", "bucket": "skipping"}]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert result["passed"] == ["optional-e2e"]
        assert result["all_complete"] is True

    def test_requests_bucket_and_never_conclusion(self):
        # Regression guard: `conclusion` is not a valid `gh pr checks` field, and
        # asking for it makes gh exit non-zero with no JSON at all.
        with patch("aya.scheduler.providers._run_gh", return_value=[]) as mock_gh:
            _check_ci_checks(self._config())
        requested = mock_gh.call_args[0][0]
        assert "--json" in requested
        fields = requested[requested.index("--json") + 1]
        assert "bucket" in fields
        assert "conclusion" not in fields

    def test_timed_out_check_goes_to_failed(self):
        # gh has no distinct timed-out bucket; a timeout rolls up as `fail`.
        checks = [{"name": "slow-test", "state": "TIMED_OUT", "bucket": "fail"}]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert "slow-test" in result["failed"]

    def test_cancelled_check_goes_to_failed(self):
        checks = [{"name": "deploy", "state": "CANCELLED", "bucket": "cancel"}]
        with patch("aya.scheduler.providers._run_gh", return_value=checks):
            result = _check_ci_checks(self._config())
        assert result is not None
        assert "deploy" in result["failed"]


# ── change detectors ─────────────────────────────────────────────────────────


class TestDetectJsonDiff:
    def test_same_state_no_change(self):
        state = {"key": "value"}
        assert _detect_json_diff(state, state) is False

    def test_different_state_detected(self):
        assert _detect_json_diff({"key": "new"}, {"key": "old"}) is True

    def test_none_last_triggers_change(self):
        assert _detect_json_diff({"key": "val"}, None) is True


class TestDetectGithubApprovedOrMerged:
    def _state(self, *, has_approval=False, merged=False):
        return GithubPrState(
            pr_state="open",
            merged=merged,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=has_approval,
            comment_count=0,
        )

    def test_no_change(self):
        new = self._state(has_approval=True)
        last = self._state(has_approval=True)
        assert _detect_github_approved_or_merged(new, last) is False

    def test_newly_approved(self):
        new = self._state(has_approval=True)
        last = self._state(has_approval=False)
        assert _detect_github_approved_or_merged(new, last) is True

    def test_newly_merged(self):
        new = self._state(merged=True)
        last = self._state(merged=False)
        assert _detect_github_approved_or_merged(new, last) is True

    def test_no_last_state(self):
        new = self._state(has_approval=True)
        assert _detect_github_approved_or_merged(new, None) is True


class TestDetectGithubMerged:
    def _state(self, merged=False):
        return GithubPrState(
            pr_state="open",
            merged=merged,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=0,
        )

    def test_not_merged(self):
        assert _detect_github_merged(self._state(merged=False), None) is False

    def test_newly_merged(self):
        new = self._state(merged=True)
        last = self._state(merged=False)
        assert _detect_github_merged(new, last) is True

    def test_already_merged_no_change(self):
        state = self._state(merged=True)
        assert _detect_github_merged(state, state) is False


class TestDetectGithubNewComments:
    def _state(self, comment_count=0):
        return GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=comment_count,
        )

    def test_no_change_same_count(self):
        state = self._state(comment_count=3)
        assert _detect_github_new_comments(state, state) is False

    def test_new_comment_detected(self):
        new = self._state(comment_count=4)
        last = self._state(comment_count=3)
        assert _detect_github_new_comments(new, last) is True

    def test_no_last_state_with_zero_comments_no_fire(self):
        """First poll with no comments should not fire."""
        new = self._state(comment_count=0)
        assert _detect_github_new_comments(new, None) is False

    def test_no_last_state_with_existing_comments_no_fire(self):
        """First poll with pre-existing comments should not fire — no baseline to diff against."""
        new = self._state(comment_count=5)
        assert _detect_github_new_comments(new, None) is False

    def test_count_decreased_no_fire(self):
        """Comment deleted — count went down; should not fire."""
        new = self._state(comment_count=2)
        last = self._state(comment_count=3)
        assert _detect_github_new_comments(new, last) is False


class TestDetectJiraNewResults:
    def test_no_new_issues(self):
        state: JiraQueryState = {
            "total": 1,
            "issues": [{"key": "A-1", "summary": "x", "status": "Open"}],
        }
        assert _detect_jira_new_results(state, state) is False

    def test_new_issue_detected(self):
        old: JiraQueryState = {
            "total": 1,
            "issues": [{"key": "A-1", "summary": "x", "status": "Open"}],
        }
        new: JiraQueryState = {
            "total": 2,
            "issues": [
                {"key": "A-1", "summary": "x", "status": "Open"},
                {"key": "A-2", "summary": "y", "status": "Open"},
            ],
        }
        assert _detect_jira_new_results(new, old) is True

    def test_none_last_with_issues_triggers(self):
        new: JiraQueryState = {
            "total": 1,
            "issues": [{"key": "A-1", "summary": "x", "status": "Open"}],
        }
        assert _detect_jira_new_results(new, None) is True


class TestDetectJiraCountChange:
    def test_same_count_no_change(self):
        state: JiraQueryState = {"total": 5, "issues": []}
        assert _detect_jira_count_change(state, state) is False

    def test_count_increased(self):
        old: JiraQueryState = {"total": 3, "issues": []}
        new: JiraQueryState = {"total": 5, "issues": []}
        assert _detect_jira_count_change(new, old) is True

    def test_none_last_with_nonzero_count(self):
        new: JiraQueryState = {"total": 2, "issues": []}
        assert _detect_jira_count_change(new, None) is True

    def test_none_last_with_zero_count(self):
        new: JiraQueryState = {"total": 0, "issues": []}
        assert _detect_jira_count_change(new, None) is False


class TestDetectJiraStatusChanged:
    def test_same_status(self):
        state: JiraTicketState = {"key": "A-1", "summary": "x", "status": "Open", "assignee": "u"}
        assert _detect_jira_status_changed(state, state) is False

    def test_status_changed(self):
        old: JiraTicketState = {"key": "A-1", "summary": "x", "status": "Open", "assignee": "u"}
        new: JiraTicketState = {
            "key": "A-1",
            "summary": "x",
            "status": "In Review",
            "assignee": "u",
        }
        assert _detect_jira_status_changed(new, old) is True

    def test_none_last_with_status(self):
        new: JiraTicketState = {
            "key": "A-1",
            "summary": "x",
            "status": "Open",
            "assignee": "u",
        }
        assert _detect_jira_status_changed(new, None) is True


class TestDetectCiChecks:
    def _state(self, *, all_complete=True, failed=None, passed=None, pending=None):
        return CiChecksState(
            all_complete=all_complete,
            passed=passed or [],
            failed=failed or [],
            pending=pending or [],
        )

    def test_checks_failed_when_complete_with_failures(self):
        state = self._state(all_complete=True, failed=["test"])
        assert _detect_ci_checks_failed(state, None) is True

    def test_checks_not_failed_when_pending(self):
        state = self._state(all_complete=False, failed=["test"])
        assert _detect_ci_checks_failed(state, None) is False

    def test_checks_not_failed_when_no_failures(self):
        state = self._state(all_complete=True, failed=[])
        assert _detect_ci_checks_failed(state, None) is False

    def test_checks_complete_when_all_done(self):
        state = self._state(all_complete=True)
        assert _detect_ci_checks_complete(state, None) is True

    def test_checks_incomplete(self):
        state = self._state(all_complete=False)
        assert _detect_ci_checks_complete(state, None) is False


# ── poll_watch ───────────────────────────────────────────────────────────────


class TestPollWatch:
    def _item(self, provider="github-pr", condition="approved_or_merged", last_state=None):
        item: SchedulerItem = {
            "id": "01JTEST00000000000000000001",
            "type": "watch",
            "status": "active",
            "message": "Test watch",
            "provider": provider,
            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
            "condition": condition,
            "last_state": last_state,
            "created_at": "2026-01-01T00:00:00",
        }
        return item

    def test_unknown_provider_returns_none_false(self):
        item = self._item(provider="unknown-provider")
        state, changed = poll_watch(item)
        assert state is None
        assert changed is False

    def test_missing_watch_config_returns_none_false(self):
        item = self._item()
        del item["watch_config"]
        state, changed = poll_watch(item)
        assert state is None
        assert changed is False

    def test_provider_returns_none_no_change(self):
        item = self._item()
        with patch.dict("aya.scheduler.providers.WATCH_PROVIDERS", {"github-pr": lambda cfg: None}):
            state, changed = poll_watch(item)
        assert state is None
        assert changed is False

    def test_no_change_detected(self):
        pr_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=0,
        )
        item = self._item(condition="approved_or_merged", last_state=pr_state)
        with patch.dict(
            "aya.scheduler.providers.WATCH_PROVIDERS", {"github-pr": lambda cfg: pr_state}
        ):
            state, changed = poll_watch(item)
        assert state is not None
        assert changed is False

    def test_change_detected(self):
        old_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=0,
        )
        new_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[{"user": "alice", "state": "APPROVED"}],
            has_approval=True,
            comment_count=0,
        )
        item = self._item(condition="approved_or_merged", last_state=old_state)
        with patch.dict(
            "aya.scheduler.providers.WATCH_PROVIDERS", {"github-pr": lambda cfg: new_state}
        ):
            state, changed = poll_watch(item)
        assert state is not None
        assert changed is True


class TestDetectWatchChange:
    def test_uses_item_condition_and_last_state(self):
        old_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=0,
        )
        new_state = GithubPrState(
            pr_state="open",
            merged=False,
            draft=False,
            title="PR",
            reviews=[{"user": "alice", "state": "APPROVED"}],
            has_approval=True,
            comment_count=0,
        )
        item: SchedulerItem = {
            "id": "01JTEST00000000000000000001",
            "type": "watch",
            "status": "active",
            "message": "Test watch",
            "provider": "github-pr",
            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
            "condition": "approved_or_merged",
            "last_state": old_state,
            "created_at": "2026-01-01T00:00:00",
        }
        assert detect_watch_change(item, new_state) is True

    def test_invalid_state_returns_false(self):
        item: SchedulerItem = {
            "id": "01JTEST00000000000000000001",
            "type": "watch",
            "status": "active",
            "message": "Test watch",
            "provider": "github-pr",
            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
            "condition": "approved_or_merged",
            "last_state": None,
            "created_at": "2026-01-01T00:00:00",
        }
        assert detect_watch_change(item, {}) is False


# ── _evaluate_auto_remove ────────────────────────────────────────────────────


class TestEvaluateAutoRemove:
    def _pr_state(self, *, merged=False, pr_state="open"):
        return GithubPrState(
            pr_state=pr_state,
            merged=merged,
            draft=False,
            title="PR",
            reviews=[],
            has_approval=False,
            comment_count=0,
        )

    def _item(self, provider="github-pr", remove_when=""):
        item: SchedulerItem = {
            "id": "01JTEST00000000000000000001",
            "type": "watch",
            "status": "active",
            "message": "Test watch",
            "provider": provider,
            "watch_config": {"owner": "acme", "repo": "widget", "pr": 42},
            "condition": "",
            "created_at": "2026-01-01T00:00:00",
        }
        if remove_when:
            item["remove_when"] = remove_when
        return item

    def test_no_remove_when_returns_false(self):
        item = self._item(remove_when="")
        assert _evaluate_auto_remove(item, self._pr_state()) is False

    def test_merged_pr_triggers_removal(self):
        item = self._item(provider="github-pr", remove_when="merged_or_closed")
        assert _evaluate_auto_remove(item, self._pr_state(merged=True)) is True

    def test_closed_pr_triggers_removal(self):
        item = self._item(provider="github-pr", remove_when="merged_or_closed")
        assert _evaluate_auto_remove(item, self._pr_state(pr_state="closed")) is True

    def test_open_pr_no_removal(self):
        item = self._item(provider="github-pr", remove_when="merged_or_closed")
        assert _evaluate_auto_remove(item, self._pr_state(pr_state="open")) is False

    def test_ci_checks_complete_triggers_removal(self):
        item = self._item(provider="ci-checks", remove_when="checks_complete")
        ci_state = CiChecksState(all_complete=True, passed=["lint"], failed=[], pending=[])
        assert _evaluate_auto_remove(item, ci_state) is True

    def test_ci_checks_incomplete_no_removal(self):
        item = self._item(provider="ci-checks", remove_when="checks_complete")
        ci_state = CiChecksState(all_complete=False, passed=[], failed=[], pending=["test"])
        assert _evaluate_auto_remove(item, ci_state) is False

    def test_unknown_remove_when_returns_false(self):
        item = self._item(provider="github-pr", remove_when="some_unknown_condition")
        assert _evaluate_auto_remove(item, self._pr_state()) is False


# ── watch failures must be visible ───────────────────────────────────────────


class TestWatchFailureIsReported:
    """A failed check returns None, which the caller cannot tell apart from
    "nothing changed". These logged at debug, so a watch that had silently
    stopped working looked identical to a quiet one.
    """

    def test_jira_query_failure_logs_at_warning(self, caplog: pytest.LogCaptureFixture):
        with (
            patch(
                "aya.scheduler.providers._get_jira_credentials",
                return_value=("a@b.c", "tok", "https://x"),
            ),
            patch("httpx.post", side_effect=OSError("boom")),
            caplog.at_level(logging.WARNING),
        ):
            assert _check_jira_query({"jql": "project = TEST"}) is None

        assert "Jira query watch failed" in caplog.text
        assert "project = TEST" in caplog.text

    def test_jira_ticket_failure_logs_at_warning(self, caplog: pytest.LogCaptureFixture):
        with (
            patch(
                "aya.scheduler.providers._get_jira_credentials",
                return_value=("a@b.c", "tok", "https://x"),
            ),
            patch("httpx.get", side_effect=OSError("boom")),
            caplog.at_level(logging.WARNING),
        ):
            assert _check_jira_ticket({"ticket": "TEST-1"}) is None

        assert "Jira ticket watch failed" in caplog.text
        assert "TEST-1" in caplog.text


# ── poll bookkeeping ─────────────────────────────────────────────────────────


class TestRecordPollAttempt:
    def test_failure_stamps_and_increments(self):
        from aya.scheduler.providers import record_poll_attempt

        item = {"id": "w1"}
        assert record_poll_attempt(item, "2026-04-01T10:00:00-07:00", None) == 1
        assert item["last_checked_at"] == "2026-04-01T10:00:00-07:00"
        assert record_poll_attempt(item, "2026-04-01T10:01:00-07:00", None) == 2
        assert item["consecutive_failures"] == 2

    def test_success_stamps_and_resets(self):
        from aya.scheduler.providers import record_poll_attempt

        item = {"id": "w1", "consecutive_failures": 9}
        state = {"all_complete": True, "passed": [], "failed": [], "pending": []}
        assert record_poll_attempt(item, "2026-04-01T10:02:00-07:00", state) == 0
        assert item["consecutive_failures"] == 0
        assert item["last_checked_at"] == "2026-04-01T10:02:00-07:00"


class TestShouldWarnForFailures:
    def test_warns_on_early_milestones(self):
        from aya.scheduler.providers import should_warn_for_failures

        assert should_warn_for_failures(1)
        assert should_warn_for_failures(3)
        assert should_warn_for_failures(10)

    def test_quiet_between_milestones(self):
        from aya.scheduler.providers import should_warn_for_failures

        assert not should_warn_for_failures(2)
        assert not should_warn_for_failures(4)
        assert not should_warn_for_failures(99)

    def test_never_goes_permanently_silent(self):
        from aya.scheduler.providers import should_warn_for_failures

        # Past the last milestone the warning must keep recurring, or a watch
        # broken for a week stops reporting itself entirely.
        assert should_warn_for_failures(1000)
        assert should_warn_for_failures(5000)
        assert not should_warn_for_failures(5001)
