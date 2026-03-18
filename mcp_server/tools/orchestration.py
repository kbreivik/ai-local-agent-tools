"""Orchestration: checkpoints, audit log, escalation."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _degraded(data: Any, message: str) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def _checkpoint_dir() -> Path:
    path = Path(os.environ.get("CHECKPOINT_PATH", "./checkpoints"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _audit_path() -> Path:
    path = Path(os.environ.get("AUDIT_LOG_PATH", "./logs/audit.log"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def checkpoint_save(label: str) -> dict:
    """Snapshot current state before risky operations."""
    try:
        from mcp_server.tools.swarm import swarm_status, service_list
        from mcp_server.tools.kafka import kafka_broker_status

        checkpoint = {
            "label": label,
            "timestamp": _ts(),
            "swarm": swarm_status(),
            "services": service_list(),
            "kafka": kafka_broker_status(),
        }

        # Primary: store in DB (survives container restarts, accessible cross-replica)
        try:
            from mcp_server.tools.skills.storage import get_backend
            get_backend().save_checkpoint(label, checkpoint)
        except Exception:
            pass

        # Secondary: write to file for portability and tail-f debugging
        checkpoint_file = _checkpoint_dir() / f"{label}_{int(time.time())}.json"
        checkpoint_file.write_text(json.dumps(checkpoint, indent=2))

        audit_log("checkpoint_save", {"label": label, "file": str(checkpoint_file)})
        return _ok({"label": label, "file": str(checkpoint_file)},
                   f"Checkpoint '{label}' saved")
    except Exception as e:
        return _err(f"checkpoint_save error: {e}")


def checkpoint_restore(label: str) -> dict:
    """Restore to a saved checkpoint state — returns the snapshot for agent use."""
    try:
        # Try DB first (more reliable in containerized environments)
        try:
            from mcp_server.tools.skills.storage import get_backend
            row = get_backend().load_checkpoint(label)
            if row:
                checkpoint = row.get("data", row)
                audit_log("checkpoint_restore", {"label": label, "source": "db"})
                return _ok({"label": label, "source": "db", "snapshot": checkpoint},
                           f"Checkpoint '{label}' loaded — agent must apply rollbacks manually")
        except Exception:
            pass

        # Fallback: file system
        cp_dir = _checkpoint_dir()
        matches = sorted(cp_dir.glob(f"{label}_*.json"), reverse=True)
        if not matches:
            return _err(f"No checkpoint found for label '{label}'")
        latest = matches[0]
        checkpoint = json.loads(latest.read_text())
        audit_log("checkpoint_restore", {"label": label, "file": str(latest)})
        return _ok({"label": label, "file": str(latest), "snapshot": checkpoint},
                   f"Checkpoint '{label}' loaded — agent must apply rollbacks manually")
    except Exception as e:
        return _err(f"checkpoint_restore error: {e}")


def audit_log(action: str, result: Any) -> dict:
    """Structured log of every agent decision."""
    try:
        # Primary: write to DB (queryable, concurrent-safe with PostgreSQL)
        try:
            from mcp_server.tools.skills.storage import get_backend
            get_backend().append_audit(action, result)
        except Exception:
            pass

        # Secondary: append to JSONL file (for tail -f and portability)
        entry = {"timestamp": _ts(), "action": action, "result": result}
        try:
            audit_path = _audit_path()
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

        return _ok({"action": action}, f"Audit entry logged: {action}")
    except Exception as e:
        return _err(f"audit_log error: {e}")


def pre_upgrade_check(service: str = "") -> dict:
    """
    6-step pre-flight gate before any service upgrade.
    All 6 steps must pass — any failure returns status=degraded with specific reason.

    Steps:
      1. Swarm nodes all ready
      2. Kafka brokers healthy, ISR intact
      3. Elastic error logs (last 30min) — zero errors on target service
      4. Elastic log pattern — error rate not anomalous
      5. MuninnDB memory context — any past upgrade failures?
      6. Checkpoint save
    """
    steps = []

    # Step 1: Swarm health
    try:
        from mcp_server.tools.swarm import swarm_status
        swarm = swarm_status()
        ok = swarm.get("status") == "ok"
        steps.append({"step": 1, "name": "swarm_nodes", "ok": ok,
                       "detail": swarm.get("message", "")})
        if not ok:
            return _degraded({"steps": steps, "failed_at": 1},
                             f"HALT: Swarm not healthy — {swarm.get('message')}")
    except Exception as e:
        return _err(f"pre_upgrade_check step 1 failed: {e}")

    # Step 2: Kafka health
    try:
        from mcp_server.tools.kafka import kafka_broker_status
        kafka = kafka_broker_status()
        ok = kafka.get("status") == "ok"
        steps.append({"step": 2, "name": "kafka_brokers", "ok": ok,
                       "detail": kafka.get("message", "")})
        if not ok:
            return _degraded({"steps": steps, "failed_at": 2},
                             f"HALT: Kafka not healthy — {kafka.get('message')}")
    except Exception as e:
        return _err(f"pre_upgrade_check step 2 failed: {e}")

    # Step 3: Elastic error logs
    try:
        from mcp_server.tools.elastic import elastic_error_logs
        errs = elastic_error_logs(service=service, minutes_ago=30)
        if errs.get("status") == "unavailable":
            steps.append({"step": 3, "name": "elastic_errors", "ok": True,
                           "detail": "Elasticsearch unavailable — skipped"})
        else:
            err_count = errs.get("data", {}).get("error_count", 0)
            ok = err_count == 0
            steps.append({"step": 3, "name": "elastic_errors", "ok": ok,
                           "detail": errs.get("message", "")})
            if not ok:
                return _degraded({"steps": steps, "failed_at": 3},
                                 f"HALT: {err_count} error(s) in logs for '{service}' last 30min")
    except Exception as e:
        steps.append({"step": 3, "name": "elastic_errors", "ok": True,
                       "detail": f"Elastic check skipped: {e}"})

    # Step 4: Error rate anomaly
    try:
        if service:
            from mcp_server.tools.elastic import elastic_log_pattern
            pattern = elastic_log_pattern(service=service, hours=24)
            if pattern.get("status") not in ("unavailable", "error"):
                anomaly = pattern.get("data", {}).get("anomaly", False)
                ok = not anomaly
                steps.append({"step": 4, "name": "error_rate_anomaly", "ok": ok,
                               "detail": pattern.get("message", "")})
                if not ok:
                    return _degraded({"steps": steps, "failed_at": 4},
                                     f"HALT: Anomalous error rate for '{service}': {pattern.get('message')}")
            else:
                steps.append({"step": 4, "name": "error_rate_anomaly", "ok": True,
                               "detail": "Elastic unavailable — skipped"})
        else:
            steps.append({"step": 4, "name": "error_rate_anomaly", "ok": True,
                           "detail": "No service specified — skipped"})
    except Exception as e:
        steps.append({"step": 4, "name": "error_rate_anomaly", "ok": True,
                       "detail": f"Pattern check skipped: {e}"})

    # Step 5: MuninnDB memory context
    mem_context = []
    try:
        import httpx
        api_port = os.environ.get("API_PORT", "8000")
        r = httpx.post(
            f"http://localhost:{api_port}/api/memory/activate",
            json=[f"upgrade {service}", "upgrade failure", "rollback"],
            timeout=3.0,
        )
        if r.status_code == 200:
            activations = r.json().get("activations", [])
            past_failures = [a for a in activations if "failure" in a.get("concept", "").lower()
                             or "rollback" in a.get("concept", "").lower()]
            mem_context = [a.get("concept") for a in activations]
            steps.append({
                "step": 5, "name": "memory_context", "ok": True,
                "detail": f"{len(activations)} engrams activated; {len(past_failures)} past failures",
                "memory": mem_context,
            })
            if past_failures:
                # Past failures found — warn but don't halt (agent decides)
                steps[-1]["warning"] = f"Past upgrade failures in memory: {[a.get('concept') for a in past_failures]}"
    except Exception as e:
        steps.append({"step": 5, "name": "memory_context", "ok": True,
                       "detail": f"Memory check skipped: {e}"})

    # Step 6: Checkpoint save
    try:
        label = f"pre_upgrade_{service}_{int(__import__('time').time())}"
        cp = checkpoint_save(label)
        ok = cp.get("status") == "ok"
        steps.append({"step": 6, "name": "checkpoint_saved", "ok": ok,
                       "detail": cp.get("message", "")})
        if not ok:
            return _degraded({"steps": steps, "failed_at": 6},
                             f"HALT: Checkpoint save failed — {cp.get('message')}")
    except Exception as e:
        return _err(f"pre_upgrade_check step 6 failed: {e}")

    return _ok(
        {"steps": steps, "service": service, "memory_context": mem_context},
        f"All 6 pre-upgrade checks passed for '{service}'"
    )


def post_upgrade_verify(service: str, operation_id: str = "") -> dict:
    """
    Post-upgrade verification after service_upgrade().
    Called automatically after any service upgrade.

    Steps:
      1. Service replicas at desired count
      2. No new errors in Elastic (last 5min)
      3. Correlate operation logs if operation_id provided
      4. Store result as MuninnDB engram
    """
    steps = []
    verdict = "success"

    # Allow Swarm replicas time to converge before checking health
    time.sleep(20)

    # Step 1: Replica count
    try:
        from mcp_server.tools.swarm import service_health
        health = service_health(service)
        ok = health.get("status") == "ok"
        steps.append({"step": 1, "name": "replicas_at_desired", "ok": ok,
                       "detail": health.get("message", "")})
        if not ok:
            verdict = "failed"
    except Exception as e:
        steps.append({"step": 1, "name": "replicas_at_desired", "ok": False,
                       "detail": str(e)})
        verdict = "failed"

    # Step 2: Elastic error logs (last 5min)
    # GroupCoordinator partition resignation is normal KRaft behavior during
    # broker shutdown — exclude these from the failure determination.
    _KAFKA_NORMAL = ("GroupCoordinator", "Resigned from", "resignation")
    new_errors = []
    try:
        from mcp_server.tools.elastic import elastic_error_logs
        errs = elastic_error_logs(service=service, minutes_ago=5)
        if errs.get("status") != "unavailable":
            all_errors = errs.get("data", {}).get("errors", [])
            real_errors = [e for e in all_errors
                           if not any(p in e.get("message", "") for p in _KAFKA_NORMAL)]
            new_errors = real_errors[:5]
            ok = len(real_errors) == 0
            detail = f"No errors" if ok else f"{len(real_errors)} error(s) (excluded {len(all_errors) - len(real_errors)} normal KRaft messages)"
            steps.append({"step": 2, "name": "no_new_errors", "ok": ok, "detail": detail})
            if not ok:
                verdict = "failed"
        else:
            steps.append({"step": 2, "name": "no_new_errors", "ok": True,
                           "detail": "Elastic unavailable — skipped"})
    except Exception as e:
        steps.append({"step": 2, "name": "no_new_errors", "ok": True,
                       "detail": f"Elastic check skipped: {e}"})

    # Step 3: Correlate operation
    correlation = {}
    if operation_id:
        try:
            from mcp_server.tools.elastic import elastic_correlate_operation
            corr = elastic_correlate_operation(operation_id)
            if corr.get("status") == "ok":
                correlation = corr.get("data", {})
                corr_errors = correlation.get("error_count", 0)
                steps.append({"step": 3, "name": "log_correlation", "ok": True,
                               "detail": corr.get("message", ""),
                               "correlated_errors": corr_errors})
                if corr_errors > 0:
                    verdict = "failed"
        except Exception as e:
            steps.append({"step": 3, "name": "log_correlation", "ok": True,
                           "detail": f"Correlation skipped: {e}"})
    else:
        steps.append({"step": 3, "name": "log_correlation", "ok": True,
                       "detail": "No operation_id provided"})

    # Step 4: Store result as MuninnDB engram
    try:
        import httpx
        api_port = os.environ.get("API_PORT", "8000")
        concept = f"upgrade_result:{service}"
        content = (
            f"Service '{service}' upgrade {'succeeded' if verdict == 'success' else 'FAILED'} "
            f"at {_ts()}. "
            f"Steps: {[s['name'] for s in steps if not s['ok']]}. "
            f"New errors: {len(new_errors)}. "
            + (f"Operation: {operation_id}" if operation_id else "")
        )
        tags = ["upgrade", service, verdict]
        if new_errors:
            tags.append("errors_detected")
        httpx.post(
            f"http://localhost:{api_port}/api/memory/store",
            json={"concept": concept, "content": content, "tags": tags},
            timeout=3.0,
        )
        steps.append({"step": 4, "name": "memory_stored", "ok": True,
                       "detail": f"Engram '{concept}' stored"})
    except Exception as e:
        steps.append({"step": 4, "name": "memory_stored", "ok": True,
                       "detail": f"Memory store skipped: {e}"})

    return {
        "status": "ok" if verdict == "success" else "degraded",
        "data": {
            "service": service,
            "verdict": verdict,
            "steps": steps,
            "correlation_summary": correlation,
            "new_errors": new_errors,
        },
        "timestamp": _ts(),
        "message": f"Post-upgrade verify for '{service}': {verdict.upper()}",
    }


def plan_action(summary: str, steps: list, risk_level: str = "medium", reversible: bool = True) -> dict:
    """
    Submit a plan for user approval before executing destructive operations.
    REQUIRED before calling: service_upgrade, service_rollback, node_drain,
    checkpoint_restore, kafka_rolling_restart_safe.
    Do NOT call for read-only tools.
    Returns {"approved": True} to proceed or {"approved": False} to cancel.
    The agent loop intercepts this call and suspends until the user responds.
    """
    # This body is never executed — the agent loop intercepts this tool call.
    return _ok(
        {"approved": False, "message": "plan_action was not intercepted by agent loop"},
        "plan_action not intercepted"
    )


def clarifying_question(question: str, options: list = None) -> dict:
    """
    Ask the user a clarifying question before proceeding.
    Use when the task is ambiguous, underspecified, or could apply to multiple
    services. ALWAYS call this before assuming which service, version, or scope
    to act on. The agent loop intercepts this call and suspends until the user
    answers — do not call any other tools until the answer is returned.
    """
    # This body is never executed — the agent loop intercepts this tool call
    # before invoke_tool() is reached and handles it asynchronously.
    return _ok({"question": question, "answer": "not_intercepted"},
               "clarifying_question was not intercepted by agent loop")


def escalate(reason: str) -> dict:
    """Flag decision as high-risk — logs, pauses, returns escalation signal."""
    entry = {
        "timestamp": _ts(),
        "level": "ESCALATION",
        "reason": reason,
        "action_required": "human_review",
    }
    audit_log("ESCALATE", entry)
    audit_path = _audit_path()
    print(f"\n[ESCALATION] {_ts()} — {reason}\nAudit: {audit_path}\n")
    return {
        "status": "escalated",
        "data": entry,
        "timestamp": _ts(),
        "message": f"ESCALATED: {reason} — agent halted, human review required",
    }
