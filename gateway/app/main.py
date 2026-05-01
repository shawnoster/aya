"""aya-gateway HTTP service."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import _bearer_token, _require_bearer
from app.effects import router as effects_router


def _version() -> str:
    """Resolve the build version from the env at call time.

    Reading per-call (rather than caching at import) keeps the contract
    testable via monkeypatch without importlib reloads. In production
    GIT_SHA is set once at container start and doesn't change, so the
    cost is a single env lookup per /health request — negligible.
    """
    return os.getenv("GIT_SHA", "dev")


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Fail fast at startup if GATEWAY_BEARER is absent."""
    if not _bearer_token():
        raise RuntimeError("GATEWAY_BEARER is not set — refusing to start without a bearer token")
    yield


app = FastAPI(
    title="aya-gateway",
    version=_version(),
    lifespan=_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def _validation_400(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 400 (not the FastAPI default 422) on body validation failures.

    The gateway's clients (Home Assistant `rest_command`, iOS Shortcuts) are
    HTTP-1 callers that read status codes literally; 400 communicates
    "client sent something invalid" more universally than 422.
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.errors()},
    )


# Router for all authenticated endpoints. Add future routes here.
authenticated = APIRouter(dependencies=[Depends(_require_bearer)])
authenticated.include_router(effects_router)
app.include_router(authenticated)


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "version": _version()}
