"""Executable architecture boundaries.

These rules were violated silently for a long time — `mcp_server` imported
five private names from `cli`, so the two presentation layers depended on each
other and a fix applied to one surface routinely missed the other. Encoding
the boundary as a test makes the regression loud instead of invisible.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "aya"

# Layers that must stay free of presentation concerns. Anything here may be
# imported by any surface; none of it may import a surface or a renderer.
SERVICE_MODULES = ("resolve.py", "outbox.py", "ingest.py", "identity.py", "packet.py")

PRESENTATION_PACKAGES = {"typer", "rich", "mcp", "click"}


def _imports(path: Path) -> set[str]:
    """Top-level package name of every import in *path*, including local ones."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def _aya_imports(path: Path) -> set[str]:
    """Fully-qualified aya modules imported by *path*."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("aya"):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("aya"))
    return found


def test_mcp_server_does_not_import_cli():
    """The two surfaces must not depend on each other.

    cli -> mcp_server is allowed in one direction only: `aya mcp-server`
    launches the server. The reverse makes every CLI-side fix a coin flip on
    whether the MCP surface gets it too.
    """
    assert "aya.cli" not in _aya_imports(SRC / "mcp_server.py")


@pytest.mark.parametrize("module", SERVICE_MODULES)
def test_service_modules_are_presentation_free(module: str):
    """No typer/rich/mcp below the surface layer.

    A service that can print or raise typer.Exit cannot be reused by the other
    surface, which is how the duplication started.
    """
    leaked = _imports(SRC / module) & PRESENTATION_PACKAGES
    assert not leaked, f"{module} imports presentation packages: {sorted(leaked)}"


@pytest.mark.parametrize("module", SERVICE_MODULES)
def test_service_modules_do_not_import_surfaces(module: str):
    imported = _aya_imports(SRC / module)
    forbidden = {"aya.cli", "aya.mcp_server"} & imported
    assert not forbidden, f"{module} imports a surface: {sorted(forbidden)}"
