"""Caddy — running config, reverse proxy routes, and TLS certificates."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "caddy_status",
    "description": "Query Caddy running config, reverse proxy routes with upstreams, and TLS certificate status.",
    "platform": "caddy",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Caddy host (default: env CADDY_HOST)"},
        "action": {"type": "string", "required": False, "description": "'config' (default), 'reverse_proxies', or 'tls'"},
    },
}


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("CADDY_HOST", "")
    if not host:
        return _err("CADDY_HOST not configured")
    try:
        r = httpx.get(f"http://{host}:2019/config/", timeout=10)
        r.raise_for_status()
        return _ok({"reachable": True}, "Caddy admin API reachable")
    except Exception as e:
        return _err(f"Caddy connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("CADDY_HOST", "")
    action = kwargs.get("action", "config")
    if not host:
        return _err("CADDY_HOST not configured")

    base = f"http://{host}:2019"
    try:
        if action == "reverse_proxies":
            return _get_reverse_proxies(base)
        elif action == "tls":
            return _get_tls(base)
        return _get_config(base)
    except httpx.HTTPStatusError as e:
        return _err(f"Caddy API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Caddy connection failed: {e}")


def _get_config(base: str) -> dict:
    r = httpx.get(f"{base}/config/", timeout=10)
    r.raise_for_status()
    cfg = r.json()
    servers = cfg.get("apps", {}).get("http", {}).get("servers", {})
    sites = []
    for srv_name, srv in servers.items():
        for route in srv.get("routes", []):
            matchers = route.get("match", [])
            hosts = []
            for m in matchers:
                hosts.extend(m.get("host", []))
            sites.append({"server": srv_name, "hosts": hosts or ["*"]})
    return _ok({
        "servers": len(servers),
        "sites": sites,
        "site_count": len(sites),
    }, f"Caddy: {len(servers)} server(s), {len(sites)} site(s)")


def _get_reverse_proxies(base: str) -> dict:
    r = httpx.get(f"{base}/config/apps/http/servers/", timeout=10)
    if r.status_code == 404:
        return _ok({"routes": [], "count": 0}, "Caddy: no HTTP servers configured")
    r.raise_for_status()
    servers = r.json()

    routes = []
    for srv_name, srv in servers.items():
        for route in srv.get("routes", []):
            matchers = route.get("match", [])
            hosts = []
            for m in matchers:
                hosts.extend(m.get("host", []))

            upstreams = []
            for handler in route.get("handle", []):
                if handler.get("handler") == "reverse_proxy":
                    for up in handler.get("upstreams", []):
                        upstreams.append(up.get("dial", ""))

            if upstreams:
                routes.append({
                    "hosts": hosts or ["*"],
                    "upstreams": upstreams,
                    "server": srv_name,
                })
    return _ok({"routes": routes, "count": len(routes)},
               f"Caddy: {len(routes)} reverse proxy route(s)")


def _get_tls(base: str) -> dict:
    r = httpx.get(f"{base}/config/apps/tls/", timeout=10)
    if r.status_code == 404:
        return _ok({"auto_https": True, "certificates": []}, "Caddy: TLS with auto-HTTPS (default)")
    r.raise_for_status()
    tls_cfg = r.json()

    automation = tls_cfg.get("automation", {})
    policies = automation.get("policies", [])
    certs = []
    for p in policies:
        subjects = p.get("subjects", [])
        issuer = p.get("issuers", [{}])[0].get("module", "acme") if p.get("issuers") else "acme"
        certs.append({"subjects": subjects, "issuer": issuer})

    return _ok({
        "auto_https": True,
        "policies": len(policies),
        "certificates": certs,
    }, f"Caddy TLS: {len(policies)} policy/ies, auto-HTTPS enabled")
