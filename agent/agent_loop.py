"""Agent loop: connects to LM Studio and drives tool calls with checks/balances."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.tools import swarm, kafka, orchestration

LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "lmstudio-community/qwen3-coder-30b-a3b-instruct")
# LM Studio authentication token — set LM_STUDIO_API_KEY in your environment
# or in .env file. Find it in LM Studio → Developer → API Key.
LM_STUDIO_API_KEY = os.environ.get("LM_STUDIO_API_KEY", "lm-studio")

SYSTEM_PROMPT = """You are an infrastructure orchestration agent for a Docker Swarm + Kafka cluster.

RULES — you must follow these exactly:
1. check → act → verify → continue or halt
2. Before ANY service upgrade: call pre_upgrade_check(). If not "ok", HALT.
3. Before ANY Kafka operation: call pre_kafka_check(). If not "ok", HALT.
4. If any tool returns status=degraded or status=failed: call escalate() immediately.
5. Call audit_log() after EVERY tool call and decision.
6. Call checkpoint_save() before any risky operation.
7. Never skip a check step, even if the previous step succeeded.
8. NEVER switch Docker image vendors (e.g. apache→confluentinc, nginx→openresty)
   without explicit user instruction to do so. If a downgrade path requires a vendor
   switch, call escalate() instead. Only pass task_hint to service_upgrade() when the
   user's task explicitly contains "switch image", "change vendor", or "migrate to".

EFFICIENCY RULES:
- Never dedicate a full step to only audit_log() calls. Call audit_log() immediately
  after the tool it documents, in the same step — combine them in one response.
- Never re-check something already checked in this session unless a tool returned
  degraded or failed. Redundant re-checks waste steps.
- Before upgrading any service, call service_current_version() to confirm the running
  image. If current image == target image, skip the upgrade, log "already at target
  version", and continue. Never upgrade a service that is already at the target version.
- Use service_resolve_image() to find the latest stable tag before upgrading. Never
  upgrade to an intermediate version when a newer stable version is already available.

Your task: Perform a rolling upgrade of the 'workload' service from nginx:1.25-alpine to
nginx:1.26-alpine while Kafka is under load, with health gates at every step.

Available tools: swarm_status, service_list, service_health, service_upgrade,
service_rollback, service_current_version, node_drain, pre_upgrade_check,
kafka_broker_status, kafka_consumer_lag, kafka_topic_health, kafka_rolling_restart_safe,
pre_kafka_check, checkpoint_save, checkpoint_restore, audit_log, escalate.

Think step by step. Log reasoning. Never skip verifications."""

TOOLS = [
    {"type": "function", "function": {"name": "swarm_status", "description": "Node health, manager/worker state", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "service_list", "description": "All services, replicas, image versions", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "service_health", "description": "Specific service ready/degraded/failed state", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "service_upgrade", "description": "Rolling upgrade with health gate", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "image": {"type": "string"}}, "required": ["name", "image"]}}},
    {"type": "function", "function": {"name": "service_rollback", "description": "Revert service to previous image", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "service_current_version", "description": "Currently running image tag for a service — call before deciding to upgrade", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "service_resolve_image", "description": "Resolve latest stable semver tag for an image from Docker Hub — use before upgrade to avoid intermediate versions", "parameters": {"type": "object", "properties": {"image": {"type": "string"}}, "required": ["image"]}}},
    {"type": "function", "function": {"name": "node_drain", "description": "Safe drain before maintenance", "parameters": {"type": "object", "properties": {"node_id": {"type": "string"}}, "required": ["node_id"]}}},
    {"type": "function", "function": {"name": "pre_upgrade_check", "description": "Full swarm readiness gate", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "kafka_broker_status", "description": "Broker health, leader election state", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "kafka_consumer_lag", "description": "Lag per topic/partition", "parameters": {"type": "object", "properties": {"group": {"type": "string"}}, "required": ["group"]}}},
    {"type": "function", "function": {"name": "kafka_topic_health", "description": "Partition count, replication, under-replicated", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}},
    {"type": "function", "function": {"name": "kafka_rolling_restart_safe", "description": "Checks ISR before each broker restart", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "pre_kafka_check", "description": "Full Kafka readiness gate", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "checkpoint_save", "description": "Snapshot state before risky ops", "parameters": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}}},
    {"type": "function", "function": {"name": "checkpoint_restore", "description": "Rollback to saved state", "parameters": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}}},
    {"type": "function", "function": {"name": "audit_log", "description": "Structured log of every decision", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "result": {"type": "string"}}, "required": ["action", "result"]}}},
    {"type": "function", "function": {"name": "escalate", "description": "Flag decision as high-risk, log and pause", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]

TOOL_MAP = {
    "swarm_status": lambda args: swarm.swarm_status(),
    "service_list": lambda args: swarm.service_list(),
    "service_health": lambda args: swarm.service_health(args["name"]),
    "service_upgrade": lambda args: swarm.service_upgrade(args["name"], args["image"]),
    "service_rollback": lambda args: swarm.service_rollback(args["name"]),
    "service_current_version": lambda args: swarm.service_current_version(args["name"]),
    "service_resolve_image": lambda args: swarm.service_resolve_image(args["image"]),
    "node_drain": lambda args: swarm.node_drain(args["node_id"]),
    "pre_upgrade_check": lambda args: swarm.pre_upgrade_check(),
    "kafka_broker_status": lambda args: kafka.kafka_broker_status(),
    "kafka_consumer_lag": lambda args: kafka.kafka_consumer_lag(args["group"]),
    "kafka_topic_health": lambda args: kafka.kafka_topic_health(args["topic"]),
    "kafka_rolling_restart_safe": lambda args: kafka.kafka_rolling_restart_safe(),
    "pre_kafka_check": lambda args: kafka.pre_kafka_check(),
    "checkpoint_save": lambda args: orchestration.checkpoint_save(args["label"]),
    "checkpoint_restore": lambda args: orchestration.checkpoint_restore(args["label"]),
    "audit_log": lambda args: orchestration.audit_log(args["action"], args["result"]),
    "escalate": lambda args: orchestration.escalate(args["reason"]),
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def dispatch_tool(name: str, args: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        result = {"status": "error", "message": f"Unknown tool: {name}", "timestamp": _ts()}
    else:
        try:
            result = fn(args)
        except Exception as e:
            result = {"status": "error", "message": str(e), "timestamp": _ts()}
    # Auto audit-log every tool call (except audit_log itself to avoid recursion)
    if name != "audit_log":
        orchestration.audit_log(f"tool:{name}", {"args": args, "result_status": result.get("status")})
    result_str = json.dumps(result)
    print(f"  [{name}] → {result.get('status', '?')} | {result.get('message', '')}")
    # Halt condition
    if result.get("status") in ("degraded", "failed", "escalated"):
        print(f"\n  !! HALT CONDITION: {name} returned {result['status']}")
    return result_str


def run_agent(user_task: str | None = None):
    client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key=LM_STUDIO_API_KEY)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_task or "Begin the rolling upgrade task now."},
    ]
    orchestration.audit_log("agent_start", {"task": user_task or "rolling_upgrade", "model": LM_STUDIO_MODEL})
    print(f"\n=== Agent Loop Started @ {_ts()} ===")
    print(f"Model: {LM_STUDIO_MODEL}")
    print(f"LM Studio: {LM_STUDIO_BASE_URL}\n")

    step = 0
    max_steps = 40
    while step < max_steps:
        step += 1
        print(f"\n--- Step {step} ---")
        response = client.chat.completions.create(
            model=LM_STUDIO_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=2048,
        )
        msg = response.choices[0].message
        finish = response.choices[0].finish_reason

        if msg.content:
            print(f"[Reasoning] {msg.content[:300]}{'...' if len(msg.content or '') > 300 else ''}")

        if finish == "stop" or (not msg.tool_calls):
            print(f"\n=== Agent finished after {step} steps ===")
            orchestration.audit_log("agent_complete", {"steps": step, "final_message": msg.content})
            return msg.content

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})

        halt = False
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            result_str = dispatch_tool(fn_name, fn_args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})
            result = json.loads(result_str)
            if result.get("status") in ("degraded", "failed"):
                escalation = orchestration.escalate(
                    f"Tool '{fn_name}' returned {result['status']}: {result.get('message', '')}"
                )
                messages.append({"role": "tool", "tool_call_id": tc.id + "_escalate",
                                  "content": json.dumps(escalation)})
                halt = True
                break

        if halt:
            print(f"\n=== Agent HALTED at step {step} — escalation triggered ===")
            orchestration.audit_log("agent_halted", {"step": step, "reason": "degraded_or_failed_tool"})
            return None

    print(f"\n=== Agent reached max steps ({max_steps}) ===")
    orchestration.audit_log("agent_max_steps", {"steps": step})
    return None


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    run_agent(task)
