"""Shared pytest fixtures."""
import pytest
import api.routers.auth as _auth_module


@pytest.fixture(autouse=True)
def clear_login_rate_limiter():
    """Reset per-IP login attempt counters before each test.

    Prevents the rate limiter from firing during tests due to accumulated
    login calls across test files within a single 60-second window.
    """
    _auth_module._login_attempts.clear()
    yield
