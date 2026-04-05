"""Terraform — workspace listing, state parsing, and outputs (read-only)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


SKILL_META = {
    "name": "terraform_state",
    "description": "Read Terraform workspaces, state resources, and outputs from local state files.",
    "category": "compute",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "'workspaces' (default), 'state', or 'outputs'"},
            "workspace": {"type": "string", "description": "Workspace name (for action=state or outputs)"},
        },
        "required": [],
    },
    "auth_type": "none",
    "config_keys": ["TERRAFORM_DIR"],
    "compat": {
        "service": "terraform",
        "api_version_built_for": "1.7",
        "min_version": "0.12",
        "max_version": "",
        "version_endpoint": "",
        "version_field": "",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def execute(**kwargs) -> dict:
    action = kwargs.get("action", "workspaces")
    workspace = kwargs.get("workspace", "")

    tf_dir = os.environ.get("TERRAFORM_DIR", "")
    if not tf_dir:
        return _err("TERRAFORM_DIR not configured")

    tf_path = Path(tf_dir)
    if not tf_path.is_dir():
        return _err(f"Terraform directory not found: {tf_dir}")

    if action == "state":
        return _get_state(tf_path, workspace)
    elif action == "outputs":
        return _get_outputs(tf_path, workspace)
    return _list_workspaces(tf_path)


def _list_workspaces(tf_path: Path) -> dict:
    """List Terraform workspaces (directories with .tf files or terraform.tfstate)."""
    workspaces = []

    # Check root directory
    if _is_workspace(tf_path):
        workspaces.append({
            "name": "default",
            "path": str(tf_path),
            "has_state": (tf_path / "terraform.tfstate").exists(),
        })

    # Check subdirectories
    for d in sorted(tf_path.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and _is_workspace(d):
            workspaces.append({
                "name": d.name,
                "path": str(d),
                "has_state": (d / "terraform.tfstate").exists(),
            })

    # Check terraform.tfstate.d/ for named workspaces
    ws_dir = tf_path / "terraform.tfstate.d"
    if ws_dir.is_dir():
        for d in sorted(ws_dir.iterdir()):
            if d.is_dir():
                workspaces.append({
                    "name": d.name,
                    "path": str(d),
                    "has_state": (d / "terraform.tfstate").exists(),
                })

    return _ok({"workspaces": workspaces, "count": len(workspaces)},
               f"Terraform: {len(workspaces)} workspace(s)")


def _is_workspace(path: Path) -> bool:
    """Check if a directory contains Terraform files."""
    return any(path.glob("*.tf")) or (path / "terraform.tfstate").exists()


def _find_state_file(tf_path: Path, workspace: str) -> Path | None:
    """Find the state file for a workspace."""
    if not workspace or workspace == "default":
        f = tf_path / "terraform.tfstate"
        if f.exists():
            return f
        return None

    # Check subdirectory
    sub = tf_path / workspace / "terraform.tfstate"
    if sub.exists():
        return sub

    # Check terraform.tfstate.d/
    ws = tf_path / "terraform.tfstate.d" / workspace / "terraform.tfstate"
    if ws.exists():
        return ws

    return None


def _get_state(tf_path: Path, workspace: str) -> dict:
    """Parse terraform.tfstate and list resources."""
    state_file = _find_state_file(tf_path, workspace or "default")
    if not state_file:
        return _err(f"No state file found for workspace '{workspace or 'default'}'")

    try:
        state = json.loads(state_file.read_text())
    except Exception as e:
        return _err(f"Failed to parse state file: {e}")

    version = state.get("terraform_version", "")
    resources = []

    for r in state.get("resources", []):
        res_type = r.get("type", "")
        res_name = r.get("name", "")
        provider = r.get("provider", "")
        mode = r.get("mode", "managed")
        instances = len(r.get("instances", []))
        resources.append({
            "type": res_type,
            "name": res_name,
            "provider": provider.split("/")[-1].rstrip('"') if "/" in provider else provider,
            "mode": mode,
            "instances": instances,
        })

    return _ok({
        "workspace": workspace or "default",
        "terraform_version": version,
        "resources": resources,
        "resource_count": len(resources),
    }, f"Terraform '{workspace or 'default'}': {len(resources)} resource(s)")


def _get_outputs(tf_path: Path, workspace: str) -> dict:
    """Read outputs from terraform.tfstate."""
    state_file = _find_state_file(tf_path, workspace or "default")
    if not state_file:
        return _err(f"No state file found for workspace '{workspace or 'default'}'")

    try:
        state = json.loads(state_file.read_text())
    except Exception as e:
        return _err(f"Failed to parse state file: {e}")

    outputs = {}
    for name, val in state.get("outputs", {}).items():
        # Don't expose sensitive outputs
        if val.get("sensitive", False):
            outputs[name] = {"value": "***sensitive***", "type": val.get("type", "")}
        else:
            outputs[name] = {"value": val.get("value"), "type": val.get("type", "")}

    return _ok({
        "workspace": workspace or "default",
        "outputs": outputs,
        "count": len(outputs),
    }, f"Terraform '{workspace or 'default'}': {len(outputs)} output(s)")


def check_compat(**kwargs) -> dict:
    tf_dir = os.environ.get("TERRAFORM_DIR", "")
    if not tf_dir:
        return _ok({"compatible": None, "detected_version": None, "reason": "TERRAFORM_DIR not configured"})
    if not Path(tf_dir).is_dir():
        return _ok({"compatible": None, "detected_version": None, "reason": f"Directory not found: {tf_dir}"})
    # Try to read version from any state file
    for sf in Path(tf_dir).rglob("terraform.tfstate"):
        try:
            state = json.loads(sf.read_text())
            version = state.get("terraform_version", "")
            if version:
                return _ok({"compatible": True, "detected_version": version, "reason": f"Terraform {version}"})
        except Exception:
            continue
    return _ok({"compatible": None, "detected_version": None, "reason": "No state files found"})
