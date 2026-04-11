"""One-shot disk investigation skill for VM hosts."""

SKILL_META = {
    "name": "vm_disk_investigate",
    "description": (
        "Full disk usage investigation on a VM host in a single SSH session. "
        "Detects OS, finds top space consumers, checks Docker storage "
        "(images/volumes/build cache), journal size, and Postgres data dir. "
        "Returns structured report with top culprits and recommended actions. "
        "Use this instead of multiple vm_exec calls for disk investigations."
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
                "description": "VM host label, hostname, or IP. Uses infra_inventory for resolution.",
            },
        },
        "required": ["host"],
    },
    "compat": {"service": "vm_host", "api_version_built_for": "1.0"},
}

_INVESTIGATE_SCRIPT = r"""
echo "=OS="
cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"'

echo "=DISK_SUMMARY="
df -h --output=source,size,used,avail,pcent,target 2>/dev/null | grep -v tmpfs | grep -v udev | tail -n +2

echo "=TOP_DIRS="
du -sh /var /tmp /home /opt /root /srv 2>/dev/null | sort -hr | head -10

echo "=VAR_BREAKDOWN="
du -sh /var/* 2>/dev/null | sort -hr | head -8

echo "=JOURNAL_SIZE="
journalctl --disk-usage 2>/dev/null || echo "unavailable"

echo "=DOCKER_SUMMARY="
docker system df 2>/dev/null || echo "not installed"

echo "=DOCKER_IMAGES="
docker images --format "{{.Size}}\t{{.Repository}}:{{.Tag}}" 2>/dev/null | sort -hr | head -10

echo "=DOCKER_VOLUMES="
docker volume ls -q 2>/dev/null | head -20

echo "=DOCKER_VOLUME_SIZES="
for v in $(docker volume ls -q 2>/dev/null | head -15); do
  mp=$(docker volume inspect "$v" --format '{{.Mountpoint}}' 2>/dev/null)
  if [ -n "$mp" ]; then
    size=$(du -sh "$mp" 2>/dev/null | cut -f1)
    echo "$size $v"
  fi
done

echo "=POSTGRES_DATA="
du -sh /var/lib/postgresql 2>/dev/null || \
du -sh $(docker volume ls -q 2>/dev/null | grep -i postgres | head -1 | xargs -r docker volume inspect --format '{{.Mountpoint}}' 2>/dev/null) 2>/dev/null || \
echo "not found"

echo "=OVERLAY2_SIZE="
du -sh /var/lib/docker/overlay2 2>/dev/null || echo "unavailable"

echo "=DOCKER_VOLUMES_DETAIL="
docker system df -v 2>/dev/null | grep -A 100 "Local Volumes" | head -30

echo "=POSTGRES_CONTAINERS="
docker ps --format "{{.Names}}\t{{.Image}}\t{{.Mounts}}" 2>/dev/null \
  | grep -i postgres | head -5

echo "=TOP_DOCKER_VOLUMES="
for v in $(docker volume ls -q 2>/dev/null); do
  mp=$(docker volume inspect "$v" --format '{{.Mountpoint}}' 2>/dev/null)
  if [ -n "$mp" ]; then
    du -sh "$mp" 2>/dev/null | awk -v name="$v" '{print $1, name}'
  fi
done 2>/dev/null | sort -hr | head -10

echo "=LARGE_FILES="
find /var /home /opt -size +100M -type f 2>/dev/null | head -10

echo "=DANGLING_IMAGES="
docker images -f "dangling=true" -q 2>/dev/null | wc -l
"""


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


def _parse_size_to_gb(size_str):
    s = size_str.strip().upper()
    try:
        if s.endswith("G"): return float(s[:-1])
        if s.endswith("M"): return float(s[:-1]) / 1024
        if s.endswith("K"): return float(s[:-1]) / 1024 / 1024
        if s.endswith("T"): return float(s[:-1]) * 1024
        return float(s)
    except ValueError:
        return 0.0


def _top_culprits(sections):
    culprits = []
    sev_order = {"high": 0, "medium": 1, "low": 2}

    # Docker dangling images
    dangling = (sections.get("DANGLING_IMAGES") or ["0"])[0].strip()
    try: dangling_count = int(dangling)
    except ValueError: dangling_count = 0
    if dangling_count > 0:
        culprits.append({"name": f"Docker dangling images ({dangling_count})",
                         "action": "docker image prune -f",
                         "severity": "high" if dangling_count > 10 else "medium"})

    # Journal
    for line in (sections.get("JOURNAL_SIZE") or []):
        if "journals take up" in line:
            parts = line.split()
            if parts:
                size_str = parts[-1].rstrip(".")
                size_gb = _parse_size_to_gb(size_str)
                if size_gb > 0.2:
                    culprits.append({"name": f"systemd journal ({size_str})",
                                     "action": "journalctl --vacuum-size=100M",
                                     "severity": "high" if size_gb > 1.0 else "medium"})
            break

    # Docker overlay2 (layer storage — accumulates with image builds)
    for line in (sections.get("OVERLAY2_SIZE") or []):
        parts = line.split()
        if parts and parts[0] not in ("unavailable",):
            size_gb = _parse_size_to_gb(parts[0])
            if size_gb > 5.0:
                culprits.append({"name": f"Docker overlay2 layers ({parts[0]})",
                                 "action": "docker system prune -f  # removes stopped containers + dangling images",
                                 "severity": "high" if size_gb > 20 else "medium"})
            break

    # Top Docker volumes by actual measured size
    for line in (sections.get("TOP_DOCKER_VOLUMES") or []):
        parts = line.split(None, 1)
        if len(parts) == 2:
            size_gb = _parse_size_to_gb(parts[0])
            vol_name = parts[1].strip()
            if size_gb > 5.0:
                culprits.append({"name": f"Docker volume '{vol_name}' ({parts[0]})",
                                 "action": f"Inspect contents: docker volume inspect {vol_name}",
                                 "severity": "high" if size_gb > 20 else "medium"})

    # Postgres
    for line in (sections.get("POSTGRES_DATA") or []):
        parts = line.split()
        if len(parts) >= 1 and parts[0] not in ("not", "unavailable", ""):
            size_gb = _parse_size_to_gb(parts[0])
            if size_gb > 1.0:
                culprits.append({"name": f"PostgreSQL data ({parts[0]})",
                                 "action": "Run VACUUM FULL on large tables; consider pg_dump + restore",
                                 "severity": "high" if size_gb > 10 else "medium"})
            break

    # Docker volumes by size (from old DOCKER_VOLUME_SIZES section — kept for compat)
    for line in (sections.get("DOCKER_VOLUME_SIZES") or []):
        parts = line.split(None, 1)
        if len(parts) == 2:
            size_gb = _parse_size_to_gb(parts[0])
            vol_name = parts[1].strip()
            # Skip if already covered by TOP_DOCKER_VOLUMES
            if size_gb > 2.0 and not any(vol_name in c.get("name", "") for c in culprits):
                culprits.append({"name": f"Docker volume {vol_name} ({parts[0]})",
                                 "action": f"Inspect: docker volume inspect {vol_name}",
                                 "severity": "medium"})

    # Large files
    large = sections.get("LARGE_FILES") or []
    if large:
        culprits.append({"name": f"{len(large)} file(s) >100MB", "detail": large[:5],
                         "action": "Review files; remove old backups/logs",
                         "severity": "medium" if len(large) > 3 else "low"})

    culprits.sort(key=lambda c: sev_order.get(c.get("severity", "low"), 2))
    return culprits[:5]


def execute(**kwargs):
    host = kwargs.get("host", "")
    if not host:
        return {"status": "error", "message": "host required", "data": None, "timestamp": _ts()}

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Connection load failed: {e}", "data": None, "timestamp": _ts()}

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
                          _INVESTIGATE_SCRIPT, jump_host=jump_host)
    except Exception as e:
        return {"status": "error", "message": f"SSH failed on {host}: {e}", "data": None, "timestamp": _ts()}

    sections = _parse_sections(output)
    culprits = _top_culprits(sections)
    label = conn.get("label", host)

    disk_pct = disk_used = disk_total = None
    for line in (sections.get("DISK_SUMMARY") or []):
        if "/" in line and line.strip().endswith("/"):
            parts = line.split()
            if len(parts) >= 5:
                disk_total = parts[1]; disk_used = parts[2]; disk_pct = parts[4]
                break

    return {
        "status": "ok",
        "message": (f"Disk investigation on {label}: {disk_pct or '?'} used "
                    f"({disk_used or '?'} of {disk_total or '?'}). "
                    f"Top culprit: {culprits[0]['name'] if culprits else 'none found'}"),
        "data": {
            "host": label,
            "os": (sections.get("OS") or ["unknown"])[0],
            "disk_summary": sections.get("DISK_SUMMARY", []),
            "disk_pct": disk_pct, "disk_used": disk_used, "disk_total": disk_total,
            "top_dirs": sections.get("TOP_DIRS", [])[:8],
            "var_breakdown": sections.get("VAR_BREAKDOWN", [])[:8],
            "journal": (sections.get("JOURNAL_SIZE") or ["unavailable"])[0],
            "docker_summary": sections.get("DOCKER_SUMMARY", []),
            "docker_volume_sizes": sections.get("DOCKER_VOLUME_SIZES", [])[:10],
            "overlay2_size": (sections.get("OVERLAY2_SIZE") or ["unavailable"])[0],
            "top_docker_volumes": sections.get("TOP_DOCKER_VOLUMES", [])[:10],
            "docker_volumes_detail": sections.get("DOCKER_VOLUMES_DETAIL", [])[:15],
            "postgres_data": (sections.get("POSTGRES_DATA") or ["not found"])[0],
            "postgres_containers": sections.get("POSTGRES_CONTAINERS", [])[:5],
            "large_files": sections.get("LARGE_FILES", [])[:10],
            "dangling_images": (sections.get("DANGLING_IMAGES") or ["0"])[0],
            "culprits": culprits,
            "recommended_actions": [c["action"] for c in culprits],
        },
        "timestamp": _ts(),
    }
