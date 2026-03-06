"""POST /api/agent/run — execute agent task, stream output via WebSocket."""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from api.websocket import manager
import api.logger as logger_mod

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _lm_base():  return os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
def _lm_model(): return os.environ.get("LM_STUDIO_MODEL", "lmstudio-community/qwen3-coder-30b-a3b-instruct")
def _lm_key():   return os.environ.get("LM_STUDIO_API_KEY", "lm-studio")

# Ensure project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.tool_registry import get_registry, invoke_tool

SYSTEM_PROMPT = """You are an infrastructure orchestration agent for a Docker Swarm + Kafka cluster.

RULES:
1. check → act → verify → continue or halt
2. Before ANY service upgrade: call pre_upgrade_check(). If not ok, HALT.
3. Before ANY Kafka operation: call pre_kafka_check(). If not ok, HALT.
4. If any tool returns status=degraded or status=failed: call escalate() immediately.
5. Call audit_log() after EVERY tool call and decision.
6. Call checkpoint_save() before any risky operation.
7. Never skip a check step.

Think step by step. Log reasoning. Never skip verifications."""


def _build_tools_spec() -> list[dict]:
    registry = get_registry()
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["schema"],
            },
        }
        for t in registry
    ]


class RunRequest(BaseModel):
    task: str = "Perform a full infrastructure health check and report status."
    session_id: str = ""


class RunResponse(BaseModel):
    session_id: str
    operation_id: int
    message: str


async def _stream_agent(task: str, session_id: str, operation_id: int):
    """Run the full agent loop, streaming every step to WebSocket clients."""
    from openai import OpenAI

    base_url = _lm_base()
    model    = _lm_model()
    api_key  = _lm_key()

    client = OpenAI(base_url=base_url, api_key=api_key)
    tools_spec = _build_tools_spec()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    await manager.send_line("step", f"Agent started — task: {task}", status="ok")
    await manager.send_line("step", f"Model: {model}", status="ok")

    step = 0
    max_steps = 40
    final_status = "completed"

    try:
        while step < max_steps:
            step += 1
            await manager.send_line("step", f"── Step {step} ──")

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools_spec,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                )
            except Exception as e:
                await manager.send_line("error", f"LM Studio error: {e}", status="error")
                final_status = "error"
                break

            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            if msg.content:
                await manager.send_line("reasoning", msg.content)

            if finish == "stop" or not msg.tool_calls:
                await manager.send_line("done", f"Agent finished after {step} steps.",
                                        status="ok")
                break

            # Build assistant message for history
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name,
                                     "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            halt = False
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                t0 = time.monotonic()
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda n=fn_name, a=fn_args: invoke_tool(n, a)
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e), "data": None,
                              "timestamp": datetime.now(timezone.utc).isoformat()}

                duration_ms = int((time.monotonic() - t0) * 1000)
                result_status = result.get("status", "error") if isinstance(result, dict) else "error"
                result_msg = result.get("message", "") if isinstance(result, dict) else str(result)

                # Log to SQLite
                await logger_mod.log_tool_call(
                    operation_id, fn_name, fn_args, result,
                    model, duration_ms
                )

                # Stream to GUI
                await manager.send_line(
                    "tool",
                    f"[{fn_name}] → {result_status} | {result_msg}",
                    tool=fn_name,
                    status=result_status,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

                if result_status in ("degraded", "failed"):
                    await manager.send_line(
                        "halt",
                        f"HALT: {fn_name} returned {result_status} — escalating",
                        tool=fn_name,
                        status="escalated",
                    )
                    # Auto-escalate
                    try:
                        esc = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: invoke_tool(
                                "escalate",
                                {"reason": f"Tool '{fn_name}' returned {result_status}: {result_msg}"},
                            ),
                        )
                        await logger_mod.log_tool_call(
                            operation_id, "escalate",
                            {"reason": f"{fn_name} → {result_status}"}, esc,
                            model, 0,
                        )
                    except Exception:
                        pass
                    halt = True
                    final_status = "escalated"
                    break

            if halt:
                await manager.send_line("halt", "Agent halted — human review required.",
                                        status="escalated")
                break

        else:
            await manager.send_line("done", f"Agent reached max steps ({max_steps}).",
                                    status="ok")

    except Exception as e:
        await manager.send_line("error", f"Agent loop error: {e}", status="error")
        final_status = "error"

    await logger_mod.complete_operation(operation_id, final_status)


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks):
    """Start an agent task. Streams output to ws://host:8000/ws/output."""
    session_id = req.session_id or str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task[:120])
    background_tasks.add_task(_stream_agent, req.task, session_id, operation_id)
    return RunResponse(
        session_id=session_id,
        operation_id=operation_id,
        message="Agent started — connect to ws://[host]:8000/ws/output for live output",
    )


@router.get("/models")
async def list_models():
    """Probe LM Studio for loaded models."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=_lm_base(), api_key=_lm_key())
        models = client.models.list()
        return {"models": [m.id for m in models.data], "base_url": _lm_base()}
    except Exception as e:
        return {"models": [], "error": str(e), "base_url": _lm_base()}
