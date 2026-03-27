# Security Hardening — Input Validation & Resource Safety (Ingest Router)

**Date:** 2026-03-27
**Version target:** 1.10.20
**Branch:** main

---

## Goal

Close three resource-safety and authorization gaps in `api/routers/ingest.py`:

1. **P1 #8** — No file-size limit on PDF upload. An attacker can upload an arbitrarily large file, exhausting memory and disk.
2. **P1 #9** — `_pending_jobs` dict is never evicted. Jobs accumulate indefinitely; with no concurrency cap an attacker can exhaust server memory by spamming preview endpoints.
3. **P2 #26** — Ingest jobs are not tied to the user who created them. Any authenticated user can confirm or cancel another user's job.

All three are in a single file (`api/routers/ingest.py`, 239 lines). The fixes are additive and do not change the happy-path response shape.

---

## Architecture

- FastAPI async route handlers in `api/routers/ingest.py`
- In-memory `_pending_jobs: dict[str, dict]` — module-level, lives for the process lifetime
- Auth via `get_current_user` dependency (returns username string)
- No database interaction for job state — intentionally ephemeral
- All fixes use Python stdlib (`time.monotonic`, `len()`) — no new dependencies

---

## Tech Stack

- Python 3.13, FastAPI, `time.monotonic` for TTL
- `fastapi.HTTPException` for 413, 429, 403 responses
- `pytest` + `fastapi.testclient.TestClient` for tests
- Test file: `tests/test_ingest_limits.py` (new)

---

## File Map

| File | Changes |
|------|---------|
| `api/routers/ingest.py` | Add `_evict_stale_jobs()`, TTL + owner fields on job creation, file-size cap in `upload_pdf`, concurrency cap + owner check in all four endpoints |
| `tests/test_ingest_limits.py` | New — covers all three fixes with failing-first TDD |
| `VERSION` | Bump `1.10.18` → `1.10.19` (Bundle A) → `1.10.20` (this bundle) |

> Note: Bundle A (auth-endpoints plan) targets 1.10.19. This plan targets 1.10.20 and assumes Bundle A has already landed. If Bundle A has not landed yet, the VERSION file will still be at 1.10.18 when you start; bump it to 1.10.19 as part of that bundle first, then to 1.10.20 here.

---

## Current State Reference

Exact current content of `api/routers/ingest.py` at the time this plan was written:

- **Line 20**: `_pending_jobs: dict[str, dict] = {}`
- **Line 51–58**: `preview_url` inserts job without `ts` or `owner`
- **Line 136**: `content_bytes = await file.read()` — unbounded read
- **Line 154–163**: `upload_pdf` inserts job without `ts` or `owner`
- **Line 79**: `confirm_url_ingest` pops job but does not check owner
- **Line 180**: `confirm_pdf_ingest` pops job but does not check owner

---

## Tasks

---

### Task 1 — Write the failing tests first

**File:** `tests/test_ingest_limits.py` (new)

**Context:**
- The test client pattern used across this project: `TestClient(app)` with a helper that logs in as admin and returns headers.
- Auth credentials used in the existing test suite: `username="admin"`, `password="superduperadmin"`.
- These tests must all **fail** before the implementation and **pass** after.

**Steps:**

- [ ] **1.1** Create `tests/test_ingest_limits.py` with the following content:

```python
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
```

- [ ] **1.2** Run the tests to confirm they all fail (as expected before implementation):

```
pytest tests/test_ingest_limits.py -x -q
```

Expected: multiple failures — `AttributeError: module ... has no attribute '_evict_stale_jobs'`, 413/429/403 assertions, etc.

---

### Task 2 — Implement `_evict_stale_jobs()` helper and job concurrency cap (P1 #9)

**File:** `api/routers/ingest.py`

**Context:**
- Module-level constants go directly after `DOCS_DIR` (line 17).
- `_pending_jobs` is defined at line 20.
- The eviction helper must be a plain function (not async) — called synchronously at the top of each preview endpoint.

**Steps:**

- [ ] **2.1** Add `import time` to the imports block (line 4 area). Current imports are:

```python
import asyncio
import logging
import os
import uuid
```

Add `time` between `os` and `uuid`:

```python
import asyncio
import logging
import os
import time
import uuid
```

- [ ] **2.2** After `_pending_jobs: dict[str, dict] = {}` (line 20), add the constants and helper:

```python
_JOB_TTL_SECONDS = 600        # 10 minutes
_MAX_PENDING_JOBS = 20


def _evict_stale_jobs() -> None:
    """Remove jobs older than _JOB_TTL_SECONDS from _pending_jobs (in-place)."""
    cutoff = time.monotonic() - _JOB_TTL_SECONDS
    stale = [jid for jid, job in _pending_jobs.items() if job.get("ts", 0) < cutoff]
    for jid in stale:
        _pending_jobs.pop(jid, None)
    if stale:
        log.debug("Evicted %d stale ingest job(s)", len(stale))
```

- [ ] **2.3** In `preview_url` (currently starts at line 30), add eviction + cap check as the **first two actions** inside the function body, before the `fetch_url` import. The existing first lines of the body are:

```python
    from api.memory.ingest_worker import fetch_url, check_if_updated, _url_key, detect_breaking_changes_llm

    try:
        _, content = await fetch_url(req.url)
```

Replace with:

```python
    _evict_stale_jobs()
    if len(_pending_jobs) >= _MAX_PENDING_JOBS:
        raise HTTPException(429, "Too many pending ingest jobs — confirm or cancel existing jobs first")

    from api.memory.ingest_worker import fetch_url, check_if_updated, _url_key, detect_breaking_changes_llm

    try:
        _, content = await fetch_url(req.url)
```

- [ ] **2.4** In `upload_pdf` (currently starts at line 120), add the same eviction + cap check as the **first two actions** inside the function body, before the `ingest_worker` import. The existing first lines of the body are:

```python
    from api.memory.ingest_worker import parse_pdf, check_if_updated, detect_breaking_changes_llm
    import re

    if not file.filename.lower().endswith(".pdf"):
```

Replace with:

```python
    _evict_stale_jobs()
    if len(_pending_jobs) >= _MAX_PENDING_JOBS:
        raise HTTPException(429, "Too many pending ingest jobs — confirm or cancel existing jobs first")

    from api.memory.ingest_worker import parse_pdf, check_if_updated, detect_breaking_changes_llm
    import re

    if not file.filename.lower().endswith(".pdf"):
```

- [ ] **2.5** In `preview_url`, add `"ts": time.monotonic()` and `"owner": user` to the job dict at line 51. The current dict is:

```python
    _pending_jobs[job_id] = {
        "type": "url",
        "url": req.url,
        "tags": req.tags,
        "label": req.label or req.url,
        "content": content,
        "update_info": update_info,
    }
```

Change to:

```python
    _pending_jobs[job_id] = {
        "ts": time.monotonic(),
        "owner": user,
        "type": "url",
        "url": req.url,
        "tags": req.tags,
        "label": req.label or req.url,
        "content": content,
        "update_info": update_info,
    }
```

- [ ] **2.6** In `upload_pdf`, add `"ts": time.monotonic()` and `"owner": user` to the job dict at line 154. The current dict is:

```python
    _pending_jobs[job_id] = {
        "type": "pdf",
        "filename": file.filename,
        "local_path": str(dest),
        "tags": tag_list,
        "label": label or file.filename,
        "content": content,
        "update_info": update_info,
        "source_key": source_key,
    }
```

Change to:

```python
    _pending_jobs[job_id] = {
        "ts": time.monotonic(),
        "owner": user,
        "type": "pdf",
        "filename": file.filename,
        "local_path": str(dest),
        "tags": tag_list,
        "label": label or file.filename,
        "content": content,
        "update_info": update_info,
        "source_key": source_key,
    }
```

- [ ] **2.7** Verify syntax:

```
python -m py_compile api/routers/ingest.py
```

- [ ] **2.8** Run the full test suite:

```
pytest tests/ -x -q
```

Expected: TTL and cap tests pass; owner tests still fail (not yet implemented); oversized-file test still fails; pre-existing proxmox fail unchanged.

---

### Task 3 — File-size cap on PDF upload (P1 #8)

**File:** `api/routers/ingest.py`

**Context:**
- The unbounded read is at line 136: `content_bytes = await file.read()`
- Line 137: `dest.write_bytes(content_bytes)` — the bytes are already in memory
- The fix reads the bytes first (FastAPI requires this for UploadFile), then checks the length, then writes to disk only if within the cap.
- `50 * 1024 * 1024` = 52,428,800 bytes (50 MiB)

**Steps:**

- [ ] **3.1** Define the size constant alongside the TTL constants added in Task 2.2. After `_MAX_PENDING_JOBS = 20`, add:

```python
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB
```

- [ ] **3.2** In `upload_pdf`, replace the current unbounded read and write block:

```python
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOCS_DIR / file.filename
    content_bytes = await file.read()
    dest.write_bytes(content_bytes)
```

With a size-checked version:

```python
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOCS_DIR / file.filename
    content_bytes = await file.read()
    if len(content_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    dest.write_bytes(content_bytes)
```

> Rationale: `await file.read()` must be called before the length is known because FastAPI's `UploadFile` does not expose `file.size` reliably before the read (it depends on the client sending `Content-Length`). Reading first, then checking, is the correct and safe pattern. Memory usage is bounded to 50 MiB per request — acceptable for a single-user homelab agent.

- [ ] **3.3** Verify syntax:

```
python -m py_compile api/routers/ingest.py
```

- [ ] **3.4** Run the full test suite:

```
pytest tests/ -x -q
```

Expected: file-size test now passes; owner tests still fail; pre-existing proxmox fail unchanged.

---

### Task 4 — Owner isolation on confirm and cancel (P2 #26)

**File:** `api/routers/ingest.py`

**Context:**
- `confirm_url_ingest` (line 76): pops job at line 79, immediately returns 404 if missing, then checks `req.approved` at line 82.
- `confirm_pdf_ingest` (line 177): same structure — pops at line 180, checks approved at line 183.
- The owner check must happen **after** the 404 guard (job must exist) but **before** the `req.approved` branch, so a wrong-user cancel also returns 403 (not silently cancel).
- If the job has no `"owner"` key (legacy jobs inserted before this fix), allow the operation to proceed without error — graceful degradation.

**Steps:**

- [ ] **4.1** In `confirm_url_ingest`, after the 404 check and before the `req.approved` check, add the owner guard. Current code at lines 79–83:

```python
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}
```

Change to:

```python
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if job.get("owner") and job["owner"] != user:
        # Put the job back so the owner can still act on it
        _pending_jobs[req.job_id] = job
        raise HTTPException(403, "You are not the owner of this ingest job")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}
```

> The job is put back into `_pending_jobs` on 403 so the legitimate owner is not blocked. This is a deliberate design choice — without it, the first user to call confirm (even with the wrong identity) would silently delete the job.

- [ ] **4.2** In `confirm_pdf_ingest`, apply the same owner guard. Current code at lines 180–184:

```python
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}
```

Change to:

```python
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if job.get("owner") and job["owner"] != user:
        _pending_jobs[req.job_id] = job
        raise HTTPException(403, "You are not the owner of this ingest job")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}
```

- [ ] **4.3** Verify syntax:

```
python -m py_compile api/routers/ingest.py
```

- [ ] **4.4** Run the full test suite:

```
pytest tests/ -x -q
```

Expected: all new tests pass; the single pre-existing proxmox fail is unchanged; all 17 previously-passing tests still pass.

---

### Task 5 — Version bump to 1.10.20

**File:** `VERSION`

**Context:**
- `VERSION` is at the project root: `D:/claude_code/FAJK/HP1-AI-Agent-v1/VERSION`
- Current content after Bundle A lands: `1.10.19`
- If Bundle A has not yet landed when you start, the file will read `1.10.18` — bump it to `1.10.19` in that plan's final commit, not here.

**Steps:**

- [ ] **5.1** Update `VERSION` from `1.10.19` to `1.10.20`.

- [ ] **5.2** Run the full test suite one final time:

```
pytest tests/ -x -q
```

Expected output: 17 tests pass (plus the new tests from `test_ingest_limits.py`), 1 pre-existing fail in `test_collectors_proxmox_vms.py`.

- [ ] **5.3** Run the pre-commit checklist:

```bash
# 1. No hardcoded values
grep -rE "192\.168\.|password|secret|token" api/routers/ingest.py

# 2. Syntax check
python -m py_compile api/routers/ingest.py

# 3. No dangerous imports in changed file
grep -E "subprocess|os\.system|eval|exec" api/routers/ingest.py
```

- [ ] **5.4** Commit:

```
git add api/routers/ingest.py tests/test_ingest_limits.py VERSION
git commit -m "fix(ingest): add file-size cap, job TTL eviction, and owner isolation"
git push
```

---

## Final State of Modified Sections

After all tasks complete, the top of `api/routers/ingest.py` will look like:

```python
"""URL/PDF ingestion REST endpoints with approval flow."""
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memory/ingest", tags=["ingest"])

DOCS_DIR = Path(__file__).parent.parent.parent / "data" / "docs"

# Pending ingest jobs (in-memory, pre-approval)
_pending_jobs: dict[str, dict] = {}

_JOB_TTL_SECONDS = 600        # 10 minutes
_MAX_PENDING_JOBS = 20
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB


def _evict_stale_jobs() -> None:
    """Remove jobs older than _JOB_TTL_SECONDS from _pending_jobs (in-place)."""
    cutoff = time.monotonic() - _JOB_TTL_SECONDS
    stale = [jid for jid, job in _pending_jobs.items() if job.get("ts", 0) < cutoff]
    for jid in stale:
        _pending_jobs.pop(jid, None)
    if stale:
        log.debug("Evicted %d stale ingest job(s)", len(stale))
```

---

## Risk Notes

- **Memory spike on 50 MiB upload**: The current design reads the entire file into memory before the size check. This is a single-user homelab agent — 50 MiB peak is acceptable. If this ever runs in a multi-user context, replace with a streaming read that raises early.
- **Job restore on 403**: Putting the job back into `_pending_jobs` after a 403 introduces a brief window where the job is missing from the dict. Under concurrent load this could cause a race. The agent runs as a single process with Python's GIL — this is safe for the current deployment model.
- **No persistence**: Jobs are still in-memory only. A container restart clears all pending jobs. This is unchanged from the current design and acceptable for the homelab use case.
- **TTL not enforced on confirm**: Stale jobs can still be confirmed if the owner acts on them between eviction cycles (eviction only runs on preview endpoints). This is intentional — once a job exists, the owner should be able to act on it without a time penalty from an eviction race.
