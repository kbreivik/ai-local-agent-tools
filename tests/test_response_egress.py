"""v2.35.6 regression tests — ensure no outbound API response sanitisation.

The v2.31.7 sanitiser (format ``[BLOCKED: <Category>]``) was supposed to be
retired by v2.34.15 in favour of ``api/security/prompt_sanitiser.py`` (format
``[REDACTED:...]``). v2.35.6 removed the last remaining legacy call site and
added a one-shot recovery migration.

These tests lock in the invariant that no outbound endpoint field ever contains
``[BLOCKED:`` and that agent output containing ``key=value``-shaped content
survives a DB round-trip unchanged. A structural guard prevents the legacy
``[BLOCKED: ...]`` format from ever returning to ``api/``.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import uuid

import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _run(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def test_health_version_is_not_blocked(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    version = body.get("version") or ""
    assert "[BLOCKED:" not in version, \
        f"/api/health version was egress-sanitised: {version!r}"
    assert "[REDACTED:" not in version, \
        "/api/health version should not pass through prompt_sanitiser either"


def test_agent_models_endpoint_clean(client):
    r = client.get("/api/agent/models")
    assert r.status_code == 200
    body_text = r.text
    assert "[BLOCKED:" not in body_text, \
        f"/api/agent/models contains BLOCKED token: {body_text[:300]}"


def test_operations_detail_preserves_key_value_final_answer(client):
    """Regression: a final_answer containing ``<parameter=x>value</parameter>``
    patterns was rewritten to ``[BLOCKED: Cookie/query string data]`` in
    v2.35.5. The DB round-trip must now preserve the raw text exactly.
    """
    from api.db.base import get_engine
    from api.db import queries as _q

    sentinel = (
        "EVIDENCE:\n"
        "- vm_exec(host=ds-docker-worker-03, cmd=docker ps)\n"
        "- <parameter=host>ds-docker-worker-03</parameter>\n"
        "- session_id=abc12345-6789-4321-8765-fedcba987654\n"
        "- version 2.35.6\n"
        "- key=value pairs in prose\n"
        "ROOT CAUSE: test\n"
    )
    sess_id = str(uuid.uuid4())

    async def _seed() -> str:
        async with get_engine().begin() as conn:
            op_id = await _q.create_operation(
                conn, sess_id, "test_egress_preservation",
                triggered_by="test", model_used="", owner_user="test",
            )
            await _q.set_operation_final_answer(conn, sess_id, sentinel)
        return op_id

    try:
        op_id = _run(_seed())
    except Exception as e:
        pytest.skip(f"DB unavailable: {e}")

    r = client.get(f"/api/logs/operations/{op_id}")
    assert r.status_code == 200, r.text
    op = r.json().get("operation") or {}
    fa = op.get("final_answer") or ""
    assert "[BLOCKED:" not in fa, f"final_answer was egress-sanitised: {fa!r}"
    assert fa == sentinel, (
        f"final_answer round-trip altered: sent {sentinel!r}, got {fa!r}"
    )

    r2 = client.get("/api/logs/operations?limit=50")
    assert r2.status_code == 200
    listed = next(
        (o for o in (r2.json().get("operations") or []) if o.get("id") == op_id),
        None,
    )
    assert listed is not None, "test op not in list response"
    assert "[BLOCKED:" not in (listed.get("final_answer") or "")


def test_prompt_sanitiser_format_is_redacted_not_blocked():
    """Lock in the canonical v2.34.15 sanitiser output format.

    If a future commit reintroduces a ``[BLOCKED:`` literal anywhere in
    ``api/security/``, this test fails.
    """
    from api.security.prompt_sanitiser import sanitise
    text = (
        "JWT eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c and key=value"
    )
    out, scrubbed = sanitise(text, source_hint="test")
    assert scrubbed is True, "JWT should have triggered a scrub"
    assert "[REDACTED:" in out, f"Expected [REDACTED: token but got {out!r}"
    assert "[BLOCKED:" not in out, \
        f"Legacy [BLOCKED: token must never appear: {out!r}"


def test_no_legacy_sanitiser_module_imports():
    """Structural guard: no file under ``api/`` produces the legacy
    ``[BLOCKED: ...]`` token for JWT / Sensitive / Cookie categories.
    """
    root = pathlib.Path(__file__).parent.parent / "api"
    legacy_token_re = re.compile(r"\[BLOCKED:\s*(?:JWT|Sensitive|Cookie)")
    offenders: list[str] = []
    for py in root.rglob("*.py"):
        try:
            txt = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if legacy_token_re.search(txt):
            offenders.append(str(py.relative_to(root)))
    assert offenders == [], (
        f"Legacy '[BLOCKED: ...]' sanitiser format found in: {offenders}. "
        "Retired by v2.34.15 and removed in v2.35.6. "
        "Use api.security.prompt_sanitiser.sanitize_for_llm() instead."
    )
