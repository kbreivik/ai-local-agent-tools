"""v2.36.2 — confirmation gate tests. No DB, no network."""
import asyncio
import pytest

from api.agents.external_ai_confirmation import (
    wait_for_confirmation, resolve_confirmation, has_pending,
    _pending,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    """Ensure no state leaks between tests."""
    _pending.clear()
    yield
    _pending.clear()


@pytest.mark.asyncio
async def test_wait_returns_approved_when_resolved():
    async def resolver():
        await asyncio.sleep(0.05)
        assert resolve_confirmation("sess-A", approved=True) is True

    asyncio.create_task(resolver())
    result = await wait_for_confirmation("sess-A", timeout_s=2)
    assert result == "approved"


@pytest.mark.asyncio
async def test_wait_returns_rejected_when_resolved_false():
    async def resolver():
        await asyncio.sleep(0.05)
        resolve_confirmation("sess-B", approved=False)

    asyncio.create_task(resolver())
    result = await wait_for_confirmation("sess-B", timeout_s=2)
    assert result == "rejected"


@pytest.mark.asyncio
async def test_wait_returns_timeout_when_no_resolver():
    result = await wait_for_confirmation("sess-C", timeout_s=1)
    assert result == "timeout"


@pytest.mark.asyncio
async def test_resolve_unknown_session_returns_false():
    """Stale /confirm-external calls shouldn't crash the endpoint."""
    assert resolve_confirmation("never-waited", approved=True) is False


@pytest.mark.asyncio
async def test_has_pending_reflects_state():
    assert has_pending("sess-D") is False
    # Start a wait in the background
    async def waiter():
        await wait_for_confirmation("sess-D", timeout_s=2)
    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.02)  # let the waiter register
    assert has_pending("sess-D") is True
    resolve_confirmation("sess-D", approved=True)
    await task
    # After resolve, decision is no longer 'pending'
    assert has_pending("sess-D") is False
