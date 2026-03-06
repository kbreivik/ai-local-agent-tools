"""GET /api/tools — dynamic tool registry endpoints."""
import time
from fastapi import APIRouter, HTTPException, Query
from api.tool_registry import get_registry, invoke_tool
import api.logger as logger_mod

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(refresh: bool = Query(False)):
    """Return all auto-discovered tools with schema."""
    return {"tools": get_registry(refresh=refresh)}


@router.get("/{tool_name}")
async def get_tool(tool_name: str):
    """Return schema for a single tool."""
    registry = get_registry()
    tool = next((t for t in registry if t["name"] == tool_name), None)
    if not tool:
        raise HTTPException(404, f"Tool '{tool_name}' not found")
    return tool


@router.post("/{tool_name}/invoke")
async def invoke(tool_name: str, params: dict = {}):
    """Directly invoke a tool (bypasses agent loop). Logs to DB."""
    import uuid
    session_id = str(uuid.uuid4())
    op_id = await logger_mod.log_operation(session_id, f"direct:{tool_name}")
    t0 = time.monotonic()
    try:
        result = invoke_tool(tool_name, params)
        duration = int((time.monotonic() - t0) * 1000)
        await logger_mod.log_tool_call(op_id, tool_name, params, result,
                                       "direct", duration)
        status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        await logger_mod.complete_operation(op_id, status)
        return result
    except Exception as e:
        duration = int((time.monotonic() - t0) * 1000)
        err = {"status": "error", "message": str(e)}
        await logger_mod.log_tool_call(op_id, tool_name, params, err, "direct", duration)
        await logger_mod.complete_operation(op_id, "error")
        raise HTTPException(500, str(e))
