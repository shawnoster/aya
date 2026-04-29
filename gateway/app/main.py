"""aya-gateway HTTP service.

Phase 0 bootstrap: liveness only. Auth, business routes, and deploy
plumbing land in subsequent issues — see
`notebook/projects/aya-gateway/README.md` for the full v1 plan.
"""

import os

from fastapi import FastAPI


def _version() -> str:
    """Resolve the build version from the env at call time.

    Reading per-call (rather than caching at import) keeps the contract
    testable via monkeypatch without importlib reloads. In production
    GIT_SHA is set once at container start and doesn't change, so the
    cost is a single env lookup per /health request — negligible.
    """
    return os.getenv("GIT_SHA", "dev")


app = FastAPI(title="aya-gateway", version=_version())


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "version": _version()}
