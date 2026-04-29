"""Pytest configuration for gateway tests.

Sets GATEWAY_BEARER before any test module is imported so the lifespan
startup check never fails during the test run.
"""

import os


def pytest_configure(config: object) -> None:  # noqa: ARG001
    """Seed GATEWAY_BEARER so the lifespan check passes in all tests."""
    os.environ.setdefault("GATEWAY_BEARER", "test-token-for-ci")
