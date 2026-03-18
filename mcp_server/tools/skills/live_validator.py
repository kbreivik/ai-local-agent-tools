"""3-layer skill validation.

Layer 1  DETERMINISTIC  — AST + contract checks (fast, no LLM, always runs)
Layer 2  LIVE PROBE     — endpoint probing via skill spec (medium, no LLM)
Layer 3  CRITIC         — LLM code review (slow, optional, only blocks on severity=error)
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def validate_skill_live(name: str, spec: Optional[dict] = None) -> dict:
    """Full 3-layer validation of a loaded skill.

    spec: optional SKILL_SPEC dict from spec_generator (enables Layer 2 probing).
          If not provided, Layer 2 falls back to version_endpoint from SKILL_META.compat.
    """
    import os
    from mcp_server.tools.skills import registry
    from mcp_server.tools.skills import loader

    modules_dir = os.path.join(os.path.dirname(loader.__file__), "modules")
    filepath = os.path.join(modules_dir, f"{name}.py")

    if not os.path.exists(filepath):
        return _err(f"Skill file not found: {name}.py")

    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()

    skill_info = registry.get_skill(name)
    layers: dict = {}

    # ── Layer 1: Deterministic ────────────────────────────────────────────────
    l1 = _layer1_deterministic(code)
    layers["layer1_deterministic"] = l1

    if not l1["passed"]:
        return _ok({
            "name": name,
            "overall_valid": False,
            "layers": layers,
            "blocking_layer": 1,
        }, f"Layer 1 failed: {l1['errors'][0] if l1['errors'] else 'validation error'}")

    # ── Layer 2: Live probe ───────────────────────────────────────────────────
    api_base = _resolve_api_base(spec, skill_info)

    if spec and api_base:
        l2 = _layer2_spec_probe(spec, api_base)
    elif api_base:
        l2 = _layer2_version_probe(skill_info, api_base)
    else:
        l2 = {"passed": None, "skipped": True, "reason": "No api_base available for live probing"}

    layers["layer2_live_probe"] = l2

    if l2.get("passed") is False:
        return _ok({
            "name": name,
            "overall_valid": False,
            "layers": layers,
            "blocking_layer": 2,
        }, f"Layer 2 failed: {l2['errors'][0] if l2.get('errors') else 'live probe failed'}")

    # ── Layer 3: LLM critic ───────────────────────────────────────────────────
    l3 = _layer3_critic(code, spec)
    layers["layer3_critic"] = l3

    l3_errors = [i for i in l3.get("issues", []) if i.get("severity") == "error"]
    l3_warnings = [i for i in l3.get("issues", []) if i.get("severity") == "warning"]

    overall_valid = (
        l1["passed"]
        and l2.get("passed") is not False
        and len(l3_errors) == 0
    )

    return _ok({
        "name": name,
        "overall_valid": overall_valid,
        "layers": layers,
        "summary": {
            "l1_passed": l1["passed"],
            "l1_warnings": len(l1.get("warnings", [])),
            "l2_passed": l2.get("passed"),
            "l2_skipped": l2.get("skipped", False),
            "l3_errors": len(l3_errors),
            "l3_warnings": len(l3_warnings),
            "l3_skipped": l3.get("skipped", False),
        },
    }, "All validation layers passed" if overall_valid else f"Validation failed ({len(l3_errors)} error(s))")


# ── Layer 1 ───────────────────────────────────────────────────────────────────

def _layer1_deterministic(code: str) -> dict:
    """AST + contract checks. Fast. No LLM."""
    import ast
    from mcp_server.tools.skills import validator

    errors: list = []
    warnings: list = []

    # Existing validator (syntax, SKILL_META, execute(), banned imports/calls)
    result = validator.validate_skill_code(code)
    if not result["valid"]:
        return {"passed": False, "errors": [result["error"]], "warnings": []}

    meta = result.get("meta", {})

    # Additional: ensure execute() has at least one return statement
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "execute":
                returns = [n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value]
                if not returns:
                    errors.append("execute() has no return statement with a value")
    except SyntaxError as e:
        errors.append(f"AST error: {e}")

    # Soft warnings
    if not meta.get("config_keys"):
        warnings.append("SKILL_META missing config_keys — credential errors will be silent")
    if not meta.get("compat"):
        warnings.append("SKILL_META missing compat section — version tracking disabled")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "skill_name": meta.get("name", ""),
    }


# ── Layer 2 ───────────────────────────────────────────────────────────────────

def _layer2_spec_probe(spec: dict, api_base: str) -> dict:
    """Full spec probe: check every endpoint in SKILL_SPEC."""
    from mcp_server.tools.skills.spec_generator import validate_spec_live
    result = validate_spec_live(spec, api_base)
    data = result.get("data", {})
    return {
        "passed": data.get("valid", False),
        "errors": data.get("errors", []),
        "warnings": data.get("warnings", []),
        "probe_results": data.get("probe_results", []),
    }


def _layer2_version_probe(skill_info: Optional[dict], api_base: str) -> dict:
    """Lightweight probe: hit the version_endpoint from SKILL_META.compat."""
    import httpx

    compat = (skill_info or {}).get("compat") or {}
    version_ep = compat.get("version_endpoint", "")

    if not version_ep:
        return {"passed": None, "skipped": True, "reason": "No version_endpoint in compat metadata"}

    url = f"{api_base.rstrip('/')}{version_ep}"
    try:
        r = httpx.get(url, timeout=8.0, verify=False, follow_redirects=True)
        reachable = r.status_code in (200, 401, 403)
        return {
            "passed": reachable,
            "errors": [] if reachable else [f"Version endpoint {version_ep} returned HTTP {r.status_code}"],
            "warnings": [],
            "probe_results": [{"url": url, "status_code": r.status_code}],
        }
    except Exception as e:
        return {
            "passed": False,
            "errors": [f"Cannot reach version endpoint {url}: {e}"],
            "warnings": [],
            "probe_results": [{"url": url, "error": str(e)}],
        }


# ── Layer 3 ───────────────────────────────────────────────────────────────────

def _layer3_critic(code: str, spec: Optional[dict] = None) -> dict:
    """LLM critic review. Optional — skipped if LM Studio is unavailable.
    Only severity=error issues block registration; warnings are logged only.
    """
    import httpx
    from mcp_server.tools.skills.generator import _get_backend_config

    cfg = _get_backend_config()
    base_url = cfg["lm_studio_base_url"]

    try:
        r = httpx.get(f"{base_url}/models", timeout=3.0)
        if r.status_code != 200:
            return {"skipped": True, "reason": "LM Studio not available", "issues": []}
        models = r.json().get("data", [])
        if not models:
            return {"skipped": True, "reason": "No models loaded in LM Studio", "issues": []}
        model = models[0]["id"]
    except Exception:
        return {"skipped": True, "reason": "LM Studio unreachable", "issues": []}

    spec_section = ""
    if spec:
        spec_section = f"\n\nSKILL_SPEC (the spec this code should implement):\n```json\n{json.dumps(spec, indent=2)}\n```"

    critic_prompt = (
        "You are a strict code reviewer for a homelab infrastructure skill system.\n"
        "Review the skill module below for: correctness, security, API contract adherence, "
        "and error handling quality.\n"
        "Return a JSON array of issues. Each issue: "
        '{"issue": "description", "severity": "error|warning", "fix": "how to fix it"}\n'
        "Return [] if no issues found.\n"
        "Output ONLY the JSON array — no markdown fences, no explanation."
        f"{spec_section}\n\n"
        f"SKILL CODE:\n```python\n{code[:4000]}\n```"
    )

    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['lm_studio_api_key']}"},
            json={
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": "You are a strict code reviewer. Output only valid JSON arrays."},
                    {"role": "user", "content": critic_prompt},
                ],
            },
            timeout=90.0,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"skipped": True, "reason": f"LM Studio call failed: {e}", "issues": []}

    # Strip fences and parse
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"^```\s*$", "", raw, flags=re.MULTILINE).strip()

    # Find JSON array
    start = raw.find("[")
    if start != -1:
        try:
            issues = json.loads(raw[start:])
            if isinstance(issues, list):
                return {"skipped": False, "issues": issues}
        except json.JSONDecodeError:
            pass

    return {"skipped": False, "issues": [], "parse_warning": "Could not parse critic output"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_api_base(spec: Optional[dict], skill_info: Optional[dict]) -> str:
    """Resolve api_base from spec, skill_info, or service_catalog."""
    if spec and spec.get("api_base"):
        return spec["api_base"]

    compat = (skill_info or {}).get("compat") or {}
    service = compat.get("service", "")
    if service:
        try:
            from mcp_server.tools.skills import registry
            svc = registry.get_service(service)
            if svc and svc.get("api_base"):
                return svc["api_base"]
        except Exception:
            pass
    return ""
