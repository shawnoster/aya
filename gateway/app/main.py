"""aya-gateway HTTP service.

Phase 0 bootstrap: liveness only. Auth, business routes, and deploy
plumbing land in subsequent issues — see
`notebook/projects/aya-gateway/README.md` for the full v1 plan.
"""

import os

from fastapi import FastAPI

VERSION = os.getenv("GIT_SHA", "dev")

app = FastAPI(title="aya-gateway", version=VERSION)


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "version": VERSION}
