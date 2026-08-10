"""The Typer application, assembled from one module per command group.

cli.py had grown to 2,877 lines holding every command and its helpers. The
kernel owns the app object, the sub-apps and the shared plumbing; each
command module registers its commands when imported.
"""

from __future__ import annotations

from aya.adapters.cli import (  # noqa: F401  — imported to register commands
    config_cmds,
    hook_cmds,
    identity_cmds,
    packet_cmds,
    pair_cmds,
    poll_cmds,
    schedule_cmds,
    send_cmds,
    workspace_cmds,
)
from aya.adapters.cli._kernel import app

__all__ = ["app"]
