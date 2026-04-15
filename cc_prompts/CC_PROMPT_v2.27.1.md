# CC PROMPT — v2.27.1 — Backend: Discovery harvest endpoint

## What this does
New `api/routers/discovery.py` with four endpoints:
- `POST /api/discovery/harvest` — passive harvest from Proxmox VMs, UniFi clients, Swarm nodes
  Cross-references vs existing connections to identify unlinked devices
- `GET /api/discovery/devices` — list discovered+unlinked devices (stored in status_snapshots)
- `POST /api/discovery/test` — test a discovered device with a given credential profile
- `POST /api/discovery/link` — create a connection from a discovered device

All IP/CIDR input validated with Python `ipaddress` module. No raw SQL from user input.
Mounts the router in api/main.py.
Version bump: 2.27.0 → 2.27.1

---

## Change 1 — api/routers/discovery.py (NEW FILE)

```python
"""Discovery — passive harvest of unlinked devices from known infrastructure sources.

Sources:
  - Proxmox: node + VM/CT list via API
  - UniFi: client list via API
  - Docker Swarm: node list via Docker daemon
  - Manual: user-supplied IP list (validated)

All discovered devices are stored as a snapshot in status_snapshots
component='discovery_harvest' and cross-referenced vs existing connections.
"""
import ipaddress
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from api.auth import get_current_user, get_current_user_and_role, role_meets

router = APIRouter(prefix="/api/discovery", tags=["discovery"])
log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_ip(ip: str) -> bool:
    """Validate a single IP address string."""
    try:
        ipaddress.ip_address(ip.strip())
        return True
    except ValueError:
        return False


def _validate_cidr(cidr: str) -> bool:
    """Validate a CIDR notation or IP range string."""
    cidr = cidr.strip()
    try:
        ipaddress.ip_network(cidr, strict=False)
        return True
    except ValueError:
        pass
    # Also accept "192.168.1.0 255.255.255.0" subnet mask notation
    parts = cidr.split()
    if len(parts) == 2:
        try:
            ipaddress.ip_network(f"{parts[0]}/{parts[1]}", strict=False)
            return True
        except ValueError:
            pass
    return False


def _ip_in_scopes(ip: str, scopes: list[str]) -> bool:
    """Check if an IP falls within any of the configured discovery scopes."""
    if not scopes:
        return True  # No scope restriction
    try:
        addr = ipaddress.ip_address(ip.strip())
        for scope in scopes:
            try:
                net = ipaddress.ip_network(scope.strip(), strict=False)
                if addr in net:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass
    return False


def _get_discovery_scopes() -> list[str]:
    """Read discoveryScopes from settings DB. Returns list of valid CIDR strings."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting("discoveryScopes")
        if raw:
            scopes = json.loads(raw) if isinstance(raw, str) else raw
            return [s for s in scopes if _validate_cidr(str(s))]
    except Exception:
        pass
    return []


def _load_existing_hosts() -> set[str]:
    """Return set of all known connection hosts (IPs + hostnames)."""
    try:
        from api.connections import list_connections
        conns = list_connections()
        return {c.get("host", "").strip().lower() for c in conns if c.get("host")}
    except Exception:
        return set()


def _save_harvest(devices: list[dict]) -> None:
    """Persist discovered devices to status_snapshots."""
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        state = json.dumps({"devices": devices, "harvested_at": _ts()})
        sa = get_sync_engine().connect()
        sa.execute(_t(
            "INSERT INTO status_snapshots (component, state, is_healthy, timestamp) "
            "VALUES (:comp, :state, :ok, :ts)"
        ), {"comp": "discovery_harvest", "state": state, "ok": True, "ts": _ts()})
        sa.commit(); sa.close()
    except Exception as e:
        log.warning("_save_harvest failed: %s", e)


def _load_last_harvest() -> list[dict]:
    """Load latest discovery harvest from status_snapshots."""
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        row = sa.execute(_t(
            "SELECT state FROM status_snapshots WHERE component = 'discovery_harvest' "
            "ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
        sa.close()
        if row:
            state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            return state.get("devices", [])
    except Exception as e:
        log.warning("_load_last_harvest failed: %s", e)
    return []


# ── Harvest sources ────────────────────────────────────────────────────────────

def _harvest_proxmox(scopes: list[str], existing: set[str]) -> list[dict]:
    devices = []
    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("proxmox")
        for conn in conns:
            try:
                import httpx, urllib3
                urllib3.disable_warnings()
                host = conn["host"]
                port = conn.get("port", 8006)
                creds = conn.get("credentials") or {}
                user = creds.get("user", "root@pam")
                tok_name = creds.get("token_name", "")
                secret = creds.get("secret", "")
                headers = {"Authorization": f"PVEAPIToken={user}!{tok_name}={secret}"}
                base = f"https://{host}:{port}/api2/json"

                nodes_r = httpx.get(f"{base}/nodes", headers=headers, verify=False, timeout=10)
                if not nodes_r.is_success:
                    continue
                for node in nodes_r.json().get("data", []):
                    node_name = node.get("node", "")
                    # Get VMs
                    for kind in ("qemu", "lxc"):
                        try:
                            vms_r = httpx.get(f"{base}/nodes/{node_name}/{kind}",
                                              headers=headers, verify=False, timeout=10)
                            if not vms_r.is_success:
                                continue
                            for vm in vms_r.json().get("data", []):
                                ip = ""  # Proxmox REST doesn't expose VM IPs without QEMU agent
                                name = vm.get("name", f"{kind}-{vm.get('vmid', '?')}")
                                dev = {
                                    "source":         "proxmox",
                                    "source_label":   conn.get("label", host),
                                    "name":           name,
                                    "host":           ip or name,
                                    "platform_guess": "vm_host",
                                    "status":         vm.get("status", "unknown"),
                                    "meta":           {"vmid": vm.get("vmid"), "node": node_name, "type": kind},
                                    "in_scope":       True,  # Proxmox VMs trusted — always show
                                    "linked":         (ip or name).lower() in existing,
                                    "discovered_at":  _ts(),
                                }
                                devices.append(dev)
                        except Exception:
                            continue
            except Exception as e:
                log.debug("Proxmox harvest for %s failed: %s", conn.get("label"), e)
    except Exception as e:
        log.debug("Proxmox harvest failed: %s", e)
    return devices


def _harvest_unifi(scopes: list[str], existing: set[str]) -> list[dict]:
    devices = []
    try:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("unifi")
        for conn in conns:
            try:
                import httpx, urllib3
                urllib3.disable_warnings()
                host = conn["host"]
                port = conn.get("port", 443)
                creds = conn.get("credentials") or {}
                api_key = creds.get("api_key", "")
                if not api_key:
                    continue
                headers = {"X-API-KEY": api_key}
                r = httpx.get(
                    f"https://{host}:{port}/proxy/network/api/s/default/stat/sta",
                    headers=headers, verify=False, timeout=10
                )
                if not r.is_success:
                    continue
                for client in r.json().get("data", []):
                    ip = client.get("ip", "")
                    if not ip or not _validate_ip(ip):
                        continue
                    if not _ip_in_scopes(ip, scopes):
                        continue
                    hostname = client.get("hostname") or client.get("name") or ip
                    dev = {
                        "source":         "unifi",
                        "source_label":   conn.get("label", host),
                        "name":           hostname,
                        "host":           ip,
                        "platform_guess": "vm_host",  # could be anything — user chooses
                        "status":         "active" if client.get("is_wired") else "wireless",
                        "meta": {
                            "mac":      client.get("mac", ""),
                            "oui":      client.get("oui", ""),
                            "hostname": hostname,
                        },
                        "in_scope":      _ip_in_scopes(ip, scopes),
                        "linked":        ip.lower() in existing or hostname.lower() in existing,
                        "discovered_at": _ts(),
                    }
                    devices.append(dev)
            except Exception as e:
                log.debug("UniFi harvest for %s failed: %s", conn.get("label"), e)
    except Exception as e:
        log.debug("UniFi harvest failed: %s", e)
    return devices


def _harvest_swarm(scopes: list[str], existing: set[str]) -> list[dict]:
    devices = []
    try:
        from api.collectors.docker_agent01 import _get_agent01_docker_host
        import docker
        client = docker.DockerClient(base_url=_get_agent01_docker_host(), timeout=10)
        nodes = client.nodes.list()
        for node in nodes:
            attrs = node.attrs or {}
            desc = attrs.get("Description", {})
            status = attrs.get("Status", {})
            ip = status.get("Addr", "")
            hostname = desc.get("Hostname", "")
            name = hostname or ip or "?"
            dev = {
                "source":         "swarm",
                "source_label":   "Docker Swarm",
                "name":           name,
                "host":           ip or hostname,
                "platform_guess": "vm_host",
                "status":         status.get("State", "unknown"),
                "meta": {
                    "hostname":      hostname,
                    "role":          attrs.get("Spec", {}).get("Role", ""),
                    "availability":  attrs.get("Spec", {}).get("Availability", ""),
                    "engine_version": desc.get("Engine", {}).get("EngineVersion", ""),
                },
                "in_scope":      not ip or _ip_in_scopes(ip, scopes),
                "linked":        (ip or hostname).lower() in existing,
                "discovered_at": _ts(),
            }
            devices.append(dev)
        client.close()
    except Exception as e:
        log.debug("Swarm harvest failed: %s", e)
    return devices


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/harvest")
async def harvest(req: dict = None, _: str = Depends(get_current_user)):
    """Passive harvest from Proxmox, UniFi, and Swarm.
    Cross-references vs existing connections.
    Persists results for GET /api/discovery/devices.

    Optional body: { manual_ips: ["192.168.1.5", ...] }
    Manual IPs are validated with ipaddress module.
    """
    import asyncio
    req = req or {}
    scopes = _get_discovery_scopes()
    existing = _load_existing_hosts()

    # Validate manual IPs
    manual_ips = []
    for raw_ip in (req.get("manual_ips") or []):
        ip = str(raw_ip).strip()
        if not _validate_ip(ip):
            raise HTTPException(400, f"Invalid IP address: {ip!r}")
        if len(manual_ips) > 256:
            raise HTTPException(400, "Too many manual IPs (max 256)")
        manual_ips.append(ip)

    # Harvest from all sources in parallel
    px, unifi, swarm = await asyncio.gather(
        asyncio.to_thread(_harvest_proxmox, scopes, existing),
        asyncio.to_thread(_harvest_unifi,   scopes, existing),
        asyncio.to_thread(_harvest_swarm,   scopes, existing),
    )

    manual = []
    for ip in manual_ips:
        manual.append({
            "source":         "manual",
            "source_label":   "Manual entry",
            "name":           ip,
            "host":           ip,
            "platform_guess": "vm_host",
            "status":         "unknown",
            "meta":           {},
            "in_scope":       _ip_in_scopes(ip, scopes),
            "linked":         ip.lower() in existing,
            "discovered_at":  _ts(),
        })

    all_devices = px + unifi + swarm + manual
    _save_harvest(all_devices)

    return {
        "status":  "ok",
        "counts":  {
            "proxmox": len(px),
            "unifi":   len(unifi),
            "swarm":   len(swarm),
            "manual":  len(manual),
            "total":   len(all_devices),
            "unlinked": sum(1 for d in all_devices if not d.get("linked")),
        },
        "devices": all_devices,
    }


@router.get("/devices")
async def list_devices(
    unlinked_only: bool = False,
    _: str = Depends(get_current_user),
):
    """Return last harvest results. Filter by unlinked_only to see gaps."""
    devices = _load_last_harvest()
    if unlinked_only:
        devices = [d for d in devices if not d.get("linked")]
    return {"devices": devices, "count": len(devices)}


@router.post("/test")
async def test_device(req: dict, _: str = Depends(get_current_user)):
    """Test a discovered device with a given credential profile.

    Body: {
        host: "192.168.1.5",
        port: 22,
        platform: "vm_host",   # determines test method
        profile_id: "<uuid>",
    }
    Returns: { ok: bool, message: str, duration_ms: int }
    """
    host = str(req.get("host", "")).strip()
    if not host or not _validate_ip(host):
        raise HTTPException(400, "Valid host IP required")

    port = int(req.get("port") or 22)
    if port < 1 or port > 65535:
        raise HTTPException(400, "Invalid port")

    platform = str(req.get("platform", "vm_host")).strip()
    profile_id = str(req.get("profile_id", "")).strip()

    if not profile_id:
        raise HTTPException(400, "profile_id required")

    from api.db.credential_profiles import get_profile
    profile = get_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")

    creds = profile.get("credentials") or {}
    auth_type = profile.get("auth_type", "ssh")

    import time, asyncio
    t0 = time.monotonic()

    try:
        if auth_type == "ssh" and platform in ("vm_host", "docker_host"):
            from api.collectors.vm_hosts import _ssh_run
            out = await asyncio.to_thread(
                _ssh_run, host, port,
                creds.get("username", ""),
                creds.get("password", ""),
                creds.get("private_key", ""),
                "echo deathstar-ok",
                passphrase=creds.get("passphrase", ""),
            )
            ok = "deathstar-ok" in out
            message = "SSH OK" if ok else f"SSH response: {out[:80]}"
        elif auth_type == "windows" or platform == "windows":
            import httpx, urllib3
            urllib3.disable_warnings()
            winrm_port = port or 5985
            scheme = "https" if winrm_port == 5986 else "http"
            try:
                r = httpx.get(f"{scheme}://{host}:{winrm_port}/wsman",
                              verify=False, timeout=8)
                ok = r.status_code < 500
                message = f"WinRM HTTP {r.status_code}"
            except Exception as e:
                ok = False
                message = str(e)[:80]
        else:
            import httpx, urllib3
            urllib3.disable_warnings()
            scheme = "https" if port in (443, 8443, 8006, 8007) else "http"
            try:
                r = httpx.get(f"{scheme}://{host}:{port}/", verify=False,
                              timeout=8, follow_redirects=True)
                ok = r.status_code < 500
                message = f"HTTP {r.status_code}"
            except Exception as e:
                ok = False
                message = str(e)[:80]

        duration_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": ok, "message": message, "duration_ms": duration_ms,
                "host": host, "port": port}

    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "message": str(e)[:120], "duration_ms": duration_ms,
                "host": host, "port": port}


@router.post("/link")
async def link_device(
    req: dict, user_role: tuple = Depends(get_current_user_and_role)
):
    """Create a connection from a discovered device.

    Body: {
        host: "192.168.1.5",
        port: 22,
        platform: "vm_host",
        label: "my-server-01",
        profile_id: "<uuid>",    # credential profile to link
        role: "swarm_worker",    # optional config.role
        os_type: "debian",       # optional
    }
    """
    username, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")

    host = str(req.get("host", "")).strip()
    if not host or not _validate_ip(host):
        raise HTTPException(400, "Valid host IP required")

    label = str(req.get("label", host)).strip()
    if not label:
        label = host

    port = int(req.get("port") or 22)
    platform = str(req.get("platform", "vm_host")).strip()
    profile_id = str(req.get("profile_id", "")).strip()

    config: dict = {}
    if req.get("role"):
        config["role"] = str(req["role"])[:50]
    if req.get("os_type"):
        config["os_type"] = str(req["os_type"])[:50]
    if profile_id:
        config["credential_profile_id"] = profile_id

    from api.connections import create_connection
    result = create_connection(
        platform=platform, label=label, host=host, port=port,
        auth_type="ssh" if platform in ("vm_host", "windows") else "api",
        credentials={}, config=config,
    )

    if result.get("status") == "ok":
        _trigger_collector_repoll(platform)

    return result


def _trigger_collector_repoll(platform: str) -> None:
    try:
        from api.collectors.manager import manager
        import asyncio
        loop = asyncio.get_event_loop()
        for component, collector in manager._collectors.items():
            if platform in getattr(collector, "platforms", []):
                loop.create_task(manager.trigger_poll(component))
    except Exception as e:
        log.debug("_trigger_collector_repoll failed: %s", e)
```

---

## Change 2 — api/main.py: mount discovery router

Find the block where other routers are mounted (near `app.include_router` calls) and add:

```python
from api.routers.discovery import router as discovery_router
app.include_router(discovery_router)
```

NOTE for CC: Read api/main.py first to find the exact location of the router mounting block and insert in the same style as the other routers (typically in a group near escalations, layout, etc.).

---

## Version bump
Update VERSION: 2.27.0 → 2.27.1

## Commit
```bash
git add -A
git commit -m "feat(discovery): v2.27.1 passive harvest from Proxmox/UniFi/Swarm, test+link endpoints"
git push origin main
```
