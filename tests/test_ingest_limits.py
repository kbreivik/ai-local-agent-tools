"""Tests for ingest router: file-size cap, job TTL/cap, and owner isolation."""
import io
import time
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

_AUTH_CACHE: dict = {}


def auth_headers(username: str = "admin", password: str = "superduperadmin") -> dict:
    key = (username, password)
    if key not in _AUTH_CACHE:
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        if r.status_code != 200:
            pytest.skip(f"Auth not available for {username}")
        _AUTH_CACHE[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _AUTH_CACHE[key]


# ---------------------------------------------------------------------------
# P1 #8 — File-size limit
# ---------------------------------------------------------------------------

def test_pdf_upload_rejects_oversized_file():
    """Upload a >50 MB payload — must return HTTP 413."""
    big = b"A" * (50 * 1024 * 1024 + 1)  # 50 MB + 1 byte
    r = client.post(
        "/api/memory/ingest/pdf/upload",
        files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        data={"tags": ""},
        headers=auth_headers(),
    )
    assert r.status_code == 413, f"Expected 413, got {r.status_code}: {r.text}"


def test_pdf_upload_accepts_small_file():
    """A tiny, clearly-under-limit payload must not be rejected with 413."""
    tiny = b"%PDF-1.4 tiny"  # not a valid PDF — will fail parse, but NOT at size check
    r = client.post(
        "/api/memory/ingest/pdf/upload",
        files={"file": ("small.pdf", io.BytesIO(tiny), "application/pdf")},
        data={"tags": ""},
        headers=auth_headers(),
    )
    # Size check must not fire — any status other than 413 is acceptable here
    assert r.status_code != 413, f"Small file wrongly rejected with 413"


# ---------------------------------------------------------------------------
# P1 #9 — Job TTL eviction and concurrency cap
# ---------------------------------------------------------------------------

def test_pending_jobs_cap_returns_429():
    """When _pending_jobs already holds >=20 entries, preview returns 429."""
    from api.routers import ingest as ingest_mod

    # Inject 20 fake stale jobs directly into the module dict
    saved = dict(ingest_mod._pending_jobs)
    try:
        for i in range(20):
            ingest_mod._pending_jobs[str(uuid.uuid4())] = {
                "ts": time.monotonic(),
                "type": "url",
                "owner": "admin",
            }
        # Any preview attempt should now be capped
        r = client.post(
            "/api/memory/ingest/url/preview",
            json={"url": "http://example.com", "tags": []},
            headers=auth_headers(),
        )
        assert r.status_code == 429, f"Expected 429 when cap reached, got {r.status_code}: {r.text}"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)


def test_stale_jobs_are_evicted():
    """Jobs older than 600 s are removed by _evict_stale_jobs()."""
    from api.routers import ingest as ingest_mod

    stale_id = str(uuid.uuid4())
    fresh_id = str(uuid.uuid4())
    saved = dict(ingest_mod._pending_jobs)
    try:
        ingest_mod._pending_jobs[stale_id] = {
            "ts": time.monotonic() - 601,  # expired
            "type": "url",
            "owner": "admin",
        }
        ingest_mod._pending_jobs[fresh_id] = {
            "ts": time.monotonic(),  # fresh
            "type": "url",
            "owner": "admin",
        }
        ingest_mod._evict_stale_jobs()
        assert stale_id not in ingest_mod._pending_jobs, "Stale job was not evicted"
        assert fresh_id in ingest_mod._pending_jobs, "Fresh job was incorrectly evicted"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)


# ---------------------------------------------------------------------------
# P2 #26 — Owner isolation on confirm/cancel
# ---------------------------------------------------------------------------

def test_confirm_url_job_by_wrong_user_returns_403():
    """A user cannot confirm a job they did not create."""
    from api.routers import ingest as ingest_mod

    job_id = str(uuid.uuid4())
    saved = dict(ingest_mod._pending_jobs)
    try:
        ingest_mod._pending_jobs[job_id] = {
            "ts": time.monotonic(),
            "type": "url",
            "url": "http://example.com",
            "tags": [],
            "label": "example",
            "content": "hello",
            "update_info": {"is_new": True, "is_updated": False, "new_hash": "abc", "diff_snippet": None},
            "owner": "alice",  # created by alice
        }
        # admin tries to confirm alice's job
        r = client.post(
            "/api/memory/ingest/url/confirm",
            json={"job_id": job_id, "approved": True},
            headers=auth_headers(),  # admin != alice
        )
        assert r.status_code == 403, f"Expected 403 for wrong-user confirm, got {r.status_code}: {r.text}"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)


def test_confirm_pdf_job_by_wrong_user_returns_403():
    """A user cannot confirm a PDF job they did not create."""
    from api.routers import ingest as ingest_mod

    job_id = str(uuid.uuid4())
    saved = dict(ingest_mod._pending_jobs)
    try:
        ingest_mod._pending_jobs[job_id] = {
            "ts": time.monotonic(),
            "type": "pdf",
            "filename": "test.pdf",
            "local_path": "/tmp/test.pdf",
            "tags": [],
            "label": "test.pdf",
            "content": "hello",
            "update_info": {"is_new": True, "is_updated": False, "new_hash": "abc", "diff_snippet": None},
            "source_key": "test_pdf",
            "owner": "alice",  # created by alice
        }
        r = client.post(
            "/api/memory/ingest/pdf/confirm",
            json={"job_id": job_id, "approved": True},
            headers=auth_headers(),  # admin != alice
        )
        assert r.status_code == 403, f"Expected 403 for wrong-user PDF confirm, got {r.status_code}: {r.text}"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)


def test_cancel_url_job_by_wrong_user_returns_403():
    """A user cannot cancel a job they did not create (approved=False path)."""
    from api.routers import ingest as ingest_mod

    job_id = str(uuid.uuid4())
    saved = dict(ingest_mod._pending_jobs)
    try:
        ingest_mod._pending_jobs[job_id] = {
            "ts": time.monotonic(),
            "type": "url",
            "url": "http://example.com",
            "tags": [],
            "label": "example",
            "content": "hello",
            "update_info": {"is_new": True, "is_updated": False, "new_hash": "abc", "diff_snippet": None},
            "owner": "alice",
        }
        r = client.post(
            "/api/memory/ingest/url/confirm",
            json={"job_id": job_id, "approved": False},
            headers=auth_headers(),
        )
        assert r.status_code == 403, f"Expected 403 for wrong-user cancel, got {r.status_code}: {r.text}"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)


def test_owner_can_cancel_own_job():
    """The job owner can cancel their own job (approved=False returns 200 + cancelled status)."""
    from api.routers import ingest as ingest_mod

    job_id = str(uuid.uuid4())
    saved = dict(ingest_mod._pending_jobs)
    try:
        ingest_mod._pending_jobs[job_id] = {
            "ts": time.monotonic(),
            "type": "url",
            "url": "http://example.com",
            "tags": [],
            "label": "example",
            "content": "hello",
            "update_info": {"is_new": True, "is_updated": False, "new_hash": "abc", "diff_snippet": None},
            "owner": "admin",  # same as auth_headers() user
        }
        r = client.post(
            "/api/memory/ingest/url/confirm",
            json={"job_id": job_id, "approved": False},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
    finally:
        ingest_mod._pending_jobs.clear()
        ingest_mod._pending_jobs.update(saved)
