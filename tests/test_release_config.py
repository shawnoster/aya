"""Tests for the release configuration in pyproject.toml.

These assert the shape of `[tool.semantic_release]` rather than any runtime
behaviour. They exist because the release job is the one code path that cannot be
exercised by the test suite or by CI — it runs once, on main, in a Docker image
with a different Python than anything else here, and a mistake there is only
visible as a failed or silently-incomplete release.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def config() -> dict:
    # Binary mode: tomllib decodes UTF-8 itself, so this does not depend on the
    # locale the tests happen to run under.
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


class TestBuildCommand:
    def test_it_does_not_install_the_project(self, config):
        """Installing aya itself breaks the release.

        semantic-release's action runs in a Docker image on Python 3.14, and aya
        depends on coincurve, whose cffi build fails there — the same constraint
        already pinned in [project] dependencies. build_command needs `uv` and
        nothing else, so it must never name the local project as a pip target.
        """
        command = config["tool"]["semantic_release"]["build_command"]
        project_targets = re.findall(
            r"pip install[^\n]*?(?:-e\s+|\s)'?\.(?:\[[^\]]*\])?'?", command
        )
        assert not project_targets, (
            "build_command installs the local project, which fails on the action's "
            f"Python 3.14 (coincurve/cffi): {project_targets}"
        )

    def test_the_pin_lookup_survives_a_locale_without_utf8(self, config):
        """Run the snippet the release actually runs, under an ASCII locale.

        `pyproject.toml` is UTF-8 by specification and this one contains 48
        non-ASCII bytes (the em dash in `project.description`, for one). A text-mode
        read uses the locale encoding, so in a minimal image with no LANG the
        release dies on `UnicodeDecodeError` before it installs anything — a
        failure that cannot reproduce on a developer machine.
        """
        command = config["tool"]["semantic_release"]["build_command"]
        snippet = re.search(r"""\$\(python -c '(.+?)'\)""", command)
        assert snippet, f"could not find the pin-lookup snippet in: {command}"

        result = subprocess.run(
            ["python", "-c", snippet.group(1)],
            cwd=PYPROJECT.parent,
            capture_output=True,
            text=True,
            env={
                "PATH": os.environ["PATH"],
                "LC_ALL": "C",
                "PYTHONCOERCECLOCALE": "0",
                "PYTHONUTF8": "0",
            },
            check=False,
        )
        assert result.returncode == 0, (
            f"the pin lookup fails without a UTF-8 locale: {result.stderr.strip()}"
        )
        assert result.stdout.strip() == config["project"]["optional-dependencies"]["build"][0]

    def test_it_relocks_and_stages_the_lockfile(self, config):
        """The reason build_command exists at all."""
        command = config["tool"]["semantic_release"]["build_command"]
        assert "uv lock --upgrade-package" in command, (
            "a bare `uv lock` could pull in untested dependency versions"
        )
        assert "git add uv.lock" in command, (
            "without staging, the re-lock is discarded and the release commit still drifts"
        )

    def test_it_fails_fast(self, config):
        """A multi-line command exits with its last statement's status.

        Without `set -e` a failed re-lock is masked by whatever runs after it, and
        the release completes with a stale lock — the failure this whole hook was
        added to prevent.
        """
        command = config["tool"]["semantic_release"]["build_command"]
        assert command.strip().startswith("set -e"), "build_command must lead with set -e"

    def test_the_uv_pin_is_the_first_build_extra(self, config):
        """build_command reads `optional-dependencies.build[0]`.

        Reading index 0 keeps the pin in one place, but it also means inserting
        another entry ahead of uv would silently install the wrong package.
        """
        build_extra = config["project"]["optional-dependencies"]["build"]
        assert build_extra, "the build extra is empty; build_command has nothing to install"
        assert build_extra[0].startswith("uv"), (
            f"build_command installs build[0]; it must be the uv pin, got {build_extra[0]!r}"
        )
