# CC PROMPT — v2.13.0 — Skill system: spec-first generation + environment discovery

## What this does

The current skill generator goes: description → LLM → code.
The LLM hallucinates API endpoints, invents parameters, guesses auth flows.

This implements the spec-first pattern from HP1_IMPROVEMENTS.md:
description → SKILL_SPEC (small structured JSON) → validate spec against live API → code from validated spec.

Also adds `discover_environment()` — a 4-phase pipeline that fingerprints services
on the network automatically from connection records.

Version bump: 2.12.1 → 2.13.0 (major skill system redesign, x.1.x)

---

## Change 1 — mcp_server/tools/skills/modules/spec_generator.py (NEW FILE)

```python
"""Skill spec generator — produces SKILL_SPEC before code generation.

Phase 1 of spec-first skill creation:
  description → LLM → SKILL_SPEC → validate → (pass to code generator)

SKILL_SPEC is a small structured dict that captures the API contract:
endpoints, auth, expected fields, error conditions. The LLM generates this
from the description. The spec is then validated against the live service
BEFORE code generation — so the code generator has verified facts, not guesses.
"""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SKILL_SPEC_SCHEMA = {
    "name":        str,    # snake_case tool name
    "service":     str,    # platform (fortigate, truenas, unifi, etc.)
    "description": str,    # one-sentence description
    "endpoints": [         # list of API endpoints the skill calls
        {
            "method":           str,   # GET, POST, etc.
            "path":             str,   # /api/v2/monitor/system/status
            "auth":             str,   # apikey_query | bearer | basic | pve_token | none
            "expected_status":  int,   # 200
            "response_fields": [str],  # ["serial", "version", "status"]
        }
    ],
    "parameters": dict,    # JSONSchema parameters block
    "health_rules": {
        "ok":      str,    # condition for green
        "degraded": str,   # condition for amber
        "error":   str,    # condition for red
    },
    "config_keys": [str],  # env var names needed (e.g. ["FORTIGATE_HOST", "FORTIGATE_API_KEY"])
}


def generate_spec_prompt(description: str, service: str, sample_response: str = "") -> str:
    """Build the LLM prompt for spec generation."""
    schema_str = json.dumps(SKILL_SPEC_SCHEMA, indent=2, default=str)
    return f"""Generate a SKILL_SPEC JSON object for this infrastructure monitoring skill.

Service: {service}
Description: {description}
{f'Sample API response: {sample_response[:500]}' if sample_response else ''}

Output ONLY valid JSON matching this schema (no prose, no markdown):
{schema_str}

Rules:
- name: snake_case, descriptive (e.g. fortigate_ha_status)
- endpoints: list every API call the skill makes
- response_fields: the actual field names from the API response
- auth: one of apikey_query, bearer, basic, pve_token, apikey_header, none
- health_rules: concrete conditions, not vague ("status == 'active'" not "status is ok")
- config_keys: what the skill reads from the connection credentials dict

Output only the JSON object. Nothing else."""


def generate_spec(
    description: str,
    service: str,
    lm_client,
    model: str,
    sample_response: str = "",
) -> dict:
    """Call the LLM to generate a SKILL_SPEC. Returns parsed dict or raises."""
    prompt = generate_spec_prompt(description, service, sample_response)
    response = lm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt + "\n/no_think"}],
        tools=None,
        temperature=0.1,
        max_tokens=800,
    )
    text = response.choices[0].message.content or ""
    # Strip markdown fences
    text = text.strip().strip("```json").strip("```").strip()
    spec = json.loads(text)
    # Basic validation
    for required in ("name", "service", "endpoints", "parameters"):
        if required not in spec:
            raise ValueError(f"SKILL_SPEC missing required field: {required!r}")
    return spec
```

---

## Change 2 — mcp_server/tools/skills/modules/live_validator.py (NEW FILE)

```python
"""Live validator — probes actual service endpoints from a SKILL_SPEC.

Phase 2 of spec-first skill creation:
  SKILL_SPEC → probe each endpoint → verify response fields exist → validated spec

If validation passes, the spec contains verified facts.
Code generation from a verified spec is nearly deterministic.
"""
import json
import logging
import time

import httpx

log = logging.getLogger(__name__)


def validate_spec(spec: dict, connection: dict) -> dict:
    """Probe each endpoint in the spec against the live service.

    Returns validation result:
      {
        "valid": bool,
        "endpoints_checked": int,
        "failures": [{"endpoint": ..., "reason": ...}],
        "sample_responses": {"path": response_snippet},
      }
    """
    host = connection.get("host", "")
    port = connection.get("port", 443)
    creds = connection.get("credentials", {})
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except Exception: creds = {}

    failures = []
    samples = {}
    checked = 0

    for ep in spec.get("endpoints", []):
        method = ep.get("method", "GET").upper()
        path   = ep.get("path", "/")
        auth   = ep.get("auth", "none")
        expected_status = ep.get("expected_status", 200)
        expected_fields = ep.get("response_fields", [])

        # Determine scheme from port
        scheme = "https" if port in (443, 8443, 8006, 8007, 9443) else "http"
        url = f"{scheme}://{host}:{port}{path}"

        headers = {}
        params = {}

        if auth == "apikey_query":
            key = creds.get("api_key", "")
            if key: params["access_token"] = key
        elif auth == "bearer":
            key = creds.get("api_key", "")
            if key: headers["Authorization"] = f"Bearer {key}"
        elif auth == "basic":
            import base64
            user = creds.get("username", "")
            pw   = creds.get("password", "")
            if user:
                b64 = base64.b64encode(f"{user}:{pw}".encode()).decode()
                headers["Authorization"] = f"Basic {b64}"
        elif auth == "pve_token":
            user = creds.get("user", "")
            tn   = creds.get("token_name", "")
            sec  = creds.get("secret", "")
            if user and tn and sec:
                headers["Authorization"] = f"PVEAPIToken={user}!{tn}={sec}"
        elif auth == "apikey_header":
            key = creds.get("api_key", "")
            if key: headers["X-API-Key"] = key

        try:
            r = httpx.request(method, url, headers=headers, params=params,
                              verify=False, timeout=8)
            checked += 1

            if r.status_code != expected_status:
                failures.append({
                    "endpoint": path,
                    "reason": f"Expected HTTP {expected_status}, got {r.status_code}",
                })
                continue

            # Check response fields
            try:
                body = r.json()
                # Handle {data: [...]} wrapper common in Proxmox/PBS
                data = body.get("data", body) if isinstance(body, dict) else body
                if isinstance(data, list) and data:
                    data = data[0]

                missing = [f for f in expected_fields
                           if isinstance(data, dict) and f not in data]
                if missing:
                    failures.append({
                        "endpoint": path,
                        "reason": f"Missing expected fields: {missing}",
                    })

                # Store sample for code generator
                samples[path] = json.dumps(data, default=str)[:400]
            except Exception:
                # Non-JSON response — not necessarily a failure
                samples[path] = r.text[:200]

        except Exception as e:
            checked += 1
            failures.append({"endpoint": path, "reason": str(e)[:120]})

    return {
        "valid": len(failures) == 0,
        "endpoints_checked": checked,
        "failures": failures,
        "sample_responses": samples,
    }
```

---

## Change 3 — mcp_server/tools/skills/modules/fingerprints.py (NEW FILE)

```python
"""Service fingerprints — identify services by probing known API paths."""
import httpx

SERVICE_FINGERPRINTS = {
    "proxmox":       {"paths": ["/api2/json/version"],          "fields": ["repoid", "version"],          "port": 8006},
    "pbs":           {"paths": ["/api2/json/version"],          "fields": ["repoid", "version"],          "port": 8007},
    "fortigate":     {"paths": ["/api/v2/monitor/system/status"], "fields": ["serial", "version"],        "port": 443},
    "truenas":       {"paths": ["/api/v2.0/system/version"],    "fields": ["TrueNAS"],                    "port": 443},
    "synology":      {"paths": ["/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query"], "fields": ["SYNO."], "port": 5001},
    "unifi":         {"paths": ["/api/s/default/stat/health"],  "fields": ["subsystem"],                  "port": 8443},
    "opnsense":      {"paths": ["/api/core/firmware/status"],   "fields": ["product_version"],            "port": 443},
    "docker":        {"paths": ["/version"],                    "fields": ["ApiVersion"],                 "port": 2375, "scheme": "http"},
    "elasticsearch": {"paths": ["/_cluster/health"],            "fields": ["cluster_name"],               "port": 9200, "scheme": "http"},
    "pihole":        {"paths": ["/admin/api.php?summary"],      "fields": ["domains_being_blocked"],      "port": 80, "scheme": "http"},
    "grafana":       {"paths": ["/api/health"],                 "fields": ["database"],                   "port": 3000, "scheme": "http"},
    "portainer":     {"paths": ["/api/status"],                 "fields": ["Version"],                    "port": 9443},
    "adguard":       {"paths": ["/control/status"],             "fields": ["dns_addresses"],              "port": 3000, "scheme": "http"},
    "technitium":    {"paths": ["/api/user/session/get"],       "fields": ["status"],                     "port": 5380, "scheme": "http"},
}


def fingerprint_host(address: str, port: int = None) -> dict:
    """Try all fingerprints against a host. Returns first match or None.

    Args:
        address: IP or hostname
        port:    Override port (if None, tries each fingerprint's default)

    Returns: {"service": "proxmox", "version": "8.1", "port": 8006} or None
    """
    for service, fp in SERVICE_FINGERPRINTS.items():
        try_port = port or fp.get("port", 443)
        scheme = fp.get("scheme", "https")
        for path in fp["paths"]:
            url = f"{scheme}://{address}:{try_port}{path}"
            try:
                r = httpx.get(url, verify=False, timeout=4, follow_redirects=True)
                if r.status_code >= 500:
                    continue
                text = r.text
                # Check if any fingerprint field appears in response
                if any(field in text for field in fp["fields"]):
                    version = None
                    try:
                        data = r.json()
                        version = (data.get("data", {}).get("version") or
                                   data.get("version") or
                                   data.get("Release"))
                    except Exception:
                        pass
                    return {
                        "service": service,
                        "version": str(version) if version else "unknown",
                        "port": try_port,
                        "scheme": scheme,
                        "fingerprint_path": path,
                    }
            except Exception:
                continue
    return None
```

---

## Change 4 — mcp_server/tools/meta_tools.py — add discover_environment

Add `discover_environment` tool that uses fingerprints + connection DB:

```python
def discover_environment() -> dict:
    """Scan all registered connections and identify service types.

    Phase 1: enumerate all registered connections from the DB.
    Phase 2: fingerprint each host to confirm service type and version.
    Phase 3: check which services have existing skill coverage.
    Phase 4: recommend skills to create for uncovered services.

    Returns structured report: identified services, skill gaps, recommendations.
    This runs deterministically — no LLM calls. Results are facts, not guesses.
    """
    try:
        from api.connections import list_connections
        from mcp_server.tools.skills.modules.fingerprints import fingerprint_host
        from mcp_server.tools.skills.registry import list_skills

        all_conns = list_connections()
        existing_skills = {s["name"] for s in list_skills(enabled_only=True)}

        identified = []
        no_skill = []

        for conn in all_conns:
            host = conn.get("host", "")
            platform = conn.get("platform", "")
            label = conn.get("label", host)
            if not host:
                continue

            # Try fingerprint to confirm and get version
            fp = fingerprint_host(host, conn.get("port"))
            service = fp["service"] if fp else platform
            version = fp.get("version", "unknown") if fp else "unknown"

            # Check skill coverage
            skill_names = [s for s in existing_skills
                           if service in s or platform in s]

            entry = {
                "label":       label,
                "host":        host,
                "platform":    platform,
                "detected_service": service,
                "version":     version,
                "skills":      skill_names,
                "covered":     len(skill_names) > 0,
            }
            identified.append(entry)
            if not skill_names:
                no_skill.append(entry)

        # Recommendations for uncovered services
        recommendations = []
        for svc in no_skill:
            recommendations.append({
                "service":    svc["detected_service"],
                "host":       svc["host"],
                "label":      svc["label"],
                "suggested_skill": f"{svc['detected_service']}_status",
                "description": (
                    f"Check {svc['label']} ({svc['detected_service']} v{svc['version']}) "
                    f"status and health metrics"
                ),
            })

        return {
            "status": "ok",
            "message": (
                f"Discovered {len(identified)} services: "
                f"{len(identified) - len(no_skill)} covered, {len(no_skill)} need skills"
            ),
            "data": {
                "services":        identified,
                "uncovered":       no_skill,
                "recommendations": recommendations,
                "skill_count":     len(existing_skills),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
```

Add `discover_environment` to `BUILD_AGENT_TOOLS` in `api/agents/router.py`.

---

## Change 5 — Update skill_create to use spec-first flow

In the existing skill_create handler (in meta_tools.py or wherever it lives),
wrap the generation with the spec-first flow:

```python
# 1. Generate spec
spec = generate_spec(description, service, lm_client, model)

# 2. Get connection for the service to validate against
from api.connections import get_connection_for_platform
conn = get_connection_for_platform(service)

# 3. Validate spec against live service (if connection available)
validation = None
if conn:
    from mcp_server.tools.skills.modules.live_validator import validate_spec
    validation = validate_spec(spec, conn)
    if not validation["valid"]:
        return {
            "status": "error",
            "message": f"Spec validation failed: {validation['failures']}",
            "data": {"spec": spec, "validation": validation},
        }
    # Enrich spec with sample responses for better code generation
    spec["_sample_responses"] = validation.get("sample_responses", {})

# 4. Generate code from validated spec
code = generate_code_from_spec(spec, lm_client, model)
```

---

## Version bump

Update VERSION: `2.12.1` → `2.13.0`

---

## Commit

```bash
git add -A
git commit -m "feat(skills): v2.13.0 spec-first generation + environment discovery

- spec_generator.py: description → SKILL_SPEC JSON before code generation
- live_validator.py: probes actual service endpoints to verify spec is correct
- fingerprints.py: 12-service fingerprint DB for deterministic identification
- discover_environment(): 4-phase pipeline — enumerate, fingerprint, catalog, recommend
- skill_create: now spec → validate → code (max 2 LLM calls, verified facts)
- discover_environment added to BUILD_AGENT_TOOLS"
git push origin main
```
