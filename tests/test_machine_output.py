"""`--format json` must be parseable, whatever the terminal is doing.

`_output_json` and `_emit_error` used to write through the Rich console, which
highlights JSON-looking text. In any environment that forces colour — much of
CI — that emitted ANSI escapes into stdout and no parser could read the
result. These assert the bytes, with colour forced on.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run(args: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess with colour forced on."""
    env = {
        **{k: v for k, v in __import__("os").environ.items() if k != "NO_COLOR"},
        "AYA_HOME": str(home),
        "FORCE_COLOR": "1",
        "CLICOLOR_FORCE": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", "from aya.adapters.cli import app; app()", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.fixture
def initialised_home(tmp_path: Path) -> Path:
    from aya.adapters.profile_store import save_profile
    from aya.entities.identity import Identity, Profile

    home = tmp_path / "aya_home"
    home.mkdir(exist_ok=True)
    p = Profile()
    p.instances["harbor"] = Identity.generate("harbor")
    (home / "profile.json").write_text("{}")
    save_profile(p, home / "profile.json")
    return home


class TestJsonIsNotRendered:
    def test_success_output_parses(self, initialised_home: Path):
        r = _run(["whoami", "--format", "json"], initialised_home)
        assert r.returncode == 0, r.stderr
        assert "\x1b[" not in r.stdout, "ANSI escapes in machine output"
        assert json.loads(r.stdout)["active_instance"] == "harbor"

    def test_error_output_parses(self, initialised_home: Path):
        r = _run(["read", "--format", "json", "01ZZZZZZZZZZZZZZZZZZZZZZZZ"], initialised_home)
        assert r.returncode != 0
        stream = r.stderr or r.stdout
        assert "\x1b[" not in stream, "ANSI escapes in machine error output"
        assert json.loads(stream)["error"]["code"] == "PACKET_NOT_FOUND"
