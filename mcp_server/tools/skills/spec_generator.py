"""Two-phase skill generation: description → SKILL_SPEC → live validation → code.

Phase 1: LLM generates a small, structured SKILL_SPEC JSON (no code).
Phase 2: SKILL_SPEC is validated against the live service via actual HTTP probes.
         Code generation only happens after the spec is validated.

This eliminates hallucinated endpoints and wrong auth patterns before any code is written.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 8.0


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


_SPEC_SYSTEM_PROMPT = """\
You are a skill spec generator for a homelab infrastructure agent.

Given a description of a skill, generate a SKILL_SPEC JSON object.
The spec describes WHAT the skill does — which API endpoints to call, what auth to use,
which response fields to check, and what health rules to apply.

Output ONLY a valid JSON object with this exact schema:
{
  "name": "snake_case_skill_name_max_4_words",
  "service": "service_name_lowercase",
  "description": "One-line description of what the skill checks or does",
  "endpoints": [
    {
      "method": "GET",
      "path": "/api/exact/path",
      "auth": "query_param:access_token | bearer | api_key_header:X-Auth-Token | basic | none",
      "expected_status": 200,
      "response_fields": ["field1", "field2"],
      "optional_fields": ["opt1"]
    }
  ],
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  },
  "config_keys": ["SERVICE_HOST", "SERVICE_API_KEY"],
  "health_rules": {
    "ok": "human-readable condition string for healthy state",
    "degraded": "human-readable condition string for degraded state",
    "error": "connection failed or HTTP status not 200"
  }
}

Rules:
- name: snake_case, max 4 words, descriptive
- auth: must be one of: query_param:<param>, bearer, api_key_header:<header>, basic, none
- response_fields: fields that MUST be present in the response for the skill to be useful
- config_keys: env var names the skill will read (SERVICE_HOST, SERVICE_API_KEY, etc.)
- Output ONLY the JSON object. No explanation. No markdown fences.
"""


def generate_spec(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:
    """Phase 1: Generate a SKILL_SPEC from a description via LLM.

    Returns: {"status": "ok", "data": {"spec": {...}}, ...}
    """
    from mcp_server.tools.skills.generator import _get_backend_config

    if not backend:
        cfg = _get_backend_config()
        backend = cfg["backend"]

    # Fetch docs for context (lightweight budget — spec only needs key facts)
    doc_context = ""
    try:
        from mcp_server.tools.skills.doc_retrieval import fetch_relevant_docs, format_docs_for_prompt
        docs = fetch_relevant_docs(description, category=category, api_base=api_base, token_budget=1500)
        doc_context = format_docs_for_prompt(docs)
    except Exception as e:
        log.debug("doc_retrieval for spec: %s", e)

    user_msg = f"Generate a SKILL_SPEC for: {description}"
    if api_base:
        user_msg += f"\nAPI base URL: {api_base}"
    if auth_type and auth_type != "none":
        user_msg += f"\nAuth type hint: {auth_type}"
    if doc_context:
        user_msg += f"\n\nDocumentation context:\n{doc_context}"

    try:
        if backend == "cloud":
            raw = _call_cloud(user_msg)
        elif backend == "export":
            return _err("Spec generation not available in export mode")
        else:
            raw = _call_local(user_msg)
    except Exception as e:
        return _err(f"Spec generation failed ({backend}): {e}")

    spec = _extract_json(raw)
    if spec is None:
        return _err("Failed to parse SKILL_SPEC from LLM output", data={"raw": raw[:500]})

    missing = [k for k in ("name", "service", "description", "endpoints") if k not in spec]
    if missing:
        return _err(f"SKILL_SPEC missing required keys: {missing}", data={"spec": spec})

    if not spec.get("endpoints"):
        return _err("SKILL_SPEC has no endpoints defined", data={"spec": spec})

    # Normalize name
    spec["name"] = re.sub(r"[^a-z0-9_]", "", spec["name"].lower().replace("-", "_").replace(" ", "_"))

    return _ok({"spec": spec}, f"Spec generated for '{spec.get('name', 'unknown')}'")


def validate_spec_live(spec: dict, api_base: str) -> dict:
    """Phase 2: Probe actual service endpoints defined in spec.

    Checks:
    - Does the endpoint return the expected status code (or 401/403 auth-gate)?
    - Do the expected response_fields exist in a 200 response?
    - Is the service reachable at api_base?

    Returns: {"status": "ok", "data": {"valid": bool, "errors": [...], "warnings": [...], ...}}
    """
    if not api_base:
        return _ok({
            "valid": True,
            "skipped": True,
            "errors": [],
            "warnings": ["No api_base provided — live validation skipped"],
            "probe_results": [],
        }, "Live validation skipped (no api_base)")

    errors = []
    warnings = []
    probe_results = []

    for ep in spec.get("endpoints", []):
        path = ep.get("path", "")
        method = ep.get("method", "GET").upper()
        expected_status = ep.get("expected_status", 200)
        response_fields = ep.get("response_fields", [])
        auth = ep.get("auth", "none")

        url = f"{api_base.rstrip('/')}{path}"
        headers = {}
        params = {}

        # Build auth tokens (probe tokens — expect 401, not 404, which proves endpoint exists)
        if auth.startswith("query_param:"):
            params[auth.split(":", 1)[1]] = "probe_test_token"
        elif auth == "bearer":
            headers["Authorization"] = "Bearer probe_test_token"
        elif auth.startswith("api_key_header:"):
            headers[auth.split(":", 1)[1]] = "probe_test_token"
        elif auth == "basic":
            headers["Authorization"] = "Basic cHJvYmU6dGVzdA=="  # probe:test

        probe = {"path": path, "url": url, "method": method}

        try:
            r = httpx.request(
                method, url,
                headers=headers,
                params=params,
                timeout=_PROBE_TIMEOUT,
                verify=False,
                follow_redirects=True,
            )
            probe["status_code"] = r.status_code
            # 401/403 = endpoint exists but auth required (expected for probe tokens)
            endpoint_exists = r.status_code in (expected_status, 401, 403)
            probe["endpoint_exists"] = endpoint_exists

            if not endpoint_exists:
                errors.append(
                    f"Endpoint {path} returned HTTP {r.status_code} "
                    f"(expected {expected_status} or 401/403 auth-gate)"
                )

            # Validate response fields only if we got a real 200
            fields_found = []
            fields_missing = []
            if r.status_code == 200 and response_fields:
                try:
                    data = r.json()
                    # Flatten one level of nesting for field scanning
                    flat: dict = {}
                    if isinstance(data, dict):
                        flat = data
                        for v in data.values():
                            if isinstance(v, dict):
                                flat.update(v)
                            elif isinstance(v, list) and v and isinstance(v[0], dict):
                                flat.update(v[0])
                    for field in response_fields:
                        if field in flat:
                            fields_found.append(field)
                        else:
                            fields_missing.append(field)
                    if fields_missing:
                        warnings.append(
                            f"Endpoint {path}: response missing expected fields: {fields_missing}"
                        )
                except Exception:
                    warnings.append(f"Endpoint {path}: non-JSON response (or parse error)")

            probe["fields_found"] = fields_found
            probe["fields_missing"] = fields_missing

        except httpx.ConnectError:
            errors.append(f"Cannot connect to {url} — check address and port")
            probe["error"] = "connection_refused"
        except httpx.TimeoutException:
            warnings.append(f"Endpoint {path} timed out after {_PROBE_TIMEOUT}s")
            probe["error"] = "timeout"
        except Exception as e:
            warnings.append(f"Endpoint {path} probe error: {e}")
            probe["error"] = str(e)

        probe_results.append(probe)

    valid = len(errors) == 0
    return _ok({
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "probe_results": probe_results,
    }, "Spec validated against live service" if valid else f"Spec validation failed: {errors[0]}")


# ── LLM call helpers ──────────────────────────────────────────────────────────

def _call_local(user_msg: str) -> str:
    """Call LM Studio for spec generation."""
    from mcp_server.tools.skills.generator import _get_backend_config
    cfg = _get_backend_config()
    base_url = cfg["lm_studio_base_url"]
    api_key = cfg["lm_studio_api_key"]
    model = cfg.get("lm_studio_model", "")

    if not model:
        try:
            r = httpx.get(f"{base_url}/models", timeout=5.0)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    model = models[0].get("id", "")
        except Exception:
            pass
    if not model:
        model = "default"

    r = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": _SPEC_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        },
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _call_cloud(user_msg: str) -> str:
    """Call Anthropic Claude for spec generation."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic>=0.50.0")

    from mcp_server.tools.skills.generator import _get_backend_config
    cfg = _get_backend_config()
    api_key = cfg["anthropic_api_key"]
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=_SPEC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return msg.content[0].text


def _extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from LLM output, handling markdown fences."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object by brace matching
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
