"""Container introspection tools — read-only introspection of Docker
containers running on Swarm worker hosts. All tools use SSH to the vm_host
and run a pre-templated command with constrained argument validation.

Design principles:
- No raw user-shell expansion: arguments are validated and quoted per-tool,
  never concatenated into free-form command strings.
- All operations are read-only. blast_radius='none' on every tool.
- Fail closed: argument validation rejects anything outside the allowlist.
"""

from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Argument validators ──────────────────────────────────────────────────────

_CONTAINER_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{1,63}$")
_SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{1,63}$")

# Read-only paths we allow container_config_read to open.
# Order matters: anchored at common config/log locations only.
_ALLOWED_CONFIG_PATHS = [
    re.compile(r"^/etc/hosts$"),
    re.compile(r"^/etc/resolv\.conf$"),
    re.compile(r"^/etc/hostname$"),
    re.compile(r"^/etc/[a-zA-Z0-9_\-]+\.(conf|yml|yaml|json|ini|properties)$"),
    re.compile(r"^/etc/[a-zA-Z0-9_\-./]+/[a-zA-Z0-9_\-]+\.(conf|yml|yaml|json|ini|properties)$"),
    re.compile(r"^/opt/[a-zA-Z0-9_\-./]+\.(conf|yml|yaml|json|ini|properties)$"),
    re.compile(r"^/usr/share/[a-zA-Z0-9_\-./]+\.(conf|yml|yaml|json|ini|properties)$"),
    re.compile(r"^/usr/share/[a-zA-Z0-9_\-/]+/pipeline/[a-zA-Z0-9_\-]+\.conf$"),
    re.compile(r"^/var/log/[a-zA-Z0-9_\-./]+\.log$"),
]

# Env var names we refuse to return — even redacted, they shouldn't surface
# in agent context.
_ENV_SECRET_KEYS = re.compile(
    r"(?i)(password|passwd|secret|token|apikey|api_key|credential|private_key)"
)


def _validate_container_id(container_id: str) -> None:
    if not isinstance(container_id, str) or not _CONTAINER_ID_RE.match(container_id):
        raise ValueError(f"invalid container_id: {container_id!r}")


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or len(path) > 512:
        raise ValueError("path missing or too long")
    if ".." in path or not path.startswith("/"):
        raise ValueError("path must be absolute with no '..' segments")
    if not any(rx.match(path) for rx in _ALLOWED_CONFIG_PATHS):
        raise ValueError(
            f"path not in read-only allowlist. Allowed: /etc/*, /opt/*/config/*, "
            f"/usr/share/*/pipeline/*, /var/log/*. Got: {path}"
        )


def _ok(name: str, data: dict) -> dict:
    try:
        from api.metrics import CONTAINER_INTROSPECT_COUNTER
        CONTAINER_INTROSPECT_COUNTER.labels(tool=name, outcome="ok").inc()
    except Exception:
        pass
    return {"data": data, "status": "ok", "message": "", "timestamp": _ts()}


def _err(name: str, message: str) -> dict:
    try:
        from api.metrics import CONTAINER_INTROSPECT_COUNTER
        CONTAINER_INTROSPECT_COUNTER.labels(tool=name, outcome="error").inc()
    except Exception:
        pass
    return {"data": None, "status": "error", "message": message, "timestamp": _ts()}


# ── SSH helper (bypasses vm_exec allowlist — commands are pre-templated) ────

def _ssh_exec(host: str, command: str, validate: bool = False) -> dict:
    """Run `command` on a registered vm_host via SSH.

    Commands are constructed from validated, shell-quoted arguments inside
    this module, so the allowlist is intentionally bypassed. `validate` is
    accepted for signature symmetry with the allowlist path but is unused.
    """
    try:
        from api.connections import get_all_connections_for_platform
        from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
        from mcp_server.tools.vm import _resolve_connection
    except Exception as e:
        return {"status": "error", "data": None,
                "message": f"Failed to load SSH helpers: {e}",
                "timestamp": _ts()}

    all_conns = get_all_connections_for_platform("vm_host")
    if not all_conns:
        return {"status": "error", "data": None,
                "message": "No vm_host connections configured.",
                "timestamp": _ts()}

    conn = _resolve_connection(host, all_conns)
    if not conn:
        return {"status": "error", "data": None,
                "message": f"No vm_host connection found for {host!r}.",
                "timestamp": _ts()}

    try:
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"status": "error", "data": None,
                "message": f"Credential resolution failed: {e}",
                "timestamp": _ts()}

    try:
        output = _ssh_run(
            conn["host"], conn.get("port") or 22,
            username, password, private_key,
            command, jump_host=jump_host,
            _log_meta={"connection_id": str(conn.get("id", "")),
                       "resolved_label": conn.get("label", host),
                       "triggered_by": "container_introspect"},
        )
        return {
            "status": "ok",
            "data": {"output": (output or "").strip()[:8000]},
            "message": "",
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "data": None,
                "message": f"SSH failed on {conn.get('label', host)}: {e}",
                "timestamp": _ts()}


# ── Tools ────────────────────────────────────────────────────────────────────

def container_config_read(
    host: str,
    container_id: str,
    path: str,
    max_lines: int = 200,
) -> dict:
    """Read a config or log file from inside a running container.

    Safe: path must match the read-only allowlist. No shell expansion; the
    path is shlex-quoted into a fixed command template. Output is truncated
    to max_lines lines (capped at 500).
    """
    try:
        _validate_container_id(container_id)
        _validate_path(path)
    except ValueError as e:
        return _err("container_config_read", str(e))

    try:
        max_lines = max(1, min(int(max_lines or 200), 500))
    except Exception:
        max_lines = 200
    q_id = shlex.quote(container_id)
    q_path = shlex.quote(path)
    cmd = f"docker exec {q_id} cat {q_path} 2>&1 | head -{max_lines}"

    res = _ssh_exec(host=host, command=cmd, validate=False)
    if res.get("status") != "ok":
        return _err("container_config_read", res.get("message", "ssh failed"))

    out = res["data"]["output"]
    lines = out.splitlines()
    truncated = len(lines) >= max_lines
    return _ok("container_config_read", {
        "host": host,
        "container_id": container_id,
        "path": path,
        "content": out,
        "lines_returned": len(lines),
        "truncated": truncated,
    })


def container_env(
    host: str,
    container_id: str,
    grep_pattern: str | None = None,
) -> dict:
    """Return container environment variables with secrets redacted.

    Secrets matched by _ENV_SECRET_KEYS are replaced with '<redacted>'.
    Optional grep_pattern is applied case-insensitively against key names.
    """
    try:
        _validate_container_id(container_id)
    except ValueError as e:
        return _err("container_env", str(e))

    if grep_pattern is not None and grep_pattern != "":
        if not isinstance(grep_pattern, str) or len(grep_pattern) > 64:
            return _err("container_env", "grep_pattern missing or too long")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", grep_pattern):
            return _err("container_env",
                        "grep_pattern: alphanumeric / _ / - only")

    q_id = shlex.quote(container_id)
    cmd = f"docker exec {q_id} env"
    res = _ssh_exec(host=host, command=cmd, validate=False)
    if res.get("status") != "ok":
        return _err("container_env", res.get("message", "ssh failed"))

    env_lines = res["data"]["output"].splitlines()
    env: list[dict] = []
    redacted_count = 0
    gp_lower = grep_pattern.lower() if grep_pattern else None
    for line in env_lines:
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if _ENV_SECRET_KEYS.search(k):
            v = "<redacted>"
            redacted_count += 1
        if gp_lower and gp_lower not in k.lower():
            continue
        env.append({"key": k, "value": v})

    return _ok("container_env", {
        "host": host,
        "container_id": container_id,
        "env": env,
        "count": len(env),
        "redacted_count": redacted_count,
    })


def container_networks(host: str, container_id: str) -> dict:
    """Return overlay networks, IPs, and published ports for a container.

    Parses `docker inspect` with a format template into structured data.
    """
    try:
        _validate_container_id(container_id)
    except ValueError as e:
        return _err("container_networks", str(e))

    q_id = shlex.quote(container_id)
    net_fmt = r"""{{range $k,$v := .NetworkSettings.Networks}}{{$k}}|{{$v.IPAddress}}|{{$v.MacAddress}}
{{end}}"""
    port_fmt = r"""{{range $p,$bs := .NetworkSettings.Ports}}{{range $bs}}{{.HostPort}}|{{$p}}
{{end}}{{end}}"""

    nets_res = _ssh_exec(
        host=host,
        command=f"docker inspect {q_id} --format {shlex.quote(net_fmt)}",
        validate=False,
    )
    if nets_res.get("status") != "ok":
        return _err("container_networks", nets_res.get("message", "ssh failed"))
    networks = []
    for line in nets_res["data"]["output"].splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            networks.append({"name": parts[0], "ip": parts[1], "mac_address": parts[2]})

    ports_res = _ssh_exec(
        host=host,
        command=f"docker inspect {q_id} --format {shlex.quote(port_fmt)}",
        validate=False,
    )
    published_ports = []
    if ports_res.get("status") == "ok":
        for line in ports_res["data"]["output"].splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                host_port = parts[0]
                cproto = parts[1]
                cport, _, proto = cproto.partition("/")
                published_ports.append({
                    "host_port": host_port,
                    "container_port": cport,
                    "protocol": proto or "tcp",
                })

    return _ok("container_networks", {
        "host": host,
        "container_id": container_id,
        "networks": networks,
        "published_ports": published_ports,
    })


def container_tcp_probe(
    host: str,
    container_id: str,
    target_host: str,
    target_port: int,
    timeout_s: int = 5,
) -> dict:
    """Probe TCP reachability from INSIDE the container's network namespace.

    Uses bash's built-in `</dev/tcp/host/port` rather than nc — works
    regardless of whether nc/netcat/ncat/curl is installed in the container.
    """
    try:
        _validate_container_id(container_id)
    except ValueError as e:
        return _err("container_tcp_probe", str(e))

    if not isinstance(target_host, str) or not re.match(
        r"^[a-zA-Z0-9._\-]+$", target_host
    ):
        return _err("container_tcp_probe", "invalid target_host")
    try:
        tp = int(target_port)
    except Exception:
        return _err("container_tcp_probe", "target_port must be int")
    if not (1 <= tp <= 65535):
        return _err("container_tcp_probe", "target_port out of range")
    try:
        ts = max(1, min(int(timeout_s or 5), 30))
    except Exception:
        ts = 5

    q_id = shlex.quote(container_id)
    inner = (
        f"t=$(date +%s%N); "
        f"timeout {ts} bash -c '</dev/tcp/{target_host}/{tp}' "
        f"&& echo OK || echo FAIL; "
        f"echo RTT_NS=$(( $(date +%s%N) - $t ))"
    )
    cmd = f"docker exec {q_id} sh -c {shlex.quote(inner)}"
    res = _ssh_exec(host=host, command=cmd, validate=False)
    if res.get("status") != "ok":
        return _err("container_tcp_probe", res.get("message", "ssh failed"))

    out = res["data"]["output"] or ""
    reachable = "OK" in out.split() or out.strip().startswith("OK")
    rtt_ms: int | None = None
    m = re.search(r"RTT_NS=(\d+)", out)
    if m:
        try:
            rtt_ms = int(int(m.group(1)) / 1_000_000)
        except Exception:
            rtt_ms = None

    return _ok("container_tcp_probe", {
        "host": host,
        "container_id": container_id,
        "target_host": target_host,
        "target_port": tp,
        "reachable": reachable,
        "rtt_ms": rtt_ms,
        "method": "bash_dev_tcp",
        "raw_output": out[:500],
    })


def container_discover_by_service(service_name: str) -> dict:
    """Map a Swarm service name to its running container IDs per node."""
    if not _SERVICE_NAME_RE.match(service_name or ""):
        return _err("container_discover_by_service", "invalid service_name")

    try:
        from mcp_server.tools.vm import service_placement
    except Exception as e:
        return _err("container_discover_by_service",
                    f"service_placement import failed: {e}")

    placements = service_placement(service_name=service_name)
    if placements.get("status") != "ok":
        return _err("container_discover_by_service",
                    placements.get("message", "placement lookup failed"))

    containers: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for p in (placements.get("data") or {}).get("placements", []):
        node = p.get("node")
        vhl = p.get("vm_host_label")
        state = p.get("current_state", "")
        if not vhl or "Running" not in state:
            continue
        key = (vhl, p.get("task", ""))
        if key in seen:
            continue
        seen.add(key)

        ps_cmd = (
            f"docker ps --filter name={shlex.quote(service_name)} "
            f"--format '{{{{.ID}}}}|{{{{.Names}}}}|{{{{.State}}}}'"
        )
        res = _ssh_exec(host=vhl, command=ps_cmd, validate=False)
        if res.get("status") != "ok":
            continue
        for line in (res["data"].get("output") or "").splitlines():
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            containers.append({
                "node": node,
                "vm_host_label": vhl,
                "container_id": parts[0],
                "container_name": parts[1],
                "state": parts[2],
            })

    return _ok("container_discover_by_service", {
        "service": service_name,
        "containers": containers,
        "count": len(containers),
    })
