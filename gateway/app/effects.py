"""Effect routes — POST /effects/<name>.

Each route shells out to a stdlib-only Python helper bundled at
/usr/local/bin/ in the container (see Dockerfile). The helpers send
one HTTP PUT to the Nanoleaf controller and exit immediately; the
animation loop runs on the panels themselves until something else
changes their state.

Concurrency: a module-level lock serialises requests so that a
previous helper subprocess is terminated before a new one is spawned.
In practice the helpers exit in tens of milliseconds, but the guard
makes the contract well-defined under bursty input.
"""

import shutil
import subprocess
import threading
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.auth import _require_bearer

router = APIRouter(
    prefix="/effects",
    tags=["effects"],
    dependencies=[Depends(_require_bearer)],
)

_KITT_BINARY = shutil.which("nanoleaf-kitt") or "/usr/local/bin/nanoleaf-kitt"

_kitt_lock = threading.Lock()
_kitt_proc: subprocess.Popen[bytes] | None = None


class KittArgs(BaseModel):
    """Optional knobs for the KITT scanner; defaults match `nanoleaf-kitt`'s CLI."""

    color: str = "red"
    period: float = Field(default=1.8, gt=0, description="Cycle time in seconds; must be positive.")
    trail: int = Field(default=4, ge=1, description="Trail length in panels; must be >= 1.")


@router.post("/kitt", status_code=status.HTTP_202_ACCEPTED)
def kitt(args: KittArgs | None = None) -> dict[str, Any]:
    """Spawn `nanoleaf-kitt` as a fire-and-forget subprocess.

    Body is fully optional — every field has a default, and a missing
    body is equivalent to `{}`. Kills any previous still-running
    `nanoleaf-kitt` subprocess first to keep the panels under
    single-writer control.
    """
    global _kitt_proc

    if args is None:
        args = KittArgs()

    cmd = [
        _KITT_BINARY,
        "--color",
        args.color,
        "--period",
        str(args.period),
        "--trail",
        str(args.trail),
    ]

    with _kitt_lock:
        if _kitt_proc is not None and _kitt_proc.poll() is None:
            _kitt_proc.terminate()
            try:
                _kitt_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _kitt_proc.kill()
                _kitt_proc.wait(timeout=2)

        _kitt_proc = subprocess.Popen(  # noqa: S603 — fixed binary path, validated args
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return {"started": True, "args": args.model_dump()}
