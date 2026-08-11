"""End-to-end MCP tests over the real stdio transport.

``test_mcp_server.py`` calls ``call_tool()`` directly, which is deliberate —
dispatch should be testable without a transport. What it cannot cover is the
transport itself, and the distinction is sharper than "unit vs integration":

* A change that stops the module *importing* — mcp 2.0 removing
  ``@server.list_tools()`` — already fails ``test_mcp_server.py`` at collection,
  because the decorator ran at import. Those tests do catch that.
* A change that imports cleanly but wires the server up wrongly — a handler
  registered under the wrong name, or not registered at all — is invisible to
  them, because none of them construct a ``Server``. Measured: dropping
  ``on_call_tool`` from the constructor leaves all 28 of them passing and fails
  four tests here.
* So does a change to how tool schemas *serialize*, which is what clients
  actually consume.

These tests spawn the server as a subprocess and drive it with the real ``mcp``
client, which is the only way to cover those last two.

Each test is bounded with ``anyio.fail_after``. The client runs on anyio cancel
scopes, and an ``asyncio.timeout`` wrapped around it does not bound them: with
that arrangement the wiring bug above wedged on session teardown and ran past
ten minutes instead of failing. A hang here has to fail the run, not stall CI.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_TIMEOUT_SECONDS = 60

# Run the server from this interpreter so it uses the same virtualenv as the
# tests; `uv run` would re-resolve the environment on every case.
_LAUNCH = "import asyncio; from aya.adapters.mcp_server import main; asyncio.run(main())"


def _server_params(aya_home: Path) -> StdioServerParameters:
    """Launch parameters pointing the child at the per-test AYA_HOME.

    The autouse ``isolate_aya_home`` fixture sets AYA_HOME in *this* process; a
    subprocess gets its own environment, so it has to be passed through
    explicitly or the child would read the developer's real ``~/.aya``.
    """
    env = {
        **os.environ,
        "AYA_HOME": str(aya_home),
        # Keep the child's stdout pure JSON-RPC — a Rich-styled log line on
        # stdout would corrupt the stream, not merely look untidy.
        "NO_COLOR": "1",
    }
    return StdioServerParameters(command=sys.executable, args=["-c", _LAUNCH], env=env)


@asynccontextmanager
async def mcp_client(aya_home: Path) -> AsyncIterator[ClientSession]:
    """An initialized client session against a freshly spawned server.

    A context manager rather than a fixture on purpose: pytest-asyncio runs
    fixture setup and teardown in *different* tasks, and anyio refuses to exit a
    cancel scope in a task other than the one that entered it ("Attempted to
    exit cancel scope in a different task"). Keeping the whole session inside
    the test's own task avoids that, and lets one bound cover startup, the
    handshake, the body and teardown.
    """
    with anyio.fail_after(_TIMEOUT_SECONDS):
        async with (
            stdio_client(_server_params(aya_home)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session


def _payload(result: Any) -> Any:
    """Every aya tool answers with one JSON TextContent block."""
    assert result.content, "tool returned no content"
    block = result.content[0]
    assert block.type == "text", f"expected a text block, got {block.type}"
    return json.loads(block.text)


async def test_server_completes_the_initialize_handshake(isolate_aya_home: Path):
    """Proves the constructor-registered handlers produce a usable server."""
    async with mcp_client(isolate_aya_home) as session:
        info = session.server_info
        assert info is not None
        assert info.name == "aya"


async def test_tools_list_over_the_wire_matches_the_catalogue(isolate_aya_home: Path):
    """Guards the seam between ``_TOOLS`` and what the transport advertises."""
    from aya.adapters.mcp_server import _TOOLS

    async with mcp_client(isolate_aya_home) as session:
        result = await session.list_tools()

        assert {t.name for t in result.tools} == {t.name for t in _TOOLS}
        for tool in result.tools:
            assert tool.input_schema.get("type") == "object", tool.name


async def test_tool_schemas_serialize_as_input_schema_alias(isolate_aya_home: Path):
    """The wire name must stay ``inputSchema`` even though the field is ``input_schema``.

    mcp 2.0 renamed the attribute and kept the old spelling as a serialization
    alias, so renaming our source was invisible to the unit tests *and* to the
    client object. Only the serialized form distinguishes a rename from a
    breaking protocol change.
    """
    async with mcp_client(isolate_aya_home) as session:
        result = await session.list_tools()

        assert result.tools, "no tools advertised"
        for tool in result.tools:
            wire = tool.model_dump(by_alias=True)
            assert "inputSchema" in wire, f"{tool.name} lost the inputSchema wire name"
            assert "input_schema" not in wire, f"{tool.name} leaked the python field name"


async def test_call_tool_returns_a_real_payload(isolate_aya_home: Path):
    """A full round trip: request framing, dispatch, and response framing."""
    async with mcp_client(isolate_aya_home) as session:
        payload = _payload(await session.call_tool("aya_status", {}))

    assert "systems" in payload

    checks = {c["name"]: c for c in payload["systems"]["checks"]}
    # An un-initialized AYA_HOME has no profile.json, so that check *should*
    # fail — asserting systems.ok here would be asserting the wrong thing.
    assert checks["profile"]["ok"] is False

    # The scheduler check is the one that must pass: scheduler.json is written
    # by the first `aya schedule` command, and its absence used to fail the gate
    # that skills/aya/SKILL.md reads as "the installation failed".
    assert checks["scheduler"]["ok"] is True, checks["scheduler"]
    assert "not created yet" in checks["scheduler"]["detail"]

    # Pin the set, so a future check that regresses is caught here.
    failing = {name for name, c in checks.items() if not c["ok"]}
    assert failing == {"profile"}, failing


async def test_unknown_tool_is_an_error_payload_not_a_transport_failure(
    isolate_aya_home: Path,
):
    """Dispatch answers unknown names in-band, so the session stays usable."""
    async with mcp_client(isolate_aya_home) as session:
        result = await session.call_tool("aya_does_not_exist", {})
        assert "Unknown tool" in _payload(result)["error"]

        # The same session still serves a valid call — a bad name must not
        # poison the connection.
        ok = await session.call_tool("aya_status", {})
        assert "systems" in _payload(ok)


@pytest.mark.parametrize("tool_name", ["aya_inbox", "aya_receive"])
async def test_relay_tools_answer_rather_than_crashing(isolate_aya_home: Path, tool_name: str):
    """With no profile and no relay, these must answer, not raise.

    The loud-failure contract asserted through the transport: an empty result
    has to arrive as a payload the caller can read, never a bare crash.
    """
    async with mcp_client(isolate_aya_home) as session:
        payload = _payload(await session.call_tool(tool_name, {}))

    assert isinstance(payload, dict)
    # Either a structured empty poll or a named error — never a silent [].
    assert "packets" in payload or "error" in payload, payload
