"""
ExternalServicesCollector — probes external service endpoints every 30s.

Services: LM Studio, Proxmox API, TrueNAS, FortiGate
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

SERVICES_CONFIG = [
    {
        "name": "LM Studio",
        "slug": "lm_studio",
        "service_type": "OpenAI-compat API",
        "host_env": "LM_STUDIO_BASE_URL",   # typically http://host:1234/v1
        "strip_suffix": "/v1",              # strip so we probe the root server
        "path": "/api/v0/models",           # LM Studio native endpoint (no log errors)
        "open_ui_url": None,
    },
    {
        "name": "Proxmox API",
        "slug": "proxmox",
        "service_type": "Proxmox cluster API",
        "host_env": "PROXMOX_HOST",
        "path": "/api2/json/version",
        "port": 8006,
        "scheme": "https",
        "auth_type": "pve_token",
        "auth_token_id_env": "PROXMOX_TOKEN_ID",
        "auth_token_secret_env": "PROXMOX_TOKEN_SECRET",
        "open_ui_url_template": "https://{host}:8006",
    },
    {
        "name": "TrueNAS",
        "slug": "truenas",
        "service_type": "TrueNAS REST API",
        "host_env": "TRUENAS_HOST",
        "path": "/api/v2.0/system/info",
        "scheme": "https",
        "auth_env": "TRUENAS_API_KEY",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "open_ui_url_template": "https://{host}",
    },
    {
        "name": "FortiGate",
        "slug": "fortigate",
        "service_type": "FortiGate REST API",
        "host_env": "FORTIGATE_HOST",
        "path": "/api/v2/monitor/system/status",
        "scheme": "https",
        "auth_env": "FORTIGATE_API_KEY",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "open_ui_url_template": "https://{host}",
    },
]


class ExternalServicesCollector(BaseCollector):
    component = "external_services"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("EXTERNAL_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        cards = []
        for cfg in SERVICES_CONFIG:
            host_raw = os.environ.get(cfg["host_env"], "")
            if host_raw.startswith("http"):
                base_url = host_raw.rstrip("/")
                strip = cfg.get("strip_suffix", "")
                if strip and base_url.endswith(strip):
                    base_url = base_url[: -len(strip)]
            else:
                scheme = cfg.get("scheme", "http")
                port = cfg.get("port", "")
                base_url = f"{scheme}://{host_raw}" + (f":{port}" if port else "")

            host_display = host_raw or "not configured"
            open_ui = None
            if "open_ui_url_template" in cfg and host_raw:
                open_ui = cfg["open_ui_url_template"].format(host=host_raw)
            elif "open_ui_url" in cfg:
                open_ui = cfg["open_ui_url"]

            if not host_raw:
                cards.append({
                    "name": cfg["name"], "slug": cfg["slug"],
                    "service_type": cfg["service_type"],
                    "host_port": host_display, "summary": "not configured",
                    "latency_ms": None, "reachable": False,
                    "open_ui_url": open_ui, "storage": None,
                    "dot": "grey", "problem": "not configured",
                })
                continue

            headers = {}
            if cfg.get("auth_type") == "pve_token":
                token_id = os.environ.get(cfg.get("auth_token_id_env", ""), "")
                token_secret = os.environ.get(cfg.get("auth_token_secret_env", ""), "")
                if token_id and token_secret:
                    headers["Authorization"] = f"PVEAPIToken={token_id}={token_secret}"
            else:
                auth_key = os.environ.get(cfg.get("auth_env", ""), "")
                if auth_key and "auth_header" in cfg:
                    headers[cfg["auth_header"]] = cfg.get("auth_prefix", "") + auth_key

            url = base_url + cfg["path"]
            r = None
            try:
                t0 = time.monotonic()
                r = httpx.get(url, headers=headers, verify=False, timeout=8, follow_redirects=True)
                latency_ms = round((time.monotonic() - t0) * 1000)
                reachable = r.status_code < 500
            except Exception as e:
                log.warning("External probe failed for %s: %s", cfg["slug"], e)
                latency_ms = None
                reachable = False

            summary = _build_summary(cfg["slug"], r if reachable else None)
            storage = _build_storage(cfg["slug"], r if reachable else None)
            dot, problem = _classify_external(reachable, latency_ms)

            cards.append({
                "name": cfg["name"], "slug": cfg["slug"],
                "service_type": cfg["service_type"],
                "host_port": host_display,
                "summary": summary,
                "latency_ms": latency_ms,
                "reachable": reachable,
                "open_ui_url": open_ui,
                "storage": storage,
                "dot": dot,
                "problem": problem,
            })

        has_error = any(s["dot"] == "red" for s in cards if s["dot"] != "grey")
        has_warn = any(s["dot"] == "amber" for s in cards if s["dot"] != "grey")
        health = "critical" if has_error else "degraded" if has_warn else "healthy"
        return {"health": health, "services": cards}


def _build_summary(slug: str, resp) -> str:
    if resp is None:
        return "unreachable"
    try:
        if slug == "lm_studio":
            data = resp.json()
            models = data.get("data", [])
            return models[0].get("id", "no model") if models else "no model loaded"
        if slug == "proxmox":
            data = resp.json().get("data", {})
            return f"version {data.get('version', '?')}"
        if slug == "truenas":
            data = resp.json()
            return f"TrueNAS {data.get('version', '?')}"
        if slug == "fortigate":
            return "authenticated"
    except Exception:
        pass
    return "ok"


def _build_storage(slug: str, resp) -> dict | None:
    """TrueNAS only — pool usage requires a separate call; return None for now."""
    return None


def _classify_external(reachable: bool, latency_ms: int | None) -> tuple[str, str | None]:
    if not reachable:
        return "red", "unreachable"
    if latency_ms and latency_ms > 500:
        return "red", f"high latency ({latency_ms} ms)"
    if latency_ms and latency_ms > 100:
        return "amber", f"high latency ({latency_ms} ms)"
    return "green", None
