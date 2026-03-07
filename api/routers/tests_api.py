"""
GET  /api/tests/results  — last test run results
POST /api/tests/run      — trigger test suite in background
GET  /api/tests/cases    — list all test case definitions
"""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/tests", tags=["tests"])

RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "test_results.json"

# Module-level flag to prevent concurrent runs
_running = False


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
    from tests.integration.test_agent import TEST_CASES
    return {
        "cases": [
            {
                "id":            tc.id,
                "category":      tc.category,
                "task":          tc.task,
                "soft":          tc.soft,
                "critical":      tc.critical,
                "timeout":       tc.timeout,
                "expected_tools": tc.expected_tools,
                "expected_agent_type": tc.expected_agent_type,
            }
            for tc in TEST_CASES
        ],
        "total": len(TEST_CASES),
    }


class RunTestsRequest(BaseModel):
    categories: Optional[list[str]] = None


async def _run_tests_bg(categories: list[str] | None) -> None:
    global _running
    _running = True
    try:
        from tests.integration.test_agent import run_all_tests, save_results
        results = await run_all_tests(categories=categories)
        save_results(results)
    except Exception as e:
        # Write error result
        import json
        from datetime import datetime, timezone
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "total": 0, "passed": 0, "failed": 0, "score_pct": 0, "results": [],
        }, indent=2))
    finally:
        _running = False


@router.post("/run")
async def run_tests(req: RunTestsRequest, background_tasks: BackgroundTasks):
    """Trigger test suite. Runs in background — poll /api/tests/results."""
    global _running
    if _running:
        return {"status": "already_running", "message": "Test run already in progress"}

    valid_cats = {"status", "research", "ambiguous", "action", "safety"}
    if req.categories:
        unknown = set(req.categories) - valid_cats
        if unknown:
            return {"status": "error", "message": f"Unknown categories: {unknown}"}

    background_tasks.add_task(_run_tests_bg, req.categories)
    return {
        "status":  "started",
        "message": f"Running {'all' if not req.categories else req.categories} tests in background",
        "poll":    "/api/tests/results",
    }
