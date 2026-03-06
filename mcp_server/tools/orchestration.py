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
        entry = {
            "timestamp": _ts(),
            "action": action,
            "result": result,
        }
        audit_path = _audit_path()
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return _ok({"action": action}, f"Audit entry logged: {action}")
    except Exception as e:
        return _err(f"audit_log error: {e}")


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
