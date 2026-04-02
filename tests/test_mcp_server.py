"""Tests for the MCP server module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from aya.mcp_server import _TOOLS, call_tool

# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


def test_list_tools_names():
    """All expected tools are declared."""
    names = {t.name for t in _TOOLS}
    assert names == {
        "aya_status",
        "aya_inbox",
        "aya_send",
        "aya_receive",
        "aya_schedule_remind",
        "aya_schedule_watch",
        "aya_ack",
    }


def test_list_tools_have_schemas():
    """Every tool has a non-empty inputSchema."""
    for tool in _TOOLS:
        assert tool.inputSchema, f"{tool.name} missing inputSchema"
        assert tool.inputSchema.get("type") == "object"


# ---------------------------------------------------------------------------
# aya_status
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_gather_status(monkeypatch):
    """Patch _gather_status so we don't need a real profile on disk."""
    from datetime import UTC, datetime

    fake_data = {
        "now_local": datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        "ship": "GSV Test Ship",
        "user": "Tester",
        "next_eval": "2026-04-03",
        "checks": [],
        "checks_ok": 0,
        "checks_total": 0,
        "unseen": [],
        "due": [],
        "upcoming": [],
        "active_watches": [],
    }
    monkeypatch.setattr("aya.status._gather_status", lambda: fake_data)


@pytest.mark.usefixtures("_mock_gather_status")
async def test_status_tool():
    """aya_status returns valid JSON with expected keys."""
    result = await call_tool("aya_status", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert "greeting" in payload
    assert "systems" in payload


# ---------------------------------------------------------------------------
# aya_schedule_remind
# ---------------------------------------------------------------------------


async def test_schedule_remind_tool(tmp_path, monkeypatch):
    """aya_schedule_remind creates a reminder via the scheduler."""
    sched_file = tmp_path / "scheduler.json"
    sched_file.write_text(json.dumps({"schema_version": 2, "items": []}))

    lock_file = tmp_path / ".scheduler.lock"

    monkeypatch.setattr("aya.scheduler.storage._scheduler_file", lambda: sched_file)
    monkeypatch.setattr("aya.scheduler.storage._lock_file", lambda: lock_file)

    # Reset cached lazy attrs so monkeypatch takes effect
    import aya.scheduler as sched_mod

    for attr in ("SCHEDULER_FILE", "LOCK_FILE"):
        sched_mod.__dict__.pop(attr, None)

    result = await call_tool(
        "aya_schedule_remind", {"message": "Test reminder", "due": "in 1 hour"}
    )
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["type"] == "reminder"
    assert payload["message"] == "Test reminder"
    assert payload["status"] == "pending"


# ---------------------------------------------------------------------------
# aya_send
# ---------------------------------------------------------------------------


async def test_send_tool():
    """aya_send builds a packet and publishes it via a mocked RelayClient."""
    from aya.identity import Identity, Profile, TrustedKey

    fake_identity = Identity.generate("default")
    peer_identity = Identity.generate("peer")
    fake_profile = Profile(
        alias="Test",
        ship_mind_name="GSV Test",
        user_name="Tester",
        instances={"default": fake_identity},
        trusted_keys={
            "peer": TrustedKey(
                did=peer_identity.did,
                label="peer",
                nostr_pubkey=peer_identity.nostr_public_hex,
            ),
        },
        ingested_ids=[],
        default_relays=["wss://relay.example.com"],
        last_checked={},
    )

    mock_publish = AsyncMock(return_value="abc123eventid")

    with (
        patch("aya.mcp_server._load_profile", return_value=fake_profile),
        patch("aya.relay.RelayClient.publish", mock_publish),
    ):
        result = await call_tool(
            "aya_send",
            {
                "to": "peer",
                "intent": "test-intent",
                "content": "Hello from MCP",
            },
        )

    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert "packet_id" in payload
    assert payload["event_id"] == "abc123eventid"
    mock_publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# unknown tool
# ---------------------------------------------------------------------------


async def test_unknown_tool():
    """Calling an unknown tool returns an error, not a crash."""
    result = await call_tool("nonexistent_tool", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert "error" in payload


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


async def test_tool_error_handling():
    """A tool that raises returns a graceful error response."""
    with patch("aya.mcp_server._handle_status", side_effect=RuntimeError("boom")):
        result = await call_tool("aya_status", {})

    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "boom" in payload["error"]
