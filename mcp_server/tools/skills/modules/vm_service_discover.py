"""Discover running services and cleanup capabilities on a VM host."""

SKILL_META = {
    "name": "vm_service_discover",
    "description": (
        "SSH into a VM host and discover running services, their disk/memory footprint, "
        "and available cleanup operations. Returns a structured list of services with "
        "recommended actions the agent can take. Use this before any VM maintenance task "
        "to understand what's running and what can be safely cleaned."
    ),
    "category": "compute",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "VM host label, hostname, or IP.",
            },
        },
        "required": ["host"],
    },
    "compat": {"service": "vm_host", "api_version_built_for": "1.0"},
}

_DISCOVER_SCRIPT = r'''
echo "=HOSTNAME="
hostname
echo "=OS="
cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '"'
echo "=SYSTEMD_SERVICES="
systemctl list-units --type=service --state=running --no-pager \
  --no-legend 2>/dev/null | awk '{print $1}'
echo "=DOCKER_CONTAINERS="
docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" 2>/dev/null \
  || echo "not installed"
echo "=DOCKER_IMAGES="
docker images --format "{{.Repository}}:{{.Tag}}\t{{.Size}}" 2>/dev/null \
  | head -15
echo "=DOCKER_DANGLING="
docker images -f "dangling=true" -q 2>/dev/null | wc -l
echo "=DOCKER_DISK="
docker system df 2>/dev/null || echo "not installed"
echo "=JOURNAL_SIZE="
journalctl --disk-usage 2>/dev/null || echo "unavailable"
echo "=APT_AUTOREMOVE="
apt-get --dry-run autoremove 2>/dev/null | grep "^Remov" | wc -l
echo "=DISK_ROOT="
df -h / 2>/dev/null | tail -1
'''


def _ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _parse_sections(output):
    sections = {}
    current = None
    lines = []
    for line in output.splitlines():
        if line.startswith("=") and line.endswith("=") and len(line) > 2:
            if current is not None:
                sections[current] = [l for l in lines if l.strip()]
            current = line.strip("=")
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = [l for l in lines if l.strip()]
    return sections


def _build_capabilities(sections):
    caps = []

    # Docker dangling images
    dangling_str = (sections.get("DOCKER_DANGLING") or ["0"])[0].strip()
    try: dangling = int(dangling_str)
    except ValueError: dangling = 0
    if dangling > 0:
        caps.append({
            "service": "docker", "type": "dangling_images",
            "description": f"{dangling} dangling Docker images",
            "cleanup_command": "docker image prune -f",
            "severity": "high" if dangling > 10 else "medium",
            "safe": True,
        })

    # Docker build cache
    docker_disk = "\n".join(sections.get("DOCKER_DISK") or [])
    if "Build Cache" in docker_disk:
        caps.append({
            "service": "docker", "type": "build_cache",
            "description": "Docker build cache can be cleared",
            "cleanup_command": "docker builder prune -f",
            "severity": "low", "safe": True,
        })

    # Docker containers info
    containers = sections.get("DOCKER_CONTAINERS") or []
    if containers and containers[0] != "not installed":
        caps.append({
            "service": "docker", "type": "containers_info",
            "description": f"{len(containers)} running containers",
            "containers": containers[:10],
            "cleanup_command": None, "severity": "info", "safe": True,
        })

    # systemd journal
    for line in (sections.get("JOURNAL_SIZE") or []):
        if "take up" in line.lower():
            parts = line.split()
            size_str = parts[-1].rstrip(".") if parts else "?"
            caps.append({
                "service": "systemd-journald", "type": "journal_logs",
                "description": f"Journal logs: {size_str}",
                "cleanup_command": "journalctl --vacuum-size=100M",
                "severity": "medium", "safe": True,
            })
            break

    # apt autoremove
    ar_str = (sections.get("APT_AUTOREMOVE") or ["0"])[0].strip()
    try: ar_count = int(ar_str)
    except ValueError: ar_count = 0
    if ar_count > 0:
        caps.append({
            "service": "apt", "type": "unused_packages",
            "description": f"{ar_count} package(s) can be autoremoved",
            "cleanup_command": "apt-get autoremove -y",
            "severity": "low", "safe": True,
        })

    return caps


def execute(**kwargs):
    host = kwargs.get("host", "")
    if not host:
        return {"status": "error", "message": "host required", "data": None, "timestamp": _ts()}

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Connection load failed: {e}",
                "data": None, "timestamp": _ts()}

    try:
        from mcp_server.tools.vm import _resolve_connection
        conn = _resolve_connection(host, all_conns)
    except Exception:
        q = host.lower()
        conn = next((c for c in all_conns if c.get("label", "").lower() == q
                     or c.get("host", "") == host or q in c.get("label", "").lower()), None)

    if not conn:
        labels = [f"{c.get('label', '?')} ({c.get('host', '?')})" for c in all_conns]
        return {"status": "error", "message": f"No vm_host for {host!r}. Available: {', '.join(labels)}",
                "data": None, "timestamp": _ts()}

    try:
        from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
        output = _ssh_run(conn["host"], conn.get("port") or 22,
                          username, password, private_key,
                          _DISCOVER_SCRIPT, jump_host=jump_host)
    except Exception as e:
        return {"status": "error", "message": f"SSH failed on {host}: {e}",
                "data": None, "timestamp": _ts()}

    sections = _parse_sections(output)
    caps = _build_capabilities(sections)
    label = conn.get("label", host)
    hostname = (sections.get("HOSTNAME") or [label])[0]
    os_str = (sections.get("OS") or ["unknown"])[0]
    disk_root = (sections.get("DISK_ROOT") or [""])[0]
    systemd_services = sections.get("SYSTEMD_SERVICES") or []
    containers = sections.get("DOCKER_CONTAINERS") or []
    docker_images = sections.get("DOCKER_IMAGES") or []

    return {
        "status": "ok",
        "message": f"Discovered {len(caps)} cleanup opportunities on {label}",
        "data": {
            "host": label,
            "os": os_str,
            "hostname": hostname,
            "disk_root": disk_root,
            "running_services": systemd_services[:20],
            "docker_containers": [c for c in containers[:10] if c != "not installed"],
            "docker_images": docker_images[:10],
            "capabilities": caps,
            "recommended_next": [c["cleanup_command"] for c in caps
                                 if c.get("cleanup_command") and c.get("severity") in ("high", "medium")],
        },
        "timestamp": _ts(),
    }
