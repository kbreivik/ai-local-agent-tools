"""Shared pytest fixtures."""
import pytest
import api.routers.auth as _auth_module


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Rewrite prompt snapshot files from the current code",
    )


@pytest.fixture
def update_snapshots(request):
    return request.config.getoption("--update-snapshots")


@pytest.fixture(autouse=True)
def clear_login_rate_limiter():
    """Reset per-IP login attempt counters before each test.

    Prevents the rate limiter from firing during tests due to accumulated
    login calls across test files within a single 60-second window.
    """
    _auth_module._login_attempts.clear()
    yield
