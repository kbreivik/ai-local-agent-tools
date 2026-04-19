"""VM host SSH execution + infrastructure lookup tools."""
import re
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _suggest_pattern(segment: str) -> str:
    """Generate a safe regex pattern suggestion for a blocked command segment."""
    import re as _re
    # Take the first word (command name)
    first_word = segment.strip().split()[0] if segment.strip() else segment
    # Escape for regex, anchor at start
    return r'^' + _re.escape(first_word) + r'\b'


def _load_allowlist(session_id: str = "") -> list[str]:
    """Load allowlist patterns from DB (cached 30s). Falls back to base patterns."""
    try:
        from api.db.vm_exec_allowlist import get_patterns
        return get_patterns(session_id=session_id)
    except Exception:
        # Fallback: hardcoded base patterns (avoids import of DB module at module level)
        try:
            from api.db.vm_exec_allowlist import BASE_PATTERNS
            return [p for p, _ in BASE_PATTERNS]
        except Exception:
            return []


# ── Safe-pipe support (v2.34.10) ──────────────────────────────────────────
# Trailing commands that only trim/format output — never change the primary
# command's side-effects.
PIPE_SAFELIST = {
    "head",  # may have -N or --lines=
    "tail",
    "grep",  # text match only; -f FILE forbidden (reads arbitrary files)
    "wc",
    "sort",
    "uniq",
    "awk",   # read-only awk; -f FILE forbidden
    "sed",   # -f FILE forbidden
    "cut",
    "tr",
}

# Trailing redirects that only silence / merge output — safe on any command.
REDIRECT_SAFELIST = (
    "2>&1",
    "2> /dev/null",
    "2>/dev/null",
    "> /dev/null",
    ">/dev/null",
)


def _split_pipeline(cmd: str) -> list[str]:
    """Split a shell command on `|` respecting quoted strings.

    Trailing safelisted redirects (2>&1, >/dev/null, 2>/dev/null) are stripped
    from the command before splitting — they don't form a pipeline stage.
    Returns list of pipeline stages, each stripped of leading/trailing ws.
    """
    s = cmd.strip()
    # Strip any number of trailing safelisted redirects
    changed = True
    while changed:
        changed = False
        for redir in REDIRECT_SAFELIST:
            if s.endswith(redir):
                s = s[: -len(redir)].rstrip()
                changed = True
                break

    stages: list[str] = []
    current: list[str] = []
    in_quote: str | None = None
    for ch in s:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
        elif ch == "|":
            stages.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    stages.append("".join(current).strip())
    return [s for s in stages if s != ""]


# ── Safe boolean-chain support (v2.35.9) ─────────────────────────────────
# `cmdA && cmdB` and `cmdA || cmdB` are strictly safer than separate calls
# when both operands are read-only: no data exfiltration risk, no
# out-of-order race. Allowed only when every segment independently validates.
#
# Split carefully: `&&` and `||` are the ONLY boolean chain operators — do
# NOT split on single `&` (background) or single `|` (pipeline; that's
# already handled by _split_pipeline).

_CHAIN_OPS_RE = re.compile(r'\s*(?:&&|\|\|)\s*')


def _split_chain(cmd: str) -> list[str]:
    """Split cmd on && / ||, respecting quoted strings.

    Returns the list of sub-commands. Single-element list when no chain ops.
    """
    parts: list[str] = []
    current: list[str] = []
    in_quote: str | None = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            i += 1
        elif ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
            i += 1
        elif i + 1 < len(cmd) and cmd[i:i + 2] in ('&&', '||'):
            parts.append("".join(current).strip())
            current = []
            i += 2
        else:
            current.append(ch)
            i += 1
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _validate_command(command: str, session_id: str = "") -> tuple:
    """Validate a command against the allowlist (DB-backed, 30s cache).

    Pipeline model (v2.34.10):
      stage0           — must match the allowlist (the actual command)
      stage1..stageN   — must be in PIPE_SAFELIST (head/tail/grep/wc/...)
      trailing redir   — 2>&1, >/dev/null, 2>/dev/null all allowed

    Boolean chains (v2.35.9):
      cmdA && cmdB     — allowed when each segment independently validates
      cmdA || cmdB     — allowed when each segment independently validates
      max 3 segments

    Returns:
        (True, command)          — command is allowed (shell handles redirects)
        (False, error_dict)      — command blocked; error_dict has:
            {"blocked": True, "message": str, "segment": str,
             "pattern_suggestion": str, "hint": str}
        (False, error_str)       — shell metachar rejected (not a pattern issue)
    """
    import re as _re

    # Strip Go template --format arguments before metachar check (contain { }).
    sanitized = _re.sub(
        r"""--format\s+['"]?\{\{[^'"]*\}\}['"]?""",
        '--format TEMPLATE',
        command,
    )

    # v2.35.9: Boolean chain support — split on && / ||, validate each segment
    # independently. No segment can itself contain another chain op (we
    # already split on them) so recursion depth is 1.
    chain_segments = _split_chain(sanitized)
    if len(chain_segments) > 1:
        if len(chain_segments) > 3:
            return False, (
                f"Maximum two boolean chain operators allowed "
                f"(got {len(chain_segments) - 1} in {command!r})"
            )
        try:
            from api.metrics import VM_EXEC_CHAIN_COUNTER
        except Exception:
            VM_EXEC_CHAIN_COUNTER = None
        for seg in chain_segments:
            ok, seg_result = _validate_command(seg, session_id=session_id)
            if not ok:
                if isinstance(seg_result, dict):
                    seg_result = {
                        **seg_result,
                        "message": (
                            f"(chain segment {seg!r} failed) "
                            + seg_result.get("message", "")
                        ),
                    }
                else:
                    seg_result = f"Chain segment {seg!r} rejected: {seg_result}"
                return False, seg_result
            if VM_EXEC_CHAIN_COUNTER is not None:
                try:
                    VM_EXEC_CHAIN_COUNTER.labels(
                        op="&&" if "&&" in command else "||"
                    ).inc()
                except Exception:
                    pass
        return True, command

    # Strip safelisted redirects BEFORE the metachar check — these legitimately
    # contain & and > that would otherwise be blocked.
    scrubbed = sanitized
    for redir in REDIRECT_SAFELIST:
        scrubbed = scrubbed.replace(redir, "")

    # Block dangerous characters that have no safe use after scrubbing.
    # ; & ` $ < > are ALL dangerous outside of the safelisted redirects above.
    for bad in (';', '`', '$', '<', '&', '>'):
        if bad in scrubbed:
            return False, (
                f"Shell metacharacters not allowed: {command!r}. "
                f"Disallowed character: {bad!r}. "
                "Safe redirects (2>&1, >/dev/null) are allowed; inline "
                "substitution ($(), backticks), statement separators (;, &&), "
                "and file redirects are not."
            )

    # Parse into pipeline stages (operates on sanitized cmd with redirects intact;
    # _split_pipeline strips trailing safelisted redirects for us).
    stages = _split_pipeline(sanitized)
    if not stages:
        return False, "Empty command"

    # Cap pipeline depth to keep commands comprehensible.
    if len(stages) > 3:
        return False, "Maximum two pipes allowed (e.g. cmd | grep X | head -20)"

    allowlist = _load_allowlist(session_id=session_id)

    # Stage 0 — the actual command — must match the allowlist.
    stage0 = stages[0]
    if not any(_re.match(p, stage0) for p in allowlist):
        suggestion = _suggest_pattern(stage0)
        return False, {
            "blocked": True,
            "segment": stage0,
            "pattern_suggestion": suggestion,
            "message": (
                f"Command segment not in allowlist: {stage0!r}. "
                "Call vm_exec_allowlist_request() to request approval for this session "
                "or permanent addition."
            ),
            "hint": (
                f"Call vm_exec_allowlist_request(command={command!r}, "
                f"reason='<why you need this>', scope='session') "
                f"then plan_action() then vm_exec_allowlist_add(pattern={suggestion!r}, ...)"
            ),
        }

    # Remaining stages — each must be a safelisted pipe helper.
    try:
        from api.metrics import VM_EXEC_PIPE_COUNTER
    except Exception:
        VM_EXEC_PIPE_COUNTER = None

    for idx, stage in enumerate(stages[1:], start=1):
        tokens = stage.split()
        head = tokens[0] if tokens else ""
        if head not in PIPE_SAFELIST:
            return False, (
                f"Pipe stage {idx} uses disallowed command: {head!r}. "
                f"Allowed pipe helpers: {sorted(PIPE_SAFELIST)}"
            )
        # grep/awk/sed can read arbitrary files via -f FILE — block that.
        if head in ("grep", "awk", "sed") and " -f " in stage:
            return False, f"{head} -f (file argument) not allowed in pipe stage {idx}"
        if VM_EXEC_PIPE_COUNTER is not None:
            try:
                VM_EXEC_PIPE_COUNTER.labels(pipe_stage=head).inc()
            except Exception:
                pass

    # Pass the command through unchanged — shell handles 2>&1 / >/dev/null.
    return True, command


def _resolve_connection(host, all_conns):
    """Resolve a host name/IP/alias to a vm_host connection.
    Resolution order: infra_inventory -> label exact -> IP exact ->
    unique suffix -> unique substring.
    Returns None on ambiguous partial match — caller must format an error.
    """
    q = host.lower().strip()

    # 1. Infra inventory (hostname, aliases, IPs, partial label)
    try:
        from api.db.infra_inventory import resolve_host
        entry = resolve_host(host)
        if entry:
            conn_id = entry.get("connection_id")
            for c in all_conns:
                if str(c.get("id")) == conn_id:
                    return c
    except Exception:
        pass

    # 2. Direct connection match -- label exact -> IP exact
    for c in all_conns:
        if c.get("label", "").lower() == q:
            return c
    for c in all_conns:
        if c.get("host", "") == host:
            return c

    # 3. Unique suffix match — catches "manager-01" ≡ "ds-docker-manager-01"
    #    but rejects ambiguous matches.
    suffix_matches = [c for c in all_conns
                      if c.get("label", "").lower().endswith(q)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    # 4. Unique substring match — broader fallback, still requires uniqueness.
    substring_matches = [c for c in all_conns
                         if q in c.get("label", "").lower()]
    if len(substring_matches) == 1:
        return substring_matches[0]

    # Ambiguous partial — return None; caller formats an informative error.
    return None


def vm_exec(host: str, command: str) -> dict:
    """Execute a command on a registered VM host via SSH.

    All allowlisted commands execute directly. Write commands (docker prune,
    journalctl vacuum, apt-get clean) are in the allowlist — the agent is
    expected to call plan_action() before invoking vm_exec for these, but
    vm_exec itself does not enforce this (no second approval gate).

    Use for: disk usage (df -h), large dirs (du -sh /* | sort -hr | head -20),
    memory (free -m), logs (journalctl -n 50), Docker storage (docker system df),
    large files (find / -size +100M -type f 2>/dev/null | head -20),
    package updates (apt list --upgradable), cleanup (docker image prune -f,
    journalctl --vacuum-size=100M, apt-get autoremove -y).

    Args:
        host: VM host label, discovered hostname, or IP address.
              The error message lists available hosts if not found.
        command: IMPORTANT: If vm_exec returns "not in allowlist", do NOT retry.
                 Use these alternatives instead:
                 - docker volume sizes → docker system df -v
                 - docker volume path  → docker volume inspect <name> --format '{{.Mountpoint}}'
                 - docker container details → docker container inspect <name>
                 - structured Docker data → use docker_df tool (preferred)

                 Read-only shell command. Rules:
                 - Up to two pipes supported (cmd | cmd | cmd)
                 - '2>/dev/null' allowed (stderr discard)
                 - NO shell variables ($var), NO while/for loops,
                   NO subshells $(), NO stdout redirects (>)

                 For Docker volume sizes use: docker system df -v
                 NOT: docker volume ls | xargs docker inspect...

                 Good examples:
                   df -h
                   du -sh /* 2>/dev/null | sort -hr | head -20
                   find /var -size +100M -type f 2>/dev/null | head -20
                   docker system df -v
                   journalctl -n 50 --no-pager
                   free -m
                   ps aux | sort -k3 -rn | head -20
    """
    valid, result_or_error = _validate_command(command)
    if not valid:
        if isinstance(result_or_error, dict) and result_or_error.get("blocked"):
            return {
                "status": "blocked",
                "message": result_or_error["message"],
                "data": {
                    "command": command,
                    "blocked_segment": result_or_error.get("segment", ""),
                    "pattern_suggestion": result_or_error.get("pattern_suggestion", ""),
                    "hint": result_or_error.get("hint", ""),
                },
                "timestamp": _ts(),
            }
        return {"status": "error", "message": result_or_error, "data": None, "timestamp": _ts()}

    safe_cmd = result_or_error

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Failed to load vm_host connections: {e}",
                "data": None, "timestamp": _ts()}

    if not all_conns:
        return {"status": "error",
                "message": "No vm_host connections configured. Add in Settings -> Connections -> vm_host.",
                "data": None, "timestamp": _ts()}

    conn = _resolve_connection(host, all_conns)
    if not conn:
        # Detect ambiguity — distinguish "unknown" from "ambiguous partial".
        all_partials = [c for c in all_conns
                        if host.lower() in c.get("label", "").lower()
                        or c.get("label", "").lower().endswith(host.lower())]
        if len(all_partials) > 1:
            names = sorted({c.get("label") for c in all_partials})
            return {
                "status": "error",
                "message": (
                    f"Ambiguous host reference {host!r} matches {len(all_partials)} "
                    f"connections: {names}. Use the COMPLETE label string."
                ),
                "data": None,
                "timestamp": _ts(),
            }
        labels = [f"{c.get('label', '?')} ({c.get('host', '?')})" for c in all_conns]
        return {"status": "error",
                "message": (
                    f"No vm_host connection found for {host!r}. "
                    f"Available: {', '.join(labels)}. "
                    "Tip: use the connection label exactly, or call infra_lookup() "
                    "to see discovered hostnames."
                ),
                "data": None, "timestamp": _ts()}

    try:
        from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"status": "error", "message": f"Credential resolution failed: {e}",
                "data": None, "timestamp": _ts()}

    try:
        output = _ssh_run(
            conn["host"], conn.get("port") or 22,
            username, password, private_key,
            safe_cmd, jump_host=jump_host,
            _log_meta={"connection_id": str(conn.get("id", "")),
                       "resolved_label": conn.get("label", host),
                       "triggered_by": "vm_exec"},
        )
        label = conn.get("label", host)
        jump_note = f" (via {jump_host['host']})" if jump_host else ""
        return {
            "status": "ok",
            "message": f"Executed on {label}{jump_note}",
            "data": {
                "host":      label,
                "ip":        conn["host"],
                "command":   safe_cmd,
                "output":    output.strip()[:4000],
                "truncated": len(output) > 4000,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {conn.get('label', host)} ({conn['host']}): {e}",
                "data": None, "timestamp": _ts()}


def infra_lookup(query: str = "", platform: str = "") -> dict:
    """Look up infrastructure entities by hostname, IP, alias, or label.

    Searches the infra_inventory automatically populated by collectors
    (vm_hosts, proxmox, swarm). Use to resolve user-provided names to
    actual connections, find IPs, or list all known hosts.

    Args:
        query: hostname, IP address, alias, or partial label to search.
               Leave blank to list all known entities.
        platform: optional filter -- vm_host, proxmox, docker_host, etc.
    """
    try:
        from api.db.infra_inventory import resolve_host, list_inventory

        if query:
            entry = resolve_host(query)
            if entry:
                return {
                    "status": "ok",
                    "message": f"Found: {entry['label']} ({entry.get('hostname') or '?'})",
                    "data": {
                        "connection_id": entry["connection_id"],
                        "platform":      entry["platform"],
                        "label":         entry["label"],
                        "hostname":      entry.get("hostname", ""),
                        "ips":           entry.get("ips", []),
                        "aliases":       entry.get("aliases", []),
                        "meta":          entry.get("meta", {}),
                        "last_discovered": str(entry.get("last_discovered", "")),
                    },
                    "timestamp": _ts(),
                }
            return {"status": "error",
                    "message": f"No infrastructure entity found for {query!r}",
                    "data": None, "timestamp": _ts()}
        else:
            entries = list_inventory(platform=platform)
            summary = [
                {
                    "label":    e["label"],
                    "hostname": e.get("hostname", ""),
                    "ips":      e.get("ips", []),
                    "platform": e["platform"],
                    "meta":     {k: v for k, v in (e.get("meta") or {}).items()
                                 if k in ("os", "role", "os_type")},
                }
                for e in entries
            ]
            return {
                "status": "ok",
                "message": f"{len(summary)} infrastructure entities known",
                "data": {"entities": summary},
                "timestamp": _ts(),
            }
    except Exception as e:
        return {"status": "error", "message": f"infra_lookup error: {e}",
                "data": None, "timestamp": _ts()}


def kafka_exec(broker_label: str, command: str) -> dict:
    """Run a Kafka CLI command inside the kafka container on a specific broker node.

    Finds the vm_host connection matching broker_label, SSHes to that node,
    finds the kafka container, and runs the command inside it.

    Args:
        broker_label: vm_host connection label (e.g. "ds-docker-worker-01")
        command:      Kafka CLI command without 'docker exec <container>' prefix
                      e.g. "kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs"

    Safe commands only: kafka-topics.sh, kafka-consumer-groups.sh,
    kafka-leader-election.sh (PREFERRED only), kafka-log-dirs.sh.
    Blocked: kafka-delete-records, kafka-reassign-partitions (destructive).
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    # Safety: block destructive kafka commands
    BLOCKED = ["delete-records", "reassign-partitions", "--delete", "--reset-offsets"]
    for b in BLOCKED:
        if b in command:
            return {"status": "error",
                    "message": f"Blocked: '{b}' is a destructive Kafka operation. Use Kafka admin directly.",
                    "data": None, "timestamp": _ts()}

    # Find the vm_host connection
    all_conns = get_all_connections_for_platform("vm_host")
    conn = next((c for c in all_conns if c.get("label", "").lower() == broker_label.lower()), None)
    if not conn:
        available = [c.get("label") for c in all_conns]
        return {"status": "error",
                "message": f"No vm_host connection '{broker_label}'. Available: {available}",
                "data": None, "timestamp": _ts()}

    host = conn.get("host", "")
    port = conn.get("port") or 22
    username, password, private_key = _resolve_credentials(conn, all_conns)

    try:
        # SSH to the worker, find the kafka container, exec the command
        find_cmd = "docker ps --filter name=kafka --format '{{.Names}}' | head -1"
        container_name = _ssh_run(host, port, username, password, private_key, find_cmd).strip()
        if not container_name:
            return {"status": "error",
                    "message": f"No kafka container found on {broker_label} ({host})",
                    "data": None, "timestamp": _ts()}

        full_cmd = f"docker exec {container_name} {command}"
        output = _ssh_run(host, port, username, password, private_key, full_cmd)

        return {
            "status": "ok",
            "data": {
                "host": host,
                "container": container_name,
                "command": command,
                "output": output,
            },
            "message": f"Executed on {broker_label} ({host}) in {container_name}",
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None, "timestamp": _ts()}


def swarm_service_force_update(service_name: str, manager_label: str = "") -> dict:
    """Force-update a Docker Swarm service to recover from network/scheduling issues.

    Runs 'docker service update --force <service>' on a Swarm manager node.
    This causes Swarm to reschedule the service with fresh network attachments,
    fixing 'network not found' errors and stale overlay network references.
    Does NOT change the image or configuration — safe for broker recovery.

    Requires plan_action() approval before calling.

    Args:
        service_name:  Exact Swarm service name (e.g. "kafka_broker-2", "logstash_logstash")
        manager_label: vm_host label of a Swarm manager node. If blank, auto-selects
                       the first available manager from vm_host connections.
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    all_conns = get_all_connections_for_platform("vm_host")

    # Resolve manager — explicit label, or find one by role/label pattern
    manager_conn = None
    if manager_label:
        manager_conn = next(
            (c for c in all_conns if c.get("label", "").lower() == manager_label.lower()),
            None
        )
    if not manager_conn:
        # Auto-select: prefer connections with 'manager' in label
        manager_conn = next(
            (c for c in all_conns if 'manager' in c.get("label", "").lower()),
            None
        )
    if not manager_conn:
        return {"status": "error",
                "message": "No Swarm manager vm_host connection found. Add a manager node in Settings → Connections.",
                "data": None, "timestamp": _ts()}

    host = manager_conn.get("host", "")
    port = manager_conn.get("port") or 22
    username, password, private_key = _resolve_credentials(manager_conn, all_conns)

    try:
        output = _ssh_run(
            host, port, username, password, private_key,
            f"docker service update --force {service_name}",
        )
        success = "converged" in output.lower() or "verify" in output.lower()
        return {
            "status": "ok" if success else "error",
            "message": f"Force-updated {service_name} on {manager_conn.get('label')}",
            "data": {
                "service": service_name,
                "manager": manager_conn.get("label"),
                "output": output.strip()[:2000],
                "converged": success,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {manager_conn.get('label')}: {e}",
                "data": None, "timestamp": _ts()}


def swarm_node_status() -> dict:
    """Get Docker Swarm node availability and service task placement.

    Runs 'docker node ls' on a manager to show all nodes with their status.
    Also checks for services with failed/not-running tasks.
    Read-only — never requires plan_action.

    Returns node list with: hostname, status (Ready/Down), availability
    (Active/Drain/Pause), manager status, engine version.
    Also returns any services with tasks not running as expected.
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    all_conns = get_all_connections_for_platform("vm_host")
    manager_conn = next(
        (c for c in all_conns if 'manager' in c.get("label", "").lower()),
        None
    )
    if not manager_conn:
        return {"status": "error",
                "message": "No manager vm_host connection found.",
                "data": None, "timestamp": _ts()}

    host = manager_conn.get("host", "")
    port = manager_conn.get("port") or 22
    username, password, private_key = _resolve_credentials(manager_conn, all_conns)

    try:
        # Get node list
        node_out = _ssh_run(
            host, port, username, password, private_key,
            "docker node ls --format '{{.Hostname}}|{{.Status}}|{{.Availability}}|{{.ManagerStatus}}|{{.EngineVersion}}'",
        )
        nodes = []
        down_nodes = []
        for line in node_out.strip().splitlines():
            parts = line.split("|")
            if len(parts) >= 4:
                hostname, status, avail, mgr_status = parts[0], parts[1], parts[2], parts[3]
                engine = parts[4] if len(parts) > 4 else ""
                nodes.append({
                    "hostname": hostname.strip(),
                    "status": status.strip(),
                    "availability": avail.strip(),
                    "manager_status": mgr_status.strip(),
                    "engine_version": engine.strip(),
                })
                if status.strip().lower() == "down":
                    down_nodes.append(hostname.strip())

        # Get service task failures
        svc_out = _ssh_run(
            host, port, username, password, private_key,
            "docker service ps --filter desired-state=running --format '{{.Name}}|{{.CurrentState}}|{{.Error}}' $(docker service ls -q) 2>/dev/null | grep -v 'Running' | head -20",
        )
        failed_tasks = []
        for line in svc_out.strip().splitlines():
            if line and "|" in line:
                parts = line.split("|")
                failed_tasks.append({
                    "task": parts[0].strip(),
                    "state": parts[1].strip() if len(parts) > 1 else "",
                    "error": parts[2].strip() if len(parts) > 2 else "",
                })

        health = "healthy"
        if down_nodes:
            health = "critical" if len(down_nodes) > 1 else "degraded"

        return {
            "status": "ok",
            "health": health,
            "message": (
                f"{len(nodes)} nodes ({len(down_nodes)} down)"
                + (f" — DOWN: {', '.join(down_nodes)}" if down_nodes else " — all ready")
            ),
            "data": {
                "nodes": nodes,
                "down_nodes": down_nodes,
                "failed_tasks": failed_tasks[:10],
                "manager_used": manager_conn.get("label"),
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"swarm_node_status failed: {e}",
                "data": None, "timestamp": _ts()}


def proxmox_vm_power(vm_label: str, action: str) -> dict:
    """Start, stop, or reboot a Proxmox VM by label.

    Use when a Swarm worker node is completely down (STATUS=Down in docker node ls)
    and cannot be reached via SSH. This talks directly to the Proxmox API.
    Requires plan_action() approval before calling.

    Args:
        vm_label: VM name as shown in Proxmox (e.g. "hp1-prod-worker-03")
                  or the short hostname (e.g. "worker-03")
        action:   "start" | "stop" | "reboot" — reboot is preferred over stop+start
    """
    if action not in ("start", "stop", "reboot"):
        return {"status": "error",
                "message": f"Invalid action '{action}'. Use: start, stop, reboot",
                "data": None, "timestamp": _ts()}

    try:
        from api.connections import get_all_connections_for_platform
        from proxmoxer import ProxmoxAPI

        all_conns = get_all_connections_for_platform("proxmox")
        if not all_conns:
            return {"status": "error",
                    "message": "No Proxmox connection configured.",
                    "data": None, "timestamp": _ts()}

        # Search all Proxmox connections until VM is found
        found = None
        conn = None
        for candidate in all_conns:
            creds = candidate.get("credentials", {})
            try:
                pve = ProxmoxAPI(
                    candidate["host"],
                    port=candidate.get("port", 8006),
                    user=creds.get("user"),
                    token_name=creds.get("token_name"),
                    token_value=creds.get("secret"),
                    verify_ssl=False,
                )
                for node_info in pve.nodes.get():
                    node = node_info["node"]
                    for vm in pve.nodes(node).qemu.get():
                        name = vm.get("name", "")
                        if (vm_label.lower() in name.lower() or
                                name.lower() in vm_label.lower()):
                            found = {"node": node, "vmid": vm["vmid"], "name": name,
                                     "status": vm.get("status")}
                            conn = candidate
                            break
                    if found:
                        break
            except Exception:
                continue
            if found:
                break

        if not found:
            return {"status": "error",
                    "message": f"No VM matching '{vm_label}' found in Proxmox.",
                    "data": None, "timestamp": _ts()}

        node, vmid = found["node"], found["vmid"]
        endpoint = pve.nodes(node).qemu(vmid).status

        if action == "start":
            result = endpoint.start.post()
        elif action == "stop":
            result = endpoint.stop.post()
        else:  # reboot
            result = endpoint.reboot.post()

        return {
            "status": "ok",
            "message": f"{action.capitalize()}ed VM '{found['name']}' (vmid {vmid}) on node {node}",
            "data": {
                "vm_name": found["name"],
                "vmid": vmid,
                "node": node,
                "action": action,
                "task_id": str(result),
                "previous_status": found["status"],
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"proxmox_vm_power failed: {e}",
                "data": None, "timestamp": _ts()}


def service_placement(service_name: str) -> dict:
    """Get task placement for a Swarm service: which node each task is on,
    its current state, and the matching vm_host connection for SSH access.

    Use when a service shows running replicas in Swarm but is behaving incorrectly
    (e.g. Kafka broker shows 1/1 replicas but is not visible in the cluster).
    This bridges: service name → node hostname → vm_host label → SSH-able connection.

    Read-only — never requires plan_action.

    Args:
        service_name: Exact Swarm service name (e.g. "kafka_broker-1", "kafka_broker-2").
                      Also accepts partial name (e.g. "kafka" returns all kafka services).
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    all_conns = get_all_connections_for_platform("vm_host")
    manager_conn = next(
        (c for c in all_conns if 'manager' in c.get("label", "").lower()),
        None
    )
    if not manager_conn:
        return {"status": "error",
                "message": "No manager vm_host connection found.",
                "data": None, "timestamp": _ts()}

    host = manager_conn.get("host", "")
    port = manager_conn.get("port") or 22
    username, password, private_key = _resolve_credentials(manager_conn, all_conns)

    try:
        # Find all matching services
        svc_list_out = _ssh_run(
            host, port, username, password, private_key,
            f"docker service ls --filter name={service_name} --format '{{{{.Name}}}}'",
        )
        services = [s.strip() for s in svc_list_out.strip().splitlines() if s.strip()]

        if not services:
            return {
                "status": "error",
                "message": f"No Swarm service matching '{service_name}' found.",
                "data": None, "timestamp": _ts(),
            }

        placements = []
        for svc in services:
            ps_out = _ssh_run(
                host, port, username, password, private_key,
                f"docker service ps {svc} --no-trunc "
                f"--format '{{{{.Name}}}}|{{{{.Node}}}}|{{{{.CurrentState}}}}|{{{{.DesiredState}}}}|{{{{.Error}}}}'",
            )
            for line in ps_out.strip().splitlines():
                if not line or "|" not in line:
                    continue
                parts = line.split("|")
                task_name    = parts[0].strip() if len(parts) > 0 else ""
                node_name    = parts[1].strip() if len(parts) > 1 else ""
                current_state = parts[2].strip() if len(parts) > 2 else ""
                desired_state = parts[3].strip() if len(parts) > 3 else ""
                error        = parts[4].strip() if len(parts) > 4 else ""

                # Cross-reference node hostname against vm_host connections
                vm_conn = _resolve_connection(node_name, all_conns)
                placements.append({
                    "service":       svc,
                    "task":          task_name,
                    "node":          node_name,
                    "current_state": current_state,
                    "desired_state": desired_state,
                    "error":         error,
                    "vm_host_label": vm_conn.get("label") if vm_conn else None,
                    "vm_host_ip":    vm_conn.get("host") if vm_conn else None,
                    "ssh_ready":     vm_conn is not None,
                })

        # Summary: healthy vs unhealthy tasks
        running = [p for p in placements if "running" in p["current_state"].lower()]
        failed  = [p for p in placements if p["current_state"] and "running" not in p["current_state"].lower()]
        health  = "healthy" if not failed and running else "degraded" if running else "critical"

        return {
            "status": "ok",
            "health": health,
            "message": (
                f"{len(services)} service(s), {len(running)} task(s) running, "
                f"{len(failed)} failed/other"
                + (f" — issues: {'; '.join(p['node'] + ' ' + p['current_state'] for p in failed[:3])}" if failed else "")
            ),
            "data": {
                "placements":    placements,
                "services":      services,
                "running_count": len(running),
                "failed_count":  len(failed),
                "manager_used":  manager_conn.get("label"),
                "hint": (
                    "Use vm_host_label with vm_exec() to SSH to the node. "
                    "Example: vm_exec(host='<vm_host_label>', command='docker ps --filter name=kafka')"
                ) if placements else "",
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"service_placement failed: {e}",
                "data": None, "timestamp": _ts()}


def resolve_entity(query: str) -> dict:
    """Resolve any infrastructure entity name to its identities across all systems.

    Use this BEFORE executing any action that involves an ambiguous entity name.
    The query can be any of: vm_host connection label, IP address, hostname,
    Proxmox VM name, Swarm node name, short alias (e.g. "worker-02", "worker 2",
    "192.168.199.32", "hp1-worker-01", "ds-docker-worker-02").

    Returns all known identities for the entity:
    - vm_host: SSH connection label + IP (what to use with vm_exec)
    - proxmox_vm: VM name, vmid, node (what to use with proxmox_vm_power)
    - swarm node: node name (what to use with swarm_service_force_update)
    - IPs: all known IP addresses for cross-referencing

    If ambiguous (multiple entities match), all candidates are returned.
    If not found, returns an error with a clarifying question to ask the user.

    Args:
        query: Any name, IP, alias, or partial label for the infrastructure entity.
               Examples: "worker-02", "worker 2", "192.168.199.32",
                         "hp1-worker-01", "ds-docker-worker-02", "kafka broker 2"
    """
    # Normalize: "worker 2" → "worker-02", "worker-2" → "worker-02"
    import re as _re
    normalized = _re.sub(r'\s+', '-', query.strip().lower())
    # Also try without leading zeros: "worker-2" as well as "worker-02"
    queries = [query, normalized]
    if _re.search(r'-0*(\d+)$', normalized):
        stripped = _re.sub(r'-0+(\d+)$', r'-\1', normalized)
        if stripped not in queries:
            queries.append(stripped)

    try:
        from api.db.infra_inventory import resolve_entity as _resolve

        # Try each normalized form
        result = None
        for q in queries:
            result = _resolve(q)
            if result and result.get("found"):
                break

        if not result or not result.get("found"):
            # Try a broader search via connections table
            from api.connections import get_all_connections_for_platform
            all_platforms = ["vm_host", "docker_host", "proxmox"]
            all_conns = []
            for plat in all_platforms:
                try:
                    all_conns.extend(get_all_connections_for_platform(plat))
                except Exception:
                    pass
            q_lower = query.lower()
            partial = [c for c in all_conns
                       if q_lower in c.get("label", "").lower()
                       or c.get("host", "") == query]
            if partial:
                return {
                    "status": "ok",
                    "message": f"Found {len(partial)} connection(s) matching '{query}' (no inventory entry yet)",
                    "data": {
                        "query": query,
                        "found": True,
                        "identities": {
                            c["platform"]: [{
                                "label": c.get("label", ""),
                                "host": c.get("host", ""),
                                "connection_id": str(c.get("id", "")),
                            }] for c in partial
                        },
                        "clarifying_question": (
                            f"Found {len(partial)} connection(s): "
                            + ", ".join(f"{c.get('label')} ({c.get('host')})" for c in partial[:5])
                            + ". Which one did you mean?"
                        ) if len(partial) > 1 else None,
                    },
                    "timestamp": _ts(),
                }
            return {
                "status": "error",
                "message": f"No infrastructure entity found for '{query}'",
                "data": {
                    "query": query,
                    "found": False,
                    "clarifying_question": (
                        f"I couldn't find any infrastructure entity matching '{query}'. "
                        "Could you provide more context? For example: the IP address, "
                        "the Proxmox VM name, the connection label from Settings → Connections, "
                        "or the Swarm node name."
                    ),
                },
                "timestamp": _ts(),
            }

        # Format a clean human summary
        identities = result.get("identities", {})
        vm_host_ids = identities.get("vm_host", [])
        proxmox_ids = identities.get("proxmox_vm", [])
        connection_ids = [i for plat, ids in identities.items()
                         for i in ids if plat not in ("vm_host", "proxmox_vm", "proxmox_lxc")]

        summary_parts = []
        if vm_host_ids:
            summary_parts.append(f"vm_host: {vm_host_ids[0].get('label')} ({', '.join(result.get('ips', []))})")
        if proxmox_ids:
            p = proxmox_ids[0]
            summary_parts.append(f"proxmox: {p.get('label')} (vmid {p.get('vmid')}, node {p.get('node')})")

        return {
            "status": "ok",
            "message": f"Resolved '{query}' → {result.get('canonical_label')}. " + " | ".join(summary_parts),
            "data": {
                "query": query,
                "found": True,
                "canonical_label": result.get("canonical_label", ""),
                "hostname": result.get("hostname", ""),
                "ips": result.get("ips", []),
                "identities": identities,
                # Convenience: pre-resolved values for common operations
                "vm_exec_host": vm_host_ids[0].get("label") if vm_host_ids else None,
                "proxmox_vm_label": proxmox_ids[0].get("label") if proxmox_ids else None,
                "proxmox_vmid": proxmox_ids[0].get("vmid") if proxmox_ids else None,
                "proxmox_node": proxmox_ids[0].get("node") if proxmox_ids else None,
            },
            "timestamp": _ts(),
        }

    except Exception as e:
        return {"status": "error", "message": f"resolve_entity failed: {e}",
                "data": None, "timestamp": _ts()}


def ssh_capabilities(host: str = "", days: int = 7) -> dict:
    """Query the SSH capability map — which credentials can reach which hosts.

    Returns verified credential→host pairs with success rates and latency.
    Use to understand available SSH access before planning operations,
    or to audit which credentials have broad access.

    Args:
        host: optional target host to filter by (label or IP). Blank = all.
        days: look-back window in days (default 7, max 90).
    """
    try:
        from api.db.ssh_capabilities import query_capabilities, get_capability_summary
        if host:
            target = host
            try:
                from api.db.infra_inventory import resolve_host
                entry = resolve_host(host)
                if entry and entry.get("ips"):
                    target = entry["ips"][0]
            except Exception:
                pass
            rows = query_capabilities(target_host=target, days=days)
            if not rows:
                rows = [r for r in query_capabilities(days=days)
                        if host.lower() in (r.get("resolved_label", "") or "").lower()
                        or host.lower() in (r.get("target_host", "") or "").lower()]
        else:
            rows = query_capabilities(verified_only=True, days=days)

        summary = get_capability_summary()
        return {
            "status": "ok",
            "message": f"{len(rows)} credential→host pair(s)" + (f" for {host!r}" if host else "") + f" (last {days}d)",
            "data": {
                "pairs": [{"credential_label": r.get("resolved_label") or r.get("target_host"),
                           "target_host": r.get("target_host"), "username": r.get("username"),
                           "verified": r.get("verified"),
                           "last_success": str(r.get("last_success", ""))[:19],
                           "success_rate_pct": r.get("success_rate_pct", 0),
                           "avg_latency_ms": r.get("avg_latency_ms"),
                           "jump_host": r.get("jump_host"),
                           "new_host_alert": r.get("new_host_alert", False),
                           "attempts_7d": r.get("attempts_7d", 0)} for r in rows[:20]],
                "summary": summary,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"ssh_capabilities error: {e}", "data": None, "timestamp": _ts()}


def vm_exec_allowlist_request(command: str, reason: str, scope: str = "session") -> dict:
    """Request approval to add a blocked command to the vm_exec allowlist.

    Call this when vm_exec returns status='blocked'. It suggests a regex pattern
    and returns instructions for the approval flow.

    Flow after calling this tool:
    1. Call plan_action() with the suggested pattern and reason
    2. After user approves, call vm_exec_allowlist_add() with the pattern
    3. Retry vm_exec() with the original command

    Args:
        command: The full command that was blocked (e.g. "ss -tlnp")
        reason:  Why this command is needed for the current task
        scope:   'session' (expires when this session ends) or 'permanent' (persists)
    """
    if scope not in ("session", "permanent"):
        scope = "session"

    suggestion = _suggest_pattern(command.strip().split()[0] if command.strip() else command)

    # Also try to load similar existing patterns for context
    existing_context = ""
    try:
        from api.db.vm_exec_allowlist import list_all
        patterns = list_all(include_base=True)
        similar = [p["pattern"] for p in patterns
                   if command.strip().split()[0].lower() in p.get("description", "").lower()]
        if similar:
            existing_context = f" (similar patterns already allowed: {similar[:2]})"
    except Exception:
        pass

    scope_note = (
        "This session only — pattern will be deleted when the session ends."
        if scope == "session" else
        "Permanent — pattern will persist across sessions and be visible in Settings → Allowlist."
    )

    return {
        "status": "ok",
        "message": f"Allowlist request prepared for: {command!r}",
        "data": {
            "command": command,
            "reason": reason,
            "scope": scope,
            "scope_note": scope_note,
            "suggested_pattern": suggestion,
            "existing_context": existing_context,
            "next_steps": [
                f"1. Call plan_action(summary='Add {command!r} to vm_exec allowlist ({scope})', "
                f"steps=['Add pattern: {suggestion}', 'Scope: {scope}', 'Reason: {reason}'], "
                f"risk_level='low', reversible=True)",
                f"2. After approval: call vm_exec_allowlist_add(pattern={suggestion!r}, "
                f"description={reason!r}, scope={scope!r})",
                "3. Retry: call vm_exec() with the original command",
            ],
        },
        "timestamp": _ts(),
    }


def vm_exec_allowlist_add(pattern: str, description: str,
                          scope: str = "session", session_id: str = "") -> dict:
    """Add a pattern to the vm_exec allowlist after plan_action approval.

    Only call this AFTER the user has approved via plan_action().
    For session scope, the pattern is automatically deleted when the session ends.
    For permanent scope, it persists and appears in Settings → Allowlist.

    Args:
        pattern:     Regex pattern to allow (e.g. r'^ss\\b'). Use the suggested_pattern
                     from vm_exec_allowlist_request().
        description: Human-readable description of what the pattern allows.
        scope:       'session' (expires with this session) or 'permanent' (persists).
        session_id:  Current session ID (required for session scope — use the session_id
                     from the current agent context if known, or leave blank).
    """
    import re as _re
    # Validate the pattern compiles
    try:
        _re.compile(pattern)
    except _re.error as e:
        return {"status": "error", "message": f"Invalid regex pattern: {e}",
                "data": None, "timestamp": _ts()}

    try:
        from api.db.vm_exec_allowlist import add_pattern
        result = add_pattern(
            pattern=pattern,
            description=description,
            scope=scope,
            session_id=session_id,
            added_by="agent",
            approved_by="user",
        )
        if result.get("ok"):
            return {
                "status": "ok",
                "message": f"Pattern {pattern!r} added ({scope}). Retry vm_exec() now.",
                "data": result,
                "timestamp": _ts(),
            }
        return {"status": "error", "message": result.get("error", "Failed to add pattern"),
                "data": None, "timestamp": _ts()}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None, "timestamp": _ts()}


def vm_exec_allowlist_list() -> dict:
    """Show all vm_exec allowlist patterns — base (built-in) and custom (user-added).

    Use to understand what commands are currently allowed before attempting vm_exec,
    or to verify a pattern was successfully added after vm_exec_allowlist_add().
    """
    try:
        from api.db.vm_exec_allowlist import list_all
        patterns = list_all(include_base=True)
        base = [p for p in patterns if p.get("is_base")]
        custom = [p for p in patterns if not p.get("is_base")]
        session = [p for p in custom if p.get("scope") == "session"]
        permanent = [p for p in custom if p.get("scope") == "permanent"]
        return {
            "status": "ok",
            "message": f"{len(patterns)} patterns ({len(base)} base, {len(permanent)} custom permanent, {len(session)} session)",
            "data": {
                "total": len(patterns),
                "base_count": len(base),
                "custom_permanent": permanent,
                "custom_session": session,
                "base_sample": [p["pattern"] for p in base[:10]],
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"vm_exec_allowlist_list failed: {e}",
                "data": None, "timestamp": _ts()}
