"""
GET  /api/tests/results  — last test run results
POST /api/tests/run      — trigger test suite in background
GET  /api/tests/cases    — list all test case definitions

v2.44.1 additions:
GET    /api/tests/suites                 — list named test suites
POST   /api/tests/suites                 — create/update suite
DELETE /api/tests/suites/{id}            — delete suite
GET    /api/tests/runs                   — list historical runs
GET    /api/tests/runs/compare?ids=a,b,c,d — compare up to 4 runs
GET    /api/tests/runs/{run_id}          — full run with results
GET    /api/tests/trend                  — score over time per suite
GET    /api/tests/schedules              — list cron schedules
POST   /api/tests/schedules              — create schedule
DELETE /api/tests/schedules/{id}         — delete schedule
POST   /api/tests/schedules/{id}/toggle  — enable/disable schedule
"""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from api.auth import get_current_user
from api.db import test_runs as tr_db

router = APIRouter(prefix="/api/tests", tags=["tests"])

RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "test_results.json"

# Module-level flag to prevent concurrent runs
_running = False

# Exported flag — checked by api/alerts.py to suppress collector noise
# during test runs (SSH load from agents causes false vm_hosts/network_ssh alerts)
test_run_active = False


@router.get("/results")
async def get_test_results():
    """Return last test run results."""
    if not RESULTS_PATH.exists():
        return {"status": "no_results", "message": "No test run yet. POST /api/tests/run to start."}
    try:
        return json.loads(RESULTS_PATH.read_text())
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/running")
async def get_test_running():
    """Return whether a test run is in progress."""
    return {"running": _running}


@router.get("/cases")
async def get_test_cases():
    """List all defined test cases."""
    from api.db.test_definitions import TestCase, TEST_CASES
    return {
        "cases": [
            {
                "id":                   tc.id,
                "category":             tc.category,
                "task":                 tc.task,
                "soft":                 tc.soft,
                "critical":             tc.critical,
                "timeout_s":            tc.timeout_s,
                "expect_tools":         tc.expect_tools,
                "forbid_tools":         tc.forbid_tools,
                "agent_type":           tc.agent_type,
                "triggers_plan":        tc.triggers_plan,
                "triggers_clarification": tc.triggers_clarification,
                "max_steps":            tc.max_steps,
            }
            for tc in TEST_CASES
        ],
        "total": len(TEST_CASES),
    }


class RunTestsRequest(BaseModel):
    categories: Optional[list[str]] = None
    test_ids: Optional[list[str]] = None      # specific test IDs to run
    suite_id: Optional[str] = None            # suite to run
    memory_enabled: Optional[bool] = None     # override memoryEnabled setting for this run


async def _run_tests_bg(
    categories: list[str] | None,
    test_ids: list[str] | None = None,
    suite_id: str | None = None,
    memory_enabled: bool | None = None,
    memory_backend: str | None = None,
    suite_name: str = "",
    caller_token: str = "",
) -> None:
    global _running, test_run_active
    _running = True
    test_run_active = True

    # v2.45.32 — capture pre-run settings so we can restore them after.
    _restore_memory_enabled = None
    _restore_memory_backend = None
    try:
        from api.settings_manager import get_setting as _gs
        _restore_memory_enabled = (_gs("memoryEnabled") or {}).get("value")
        _restore_memory_backend = (_gs("memoryBackend") or {}).get("value")
    except Exception:
        pass

    try:
        # ── 1. Load suite config if suite_id provided ─────────────────────
        if suite_id:
            try:
                from api.db import test_runs as _tr
                suites = _tr.list_suites()
                suite = next((s for s in suites if s["id"] == suite_id), None)
                if suite:
                    suite_name = suite_name or suite.get("name", "")
                    cfg = suite.get("config") or {}
                    if not categories:
                        categories = suite.get("categories") or []
                    if not test_ids:
                        test_ids = suite.get("test_ids") or []
                    if memory_enabled is None:
                        memory_enabled = cfg.get("memoryEnabled", True)
                    if memory_backend is None:
                        memory_backend = cfg.get("memoryBackend", "muninndb")
            except Exception as _se:
                import logging; logging.getLogger(__name__).debug("suite load: %s", _se)

        # ── 2. Apply memory settings ──────────────────────────────────────
        if memory_enabled is not None:
            try:
                from api.settings_manager import set_setting
                set_setting("memoryEnabled", memory_enabled)
            except Exception: pass
        if memory_backend is not None:
            try:
                from api.settings_manager import set_setting
                set_setting("memoryBackend", memory_backend)
            except Exception: pass

        # ── 3. Run tests ──────────────────────────────────────────────────
        from api.db.test_definitions import TEST_CASES
        from tests.integration.test_agent import run_all_tests, save_results
        from datetime import datetime, timezone
        import httpx

        _t_start = datetime.now(timezone.utc)

        # Filter cases
        cases_to_run = TEST_CASES
        if categories:
            cases_to_run = [tc for tc in cases_to_run if tc.category in categories]
        if test_ids:
            cases_to_run = [tc for tc in cases_to_run if tc.id in test_ids]

        # Generate a fresh internal JWT — the caller's token may be stale
        # (localStorage token from before v2.30.1 httpOnly cookie switch).
        # The WS connection uses ?token= (no cookie), so must be a valid JWT.
        from api.auth import create_internal_token
        _fresh_token = create_internal_token(expires_minutes=180)
        _auth_headers = {"Authorization": f"Bearer {_fresh_token}"} if _fresh_token else {}
        async with httpx.AsyncClient(timeout=30.0, headers=_auth_headers) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
                token=_fresh_token,
                cases=cases_to_run if (test_ids or (categories and len(categories) < 6)) else None,
            )

        save_results(results)
        _t_end = datetime.now(timezone.utc)

        # ── 4. Persist to DB ──────────────────────────────────────────────
        try:
            from api.db import test_runs as tr_db_inner
            results_data = {}
            try:
                results_data = json.loads(RESULTS_PATH.read_text())
            except Exception:
                results_data = {}

            run_id = tr_db_inner.create_run(
                suite_id=suite_id,
                suite_name=suite_name or ((",".join(categories)) if categories else "all"),
                config={
                    "categories": categories or [],
                    "test_ids": test_ids or [],
                    "suite_id": suite_id,
                    "memoryEnabled": memory_enabled,
                    "memoryBackend": memory_backend,
                },
                triggered_by="api",
                started_at=_t_start,
            )
            for r in results_data.get("results", []):
                tr_db_inner.insert_result(run_id, r)
            tr_db_inner.finish_run(
                run_id=run_id,
                total=results_data.get("total", 0),
                passed=results_data.get("passed", 0),
                score_pct=results_data.get("score_pct", 0),
                weighted_pct=results_data.get("weighted_pct", 0),
                finished_at=_t_end,
            )
        except Exception as _dbe:
            import logging
            logging.getLogger(__name__).debug("DB persist failed: %s", _dbe)

    except Exception as e:
        import json as _json
        from datetime import datetime, timezone
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(_json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "total": 0, "passed": 0, "failed": 0, "score_pct": 0, "results": [],
        }, indent=2))
    finally:
        # v2.45.32 — restore the pre-run setting state so a manual user run
        # immediately after a memory-off baseline is not silently degraded.
        try:
            from api.settings_manager import set_setting as _ss
            if _restore_memory_enabled is not None and memory_enabled is not None:
                _ss("memoryEnabled", _restore_memory_enabled)
            if _restore_memory_backend is not None and memory_backend is not None:
                _ss("memoryBackend", _restore_memory_backend)
        except Exception as _re:
            import logging as _rl
            _rl.getLogger(__name__).warning(
                "v2.45.32 settings restore failed: %s", _re,
            )
        _running = False
        test_run_active = False


@router.post("/run")
async def run_tests(
    request: Request,
    body: RunTestsRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_user),
):
    global _running
    if _running:
        return {"status": "already_running",
                "message": "A test run is already in progress."}

    # Extract the caller's Bearer token — pass it to the test runner so it can
    # make authenticated requests to /api/agent/run and the WebSocket.
    auth_header = request.headers.get("Authorization", "")
    caller_token = auth_header.removeprefix("Bearer ").strip()

    background_tasks.add_task(
        _run_tests_bg,
        categories=body.categories,
        test_ids=body.test_ids,
        suite_id=body.suite_id,
        memory_enabled=body.memory_enabled,
        suite_name="",
        caller_token=caller_token,
    )
    return {"status": "started",
            "message": f"Test run started (suite={body.suite_id}, categories={body.categories}, ids={len(body.test_ids or [])} tests)"}


# ── Suites ────────────────────────────────────────────────────────────────────

@router.get("/suites")
async def list_suites_endpoint(_: str = Depends(get_current_user)):
    return {"suites": tr_db.list_suites()}


class SuiteRequest(BaseModel):
    name: str
    description: str = ""
    test_ids: list[str] = []
    categories: list[str] = []
    config: dict = {}


@router.post("/suites")
async def create_suite(body: SuiteRequest, _: str = Depends(get_current_user)):
    result = tr_db.upsert_suite(
        name=body.name, description=body.description,
        test_ids=body.test_ids, categories=body.categories, config=body.config,
    )
    return {"suite": result}


@router.delete("/suites/{suite_id}")
async def remove_suite(suite_id: str, _: str = Depends(get_current_user)):
    tr_db.delete_suite(suite_id)
    return {"status": "ok"}


# ── Runs ──────────────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs_endpoint(limit: int = 50, suite_id: str = None, _: str = Depends(get_current_user)):
    return {"runs": tr_db.list_runs(limit=limit, suite_id=suite_id)}


@router.get("/runs/compare")
async def compare_runs(ids: str, _: str = Depends(get_current_user)):
    run_ids = [i.strip() for i in ids.split(",") if i.strip()][:4]
    return {"runs": tr_db.get_compare(run_ids)}


@router.get("/runs/{run_id}")
async def get_run_endpoint(run_id: str, _: str = Depends(get_current_user)):
    run = tr_db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/trend")
async def get_trend_endpoint(suite_id: str = None, limit: int = 30, _: str = Depends(get_current_user)):
    return {"trend": tr_db.get_trend(suite_id=suite_id, limit=limit)}


# ── Schedules ─────────────────────────────────────────────────────────────────

@router.get("/schedules")
async def list_schedules_endpoint(_: str = Depends(get_current_user)):
    return {"schedules": tr_db.list_schedules()}


class ScheduleRequest(BaseModel):
    name: str
    suite_id: str
    cron: str
    enabled: bool = True


@router.post("/schedules")
async def create_schedule(body: ScheduleRequest, _: str = Depends(get_current_user)):
    result = tr_db.upsert_schedule(
        name=body.name, suite_id=body.suite_id, cron=body.cron, enabled=body.enabled,
    )
    return {"schedule": result}


@router.delete("/schedules/{schedule_id}")
async def remove_schedule(schedule_id: str, _: str = Depends(get_current_user)):
    tr_db.delete_schedule(schedule_id)
    return {"status": "ok"}


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule_endpoint(schedule_id: str, body: dict, _: str = Depends(get_current_user)):
    tr_db.toggle_schedule(schedule_id, body.get("enabled", True))
    return {"status": "ok"}
