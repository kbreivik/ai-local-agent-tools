# CC PROMPT — v2.6.2 — Fix test_connection for PBS and UniFi

## Problem

`POST /api/connections/{id}/test` returns red for both PBS and UniFi connections.

Two bugs in `test_connection()` in `api/connections.py`:

1. **PBS** — port 8007 is not in the hardcoded scheme-detection list
   `(443, 8443, 8006, 9443, 5001)`, so it tries `http://host:8007/` instead of
   `https://host:8007/` — PBS only serves HTTPS → connection error → red.

2. **UniFi** — the generic root-URL hit `https://host:port/` with no auth is
   fragile; for UDM SE with API key the port is 443 and the test incidentally
   works, but for session-auth mode (port 8443) the controller may not respond
   at `/` with a useful status code.

The real fix: `test_connection()` should use the same platform-specific health
check logic already defined in `ExternalServicesCollector` (`PLATFORM_HEALTH` +
`_probe_connection()`) instead of rolling its own dumb HTTP check.

---

## Fix

File: `api/connections.py`

Replace the entire `test_connection()` function:

```python
def test_connection(connection_id: str) -> dict:
    """Test a connection by probing its platform health endpoint (same logic as
    ExternalServicesCollector) so auth, path, and scheme are always correct."""
    connection = get_connection(connection_id)
    if not connection:
        return {"status": "error", "message": "Connection not found"}

    platform = connection["platform"]
    now = _ts()

    # Use the platform-specific health check from ExternalServicesCollector
    try:
        from api.collectors.external_services import PLATFORM_HEALTH, ExternalServicesCollector
        health_cfg = PLATFORM_HEALTH.get(platform)
        if health_cfg:
            collector = ExternalServicesCollector()
            result = collector._probe_connection(connection, health_cfg)
            ok = result.get("dot") == "green"
            update_connection(connection_id, verified=ok, last_seen=now)
            return {
                "status": "ok" if ok else "error",
                "data": {
                    "reachable": result.get("reachable", False),
                    "latency_ms": result.get("latency_ms"),
                    "summary": result.get("summary", ""),
                    "dot": result.get("dot", "red"),
                },
                "timestamp": now,
                "message": result.get("summary") or result.get("problem") or "unreachable",
            }
    except Exception as e:
        log.warning("test_connection platform probe failed (%s): %s", platform, e)

    # Fallback for platforms not in PLATFORM_HEALTH: generic HTTPS reachability check
    try:
        import httpx
        host = connection["host"]
        port = connection.get("port", 443)
        # Treat any port that is known-HTTPS or >1024 and unknown as https
        https_ports = {443, 8443, 8006, 8007, 9443, 5001, 8001}
        scheme = "https" if port in https_ports else "http"
        r = httpx.get(f"{scheme}://{host}:{port}/", verify=False, timeout=10,
                      follow_redirects=True)
        ok = r.status_code < 500
        update_connection(connection_id, verified=ok, last_seen=now)
        return {
            "status": "ok" if ok else "error",
            "data": {"http_status": r.status_code},
            "timestamp": now,
            "message": f"HTTP {r.status_code}",
        }
    except Exception as e:
        update_connection(connection_id, verified=False, last_seen=now)
        return {"status": "error", "data": None, "timestamp": now, "message": str(e)}
```

No other files need changes — `_probe_connection()` already handles the UniFi
API key vs basic auth switching, the PBS `PBSAPIToken` header format, and all
other platform auth styles correctly.

---

## Test after deploy

1. Settings → Connections → click test on PBS connection → should go green
2. Settings → Connections → click test on UniFi connection → should go green
3. Spot-check any other connection (FortiGate, TrueNAS, Proxmox) — should be
   unaffected (they were already working)

---

## Commit & deploy

```bash
git add -A
git commit -m "fix(connections): test_connection delegates to platform health probe

PBS port 8007 was being tested over HTTP (not in hardcoded https-port list).
UniFi generic root-URL hit was fragile. Both now use _probe_connection() from
ExternalServicesCollector which has correct auth, path, and scheme per platform."
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
