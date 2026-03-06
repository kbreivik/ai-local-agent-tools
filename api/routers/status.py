"""GET /api/status — live infrastructure status snapshots."""
import asyncio
from fastapi import APIRouter
import api.logger as logger_mod

router = APIRouter(prefix="/api/status", tags=["status"])


def _run_sync(fn):
    """Run a sync tool function and return result safely."""
    try:
        return fn()
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}


@router.get("")
async def get_status():
    """Returns current health of all infrastructure components."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    from mcp_server.tools.swarm import swarm_status, service_list
    from mcp_server.tools.kafka import kafka_broker_status

    swarm, services, kafka = await asyncio.gather(
        asyncio.get_event_loop().run_in_executor(None, swarm_status),
        asyncio.get_event_loop().run_in_executor(None, service_list),
        asyncio.get_event_loop().run_in_executor(None, kafka_broker_status),
    )

    # Persist snapshots
    for component, state in [("swarm", swarm), ("services", services), ("kafka", kafka)]:
        await logger_mod.log_status_snapshot(component, state)

    return {
        "swarm": swarm,
        "services": services,
        "kafka": kafka,
        "elasticsearch": {"status": "unknown", "message": "Not deployed", "data": None},
    }
