"""Executable architecture boundaries.

The layout states the layering; these tests keep it true. Both were violated
silently for a long time — `mcp_server` imported five private names from `cli`,
so a fix applied to one surface routinely missed the other.

Layers, innermost first:

    entities   → (nothing)
    usecases   → entities
    adapters   → usecases, entities
    scheduler  → a bounded subsystem, layered internally
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "aya"

PRESENTATION_PACKAGES = {"typer", "rich", "mcp", "click"}


def _modules(layer: str) -> list[Path]:
    return sorted(p for p in (SRC / layer).glob("*.py") if p.name != "__init__.py")


def _imports(path: Path) -> set[str]:
    """Top-level package name of every import in *path*."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
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


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


ENTITIES = _modules("entities")
USECASES = _modules("usecases")
ADAPTERS = _modules("adapters")


@pytest.mark.parametrize("module", ENTITIES, ids=_ids(ENTITIES))
def test_entities_depend_on_nothing_inward(module: Path):
    """The innermost layer imports no other layer.

    Held for every entity now that reading and writing profile.json lives in
    adapters.profile_store rather than on Profile itself.
    """
    outward = {
        i
        for i in _aya_imports(module)
        if i.startswith(("aya.usecases", "aya.adapters", "aya.scheduler"))
    }
    assert not outward, f"{module.name} reaches outward: {sorted(outward)}"


@pytest.mark.parametrize("module", ENTITIES + USECASES, ids=_ids(ENTITIES + USECASES))
def test_inner_layers_are_presentation_free(module: Path):
    """No typer/rich/mcp below adapters.

    A use case that can print or raise typer.Exit cannot be reused by the
    other surface, which is how the duplication started.
    """
    leaked = _imports(module) & PRESENTATION_PACKAGES
    assert not leaked, f"{module.name} imports presentation packages: {sorted(leaked)}"


@pytest.mark.parametrize("module", USECASES, ids=_ids(USECASES))
def test_usecases_do_not_import_a_driving_adapter(module: Path):
    """A use case must never depend on the CLI or the MCP server."""
    forbidden = {"aya.adapters.cli", "aya.adapters.mcp_server"} & _aya_imports(module)
    assert not forbidden, f"{module.name} imports a surface: {sorted(forbidden)}"


def test_the_two_surfaces_do_not_import_each_other():
    """cli -> mcp_server is allowed one way only: `aya mcp-server` starts it.

    The reverse makes every CLI-side fix a coin flip on whether MCP gets it.
    """
    assert "aya.adapters.cli" not in _aya_imports(SRC / "adapters" / "mcp_server.py")


def test_every_module_lives_in_a_layer():
    """No module may sit loose at the package root."""
    stray = [p.name for p in SRC.glob("*.py") if p.name != "__init__.py"]
    assert not stray, f"unlayered modules: {stray}"
