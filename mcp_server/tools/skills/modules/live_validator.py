"""Live validator — probes actual service endpoints from a SKILL_SPEC.

Phase 2 of spec-first skill creation:
  SKILL_SPEC → probe each endpoint → verify response fields exist → validated spec

If validation passes, the spec contains verified facts.
Code generation from a verified spec is nearly deterministic.
"""
import json
import logging

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
