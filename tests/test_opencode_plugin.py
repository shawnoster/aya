"""Run the OpenCode plugin's JavaScript tests as part of the Python suite.

The plugin has no package manager or CI job of its own, so `make check` is the
only place its tests would run. `node --test` needs no dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "opencode-plugin"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_opencode_plugin_js_suite():
    result = subprocess.run(
        ["node", "--test", "aya-reminders.test.js"],
        cwd=PLUGIN_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
