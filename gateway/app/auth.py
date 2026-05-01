"""Bearer-token authentication for aya-gateway routes.

Extracted from `app.main` so router modules (effects, future inbox,
…) can `from app.auth import _require_bearer` without importing the
FastAPI app and creating circular dependencies.
"""

import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


def _bearer_token() -> str:
    """Return GATEWAY_BEARER from the environment, stripped.

    Read per-call (not cached) so tests can override it with monkeypatch
    without reloading the module. In production the value is fixed at
    container start and never changes.
    """
    return os.getenv("GATEWAY_BEARER", "").strip()


def _require_bearer(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),  # noqa: B008
) -> None:
    """FastAPI dependency — reject requests that lack a valid bearer token."""
    expected = _bearer_token()
    if (
        credentials is None
        or not expected
        or not secrets.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
