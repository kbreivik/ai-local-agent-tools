"""Perform an HTTP GET health check on any URL with response timing."""
import httpx
from datetime import datetime, timezone


SKILL_META = {
    "name": "http_health_check",
    "description": "Perform an HTTP GET health check on any URL. Returns status code, response time in ms, and content length.",
    "category": "monitoring",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to health-check (e.g. https://example.com/health)"},
            "timeout": {"type": "integer", "description": "Request timeout in seconds (default 10)"},
        },
        "required": ["url"],
    },
    "auth_type": "none",
    "config_keys": [],
    "compat": {
        "service": "generic",
        "api_version_built_for": "",
        "min_version": "",
        "max_version": "",
        "version_endpoint": "",
        "version_field": "",
    },
}


# ── Response helpers ───────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


# ── Execute ────────────────────────────────────────────────────────────────────
def execute(**kwargs) -> dict:
    url = kwargs.get("url", "")
    if not url:
        return _err("url is required")

    timeout = kwargs.get("timeout", 10)
    if not isinstance(timeout, int) or timeout < 1:
        timeout = 10

    try:
        r = httpx.get(url, timeout=float(timeout), follow_redirects=True, verify=False)
        elapsed_ms = round(r.elapsed.total_seconds() * 1000, 1)
        content_length = len(r.content)
        status_code = r.status_code

        result = {
            "url": url,
            "status_code": status_code,
            "response_time_ms": elapsed_ms,
            "content_length": content_length,
        }

        if 200 <= status_code < 300:
            return _ok(result, f"{url} — {status_code} OK in {elapsed_ms}ms")
        elif 300 <= status_code < 500:
            return _degraded(result,
                             f"{url} — {status_code} in {elapsed_ms}ms")
        else:
            return _err(f"{url} — HTTP {status_code} in {elapsed_ms}ms", data=result)

    except httpx.TimeoutException:
        return _err(f"{url} — timeout after {timeout}s", data={"url": url, "timeout": timeout})
    except httpx.ConnectError as e:
        return _err(f"{url} — connection failed: {e}", data={"url": url})
    except Exception as e:
        return _err(f"http_health_check error: {e}", data={"url": url})
