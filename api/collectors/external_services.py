"""
ExternalServicesCollector — probes all configured connections every 30s.

Driven by the connections DB — adding a connection in Settings makes it
appear here automatically. Falls back to SERVICES_CONFIG for LM Studio
(which doesn't use the connections table).

Writes component="external_services" to status_snapshots.
State shape: { health, services: [ExternalServiceCard] }
"""
import asyncio
import logging
import os
import time

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

# Platform → health check config (path, scheme, port, auth style)
PLATFORM_HEALTH = {
    "proxmox":         {"path": "/api2/json/version", "scheme": "https", "port": 8006, "auth": "pve_token"},
    "pbs":             {"path": "/api2/json/version", "scheme": "https", "port": 8007, "auth": "pve_token"},
    "fortigate":       {"path": "/api/v2/monitor/system/status", "scheme": "https", "auth": "apikey_query"},
    "truenas":         {"path": "/api/v2.0/system/info", "scheme": "https", "auth": "bearer"},
    "unifi":           {"path": "/api/s/default/stat/health", "scheme": "https", "port": 8443, "auth": "basic"},
    "security_onion":  {"path": "/api/info", "scheme": "https", "auth": "basic"},
    "wazuh":           {"path": "/", "scheme": "https", "port": 55000, "auth": "basic"},
    "grafana":         {"path": "/api/health", "scheme": "http", "port": 3000, "auth": "bearer"},
    "portainer":       {"path": "/api/status", "scheme": "https", "port": 9443, "auth": "apikey_header"},
    "kibana":          {"path": "/api/status", "scheme": "http", "port": 5601, "auth": "basic"},
    "netbox":          {"path": "/api/status/", "scheme": "https", "auth": "token_header"},
    "synology":        {"path": "/webapi/entry.cgi?api=SYNO.API.Info&version=1&method=query", "scheme": "https", "port": 5001, "auth": "none"},
    "adguard":         {"path": "/control/status", "scheme": "http", "port": 3000, "auth": "basic"},
    "opnsense":        {"path": "/api/core/firmware/status", "scheme": "https", "auth": "basic"},
    "syncthing":       {"path": "/rest/system/status", "scheme": "http", "port": 8384, "auth": "apikey_header"},
    "caddy":           {"path": "/config/", "scheme": "http", "port": 2019, "auth": "none"},
    "traefik":         {"path": "/api/overview", "scheme": "http", "port": 8080, "auth": "basic"},
    "nginx":           {"path": "/nginx_status", "scheme": "http", "auth": "none"},
    "pihole":          {"path": "/admin/api.php?summaryRaw", "scheme": "http", "auth": "none"},
    "technitium":      {"path": "/api/zones/list", "scheme": "http", "auth": "apikey_query"},
    "bookstack":       {"path": "/api/docs.json", "scheme": "https", "auth": "token_header"},
    "trilium":         {"path": "/etapi/app-info", "scheme": "http", "port": 8080, "auth": "token_header"},
}

# LM Studio — not a connection, uses env var directly
LM_STUDIO_CONFIG = {
    "name": "LM Studio",
    "slug": "lm_studio",
    "service_type": "OpenAI-compat API",
    "host_env": "LM_STUDIO_BASE_URL",
    "strip_suffix": "/v1",
    "path": "/api/v0/models",
    "auth_env": "LM_STUDIO_API_KEY",
    "auth_header": "Authorization",
    "auth_prefix": "Bearer ",
}


class ExternalServicesCollector(BaseCollector):
    component = "external_services"
    platforms = list(PLATFORM_HEALTH.keys())

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("EXTERNAL_POLL_INTERVAL", "30"))

    def mock(self) -> dict:
        return {
            "health": "degraded",
            "services": [
                {"name": "FortiGate", "slug": "fortigate", "service_type": "fortigate",
                 "host_port": "192.168.1.1:443", "summary": "HTTP 200", "latency_ms": 18,
                 "reachable": True, "dot": "green", "problem": None, "open_ui_url": "https://192.168.1.1", "connection_id": "mock-fg"},
                {"name": "TrueNAS", "slug": "truenas", "service_type": "truenas",
                 "host_port": "192.168.1.2:443", "summary": "unreachable", "latency_ms": None,
                 "reachable": False, "dot": "red", "problem": "unreachable", "open_ui_url": "https://192.168.1.2", "connection_id": "mock-tn"},
            ],
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity, PLATFORM_SECTION
        dot_to_status = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        entities = []
        for svc in state.get("services", []):
            slug = svc.get("slug") or svc.get("service_type", "unknown")
            dot = svc.get("dot", "grey")
            entities.append(Entity(
                id=f"external_services:{slug}", label=svc.get("name", slug),
                component=self.component, platform=slug,
                section=PLATFORM_SECTION.get(slug, "PLATFORM"),
                status=dot_to_status.get(dot, "unknown"),
                latency_ms=svc.get("latency_ms"),
                last_error=svc.get("problem") if dot == "red" else None,
                metadata={"host_port": svc.get("host_port"), "open_ui_url": svc.get("open_ui_url"),
                          "summary": svc.get("summary"), "connection_id": svc.get("connection_id")},
            ))
        return entities if entities else super().to_entities(state)

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        cards = []

        # 1. Probe LM Studio (env-var based, not a connection)
        cards.append(self._probe_lm_studio())

        # 2. Probe all connections from DB
        try:
            from api.connections import get_connection_for_platform
            for platform, health_cfg in PLATFORM_HEALTH.items():
                conn = get_connection_for_platform(platform)
                if not conn:
                    continue
                cards.append(self._probe_connection(conn, health_cfg))
        except Exception as e:
            log.warning("ExternalServicesCollector DB read failed: %s", e)

        has_error = any(s["dot"] == "red" for s in cards if s["dot"] != "grey")
        has_warn = any(s["dot"] == "amber" for s in cards if s["dot"] != "grey")
        health = "critical" if has_error else "degraded" if has_warn else "healthy"
        return {"health": health, "services": cards}

    def _probe_connection(self, conn: dict, health_cfg: dict) -> dict:
        """Probe a single connection using its platform health config."""
        host = conn.get("host", "")
        port = conn.get("port") or health_cfg.get("port", 443)
        scheme = health_cfg.get("scheme", "https")
        path = health_cfg.get("path", "/")
        auth_style = health_cfg.get("auth", "none")
        platform = conn.get("platform", "")
        label = conn.get("label") or f"{platform} ({host})"
        creds = conn.get("credentials", {})
        if not isinstance(creds, dict):
            creds = {}

        # UniFi dynamic auth: api_key → X-API-KEY + /proxy/network prefix; else basic
        if platform == "unifi" and creds.get("api_key"):
            port = conn.get("port") or 443
            auth_style = "unifi_apikey"
            path = "/proxy/network/api/s/default/stat/health"

        base_url = f"{scheme}://{host}:{port}"
        url = base_url + path

        # Build auth headers/params
        headers = {}
        params = {}
        if auth_style == "unifi_apikey":
            headers["X-API-KEY"] = creds.get("api_key", "")
        elif auth_style == "pve_token":
            user = creds.get("user", "")
            token_name = creds.get("token_name", "")
            secret = creds.get("secret", "")
            if user and token_name and secret:
                headers["Authorization"] = f"PBSAPIToken={user}!{token_name}:{secret}" if platform == "pbs" else f"PVEAPIToken={user}!{token_name}={secret}"
        elif auth_style == "bearer":
            key = creds.get("api_key", "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        elif auth_style == "basic":
            user = creds.get("username", "")
            pw = creds.get("password", "")
            if user:
                import base64
                b64 = base64.b64encode(f"{user}:{pw}".encode()).decode()
                headers["Authorization"] = f"Basic {b64}"
        elif auth_style == "apikey_query":
            key = creds.get("api_key", "")
            if key:
                params["access_token"] = key
        elif auth_style == "apikey_header":
            key = creds.get("api_key", "")
            if key:
                headers["X-API-Key"] = key
        elif auth_style == "token_header":
            key = creds.get("api_key", creds.get("token_id", ""))
            secret = creds.get("secret", "")
            if key and secret:
                headers["Authorization"] = f"Token {key}:{secret}"
            elif key:
                headers["Authorization"] = key

        # Probe
        try:
            t0 = time.monotonic()
            r = httpx.get(url, headers=headers, params=params, verify=False, timeout=8, follow_redirects=True)
            latency_ms = round((time.monotonic() - t0) * 1000)
            reachable = r.status_code < 500
        except Exception as e:
            log.debug("External probe %s (%s) failed: %s", label, host, e)
            try:
                from api.connections import mark_connection_verified
                mark_connection_verified(conn.get("id"), False)
            except Exception:
                pass
            return {
                "name": label, "slug": platform, "service_type": platform,
                "host_port": f"{host}:{port}", "summary": str(e)[:80],
                "latency_ms": None, "reachable": False,
                "open_ui_url": f"{scheme}://{host}:{port}" if host else None,
                "storage": None, "dot": "red", "problem": "unreachable",
                "connection_id": conn.get("id"),
            }

        dot, problem = _classify_external(reachable, latency_ms)
        try:
            from api.connections import mark_connection_verified
            mark_connection_verified(conn.get("id"), reachable)
        except Exception:
            pass
        return {
            "name": label, "slug": platform, "service_type": platform,
            "host_port": f"{host}:{port}",
            "summary": f"HTTP {r.status_code}" if reachable else f"HTTP {r.status_code}",
            "latency_ms": latency_ms, "reachable": reachable,
            "open_ui_url": f"{scheme}://{host}:{port}" if host else None,
            "storage": None, "dot": dot, "problem": problem,
            "connection_id": conn.get("id"),
        }

    def _probe_lm_studio(self) -> dict:
        """Probe LM Studio using env vars (not a connection)."""
        cfg = LM_STUDIO_CONFIG
        host_raw = os.environ.get(cfg["host_env"], "")
        if not host_raw:
            return {
                "name": cfg["name"], "slug": cfg["slug"], "service_type": cfg["service_type"],
                "host_port": "not configured", "summary": "not configured",
                "latency_ms": None, "reachable": False,
                "open_ui_url": None, "storage": None,
                "dot": "grey", "problem": "not configured",
            }

        base_url = host_raw.rstrip("/")
        strip = cfg.get("strip_suffix", "")
        if strip and base_url.endswith(strip):
            base_url = base_url[: -len(strip)]

        headers = {}
        auth_key = os.environ.get(cfg.get("auth_env", ""), "")
        if auth_key:
            headers[cfg["auth_header"]] = cfg.get("auth_prefix", "") + auth_key

        url = base_url + cfg["path"]
        try:
            t0 = time.monotonic()
            r = httpx.get(url, headers=headers, verify=False, timeout=8, follow_redirects=True)
            latency_ms = round((time.monotonic() - t0) * 1000)
            reachable = r.status_code < 500
        except Exception:
            return {
                "name": cfg["name"], "slug": cfg["slug"], "service_type": cfg["service_type"],
                "host_port": host_raw, "summary": "unreachable",
                "latency_ms": None, "reachable": False,
                "open_ui_url": None, "storage": None,
                "dot": "red", "problem": "unreachable",
            }

        dot, problem = _classify_external(reachable, latency_ms)
        return {
            "name": cfg["name"], "slug": cfg["slug"], "service_type": cfg["service_type"],
            "host_port": host_raw, "summary": f"HTTP {r.status_code}",
            "latency_ms": latency_ms, "reachable": reachable,
            "open_ui_url": None, "storage": None,
            "dot": dot, "problem": problem,
        }


def _classify_external(reachable: bool, latency_ms: int | None) -> tuple[str, str | None]:
    if not reachable:
        return "red", "unreachable"
    if latency_ms and latency_ms > 500:
        return "amber", f"slow ({latency_ms}ms)"
    return "green", None
