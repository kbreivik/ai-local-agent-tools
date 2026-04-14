"""Runbooks — saved step-by-step procedures, created from manual checklist completions
or agent proposals. Searchable by agents via runbook_search() tool."""
import json
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS runbooks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    steps       JSONB NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT 'manual_completion',
    proposal_id TEXT NOT NULL DEFAULT '',
    tags        TEXT[] NOT NULL DEFAULT '{}',
    run_count   INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT 'user',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_runbooks_source ON runbooks(source);
CREATE INDEX IF NOT EXISTS idx_runbooks_tags   ON runbooks USING gin(tags);
"""

_initialized = False

def _ts():
    return datetime.now(timezone.utc).isoformat()

# ── Base runbooks — seeded on startup, always available to agents ──────────────
BASE_RUNBOOKS = [
    {
        "title": "Kafka broker missing — worker node recovery",
        "description": (
            "Standard procedure when a Kafka broker is missing from the cluster "
            "because the underlying Docker Swarm worker node is Down. "
            "Covers: VM reboot via Proxmox, node reattachment verification, "
            "broker reschedule, and ISR health check."
        ),
        "tags": ["kafka", "broker", "swarm", "worker", "recovery", "proxmox"],
        "steps": [
            {"order": 1, "tool": "swarm_node_status",
             "description": "Check all Swarm nodes — identify which worker is Down",
             "command": "swarm_node_status()"},
            {"order": 2, "tool": "service_placement",
             "description": "Confirm which Kafka broker task is unscheduled",
             "command": "service_placement(service_name='kafka_broker-3')"},
            {"order": 3, "tool": "plan_action", "requires_plan": True,
             "description": "Plan: reboot the Down worker VM via Proxmox",
             "command": "plan_action(summary='Reboot worker-03 via Proxmox to recover kafka_broker-3', steps=['proxmox_vm_power reboot'], risk_level='medium', reversible=True)"},
            {"order": 4, "tool": "proxmox_vm_power", "requires_plan": True,
             "description": "Reboot the Down worker VM (replace label with actual)",
             "command": "proxmox_vm_power(vm_label='ds-docker-worker-03', action='reboot')"},
            {"order": 5, "tool": None,
             "description": "Wait ~2 minutes for VM boot and Swarm node reattachment",
             "command": None, "wait_seconds": 120},
            {"order": 6, "tool": "swarm_node_status",
             "description": "Verify the worker node is Ready",
             "command": "swarm_node_status()"},
            {"order": 7, "tool": "service_placement",
             "description": "Confirm kafka_broker task scheduled on recovered node",
             "command": "service_placement(service_name='kafka_broker-3')"},
            {"order": 8, "tool": "kafka_broker_status",
             "description": "Verify 3/3 brokers online, ISR healthy, no under-replicated partitions",
             "command": "kafka_broker_status()"},
        ],
    },
    {
        "title": "Docker disk cleanup — reclaim space on VM host",
        "description": (
            "Remove unused Docker images, stopped containers, and dangling volumes "
            "to reclaim disk space on a VM host. Always measure before and after. "
            "Requires plan_action before prune operations."
        ),
        "tags": ["disk", "docker", "cleanup", "prune", "storage", "vm_host"],
        "steps": [
            {"order": 1, "tool": "docker_df",
             "description": "Measure current Docker disk usage (before)",
             "command": "docker_df()"},
            {"order": 2, "tool": "vm_disk_investigate",
             "description": "Run full disk investigation to identify top consumers",
             "command": "vm_disk_investigate(host='<vm_host_label>')"},
            {"order": 3, "tool": "plan_action", "requires_plan": True,
             "description": "Plan: prune unused images and containers",
             "command": "plan_action(summary='Docker prune on <host>', steps=['docker_prune images', 'docker_prune containers'], risk_level='low', reversible=False)"},
            {"order": 4, "tool": "docker_prune", "requires_plan": True,
             "description": "Prune unused Docker images",
             "command": "docker_prune(host='<vm_host_label>', target='images')"},
            {"order": 5, "tool": "vm_exec", "requires_plan": True,
             "description": "Vacuum systemd journal logs if >500MB (check df first)",
             "command": "vm_exec(host='<vm_host_label>', command='journalctl --vacuum-size=500M')"},
            {"order": 6, "tool": "docker_df",
             "description": "Measure Docker disk usage after cleanup (confirm reclaimed)",
             "command": "docker_df()"},
        ],
    },
    {
        "title": "Swarm service not converging — force update to clear network state",
        "description": (
            "A Swarm service is stuck: task failing on wrong node, exit-code loops, "
            "or network overlay stale state. Force update clears overlay network assignments "
            "and reschedules the task cleanly. Use when service_placement shows repeated failures."
        ),
        "tags": ["swarm", "service", "force-update", "stuck", "convergence", "overlay"],
        "steps": [
            {"order": 1, "tool": "service_placement",
             "description": "Check task placement, state, and error message",
             "command": "service_placement(service_name='<service>')"},
            {"order": 2, "tool": "swarm_node_status",
             "description": "Verify all nodes are Ready (not Down)",
             "command": "swarm_node_status()"},
            {"order": 3, "tool": "vm_exec",
             "description": "View full task history with error messages",
             "command": "vm_exec(host='<manager_label>', command='docker service ps <service> --no-trunc')"},
            {"order": 4, "tool": "plan_action", "requires_plan": True,
             "description": "Plan: force-update the service to clear overlay state",
             "command": "plan_action(summary='Force-update <service> to clear network state', steps=['swarm_service_force_update'], risk_level='low', reversible=True)"},
            {"order": 5, "tool": "swarm_service_force_update", "requires_plan": True,
             "description": "Force update the service",
             "command": "swarm_service_force_update(service_name='<service>')"},
            {"order": 6, "tool": "service_placement",
             "description": "Verify task is Running on a healthy node (~30s after force-update)",
             "command": "service_placement(service_name='<service>')"},
        ],
    },
    {
        "title": "Worker node reintegration after manual reboot",
        "description": (
            "After manually rebooting a Swarm worker (via Proxmox UI, SSH, or other means), "
            "verify it rejoins the cluster and all affected services reschedule correctly. "
            "Force-update any service still stuck after node recovery."
        ),
        "tags": ["swarm", "worker", "node", "reintegration", "reboot", "recovery"],
        "steps": [
            {"order": 1, "tool": "swarm_node_status",
             "description": "Confirm all Swarm nodes are Ready",
             "command": "swarm_node_status()"},
            {"order": 2, "tool": "kafka_broker_status",
             "description": "Check if Kafka cluster re-formed with all 3 brokers",
             "command": "kafka_broker_status()"},
            {"order": 3, "tool": "service_list",
             "description": "Identify any services not at desired replica count",
             "command": "service_list()"},
            {"order": 4, "tool": "service_placement",
             "description": "For each degraded service, check placement and error",
             "command": "service_placement(service_name='<service>')"},
            {"order": 5, "tool": "plan_action", "requires_plan": True,
             "description": "Plan: force-update services not converging",
             "command": "plan_action(summary='Force-update stuck services post-reboot', steps=['swarm_service_force_update x N'], risk_level='low', reversible=True)"},
            {"order": 6, "tool": "swarm_service_force_update", "requires_plan": True,
             "description": "Force-update each service not at desired replicas",
             "command": "swarm_service_force_update(service_name='<service>')"},
            {"order": 7, "tool": "kafka_broker_status",
             "description": "Final check: Kafka fully healthy, 0 under-replicated partitions",
             "command": "kafka_broker_status()"},
        ],
    },
]


def init_runbooks():
    global _initialized
    if _initialized: return
    try:
        from api.connections import _get_conn
        conn = _get_conn(); conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("runbooks table ready")
        # Seed base runbooks after table is ready
        seed_base_runbooks()
    except Exception as e:
        log.warning("runbooks init failed: %s", e)


def seed_base_runbooks() -> int:
    """Insert BASE_RUNBOOKS into DB if not already present (idempotent on title).
    Returns count of newly inserted runbooks."""
    inserted = 0
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        for rb in BASE_RUNBOOKS:
            # Check if a runbook with this title already exists
            cur.execute("SELECT id FROM runbooks WHERE title = %s", (rb["title"],))
            if cur.fetchone():
                continue  # already seeded
            rid = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO runbooks
                   (id, title, description, steps, source, tags, created_by)
                   VALUES (%s,%s,%s,%s,'system_base',%s,'system')""",
                (rid, rb["title"], rb["description"],
                 json.dumps(rb["steps"]), rb["tags"]),
            )
            inserted += 1
        conn.commit()
        cur.close()
        conn.close()
        if inserted:
            log.info("runbooks: seeded %d base runbook(s)", inserted)
    except Exception as e:
        log.debug("seed_base_runbooks failed: %s", e)
    return inserted

def create_runbook(title: str, description: str, steps: list,
                   source: str = "manual_completion", proposal_id: str = "",
                   tags: list = None, created_by: str = "user") -> str:
    """Insert a new runbook. Returns the runbook ID."""
    rid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """INSERT INTO runbooks
               (id, title, description, steps, source, proposal_id, tags, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid, title, description, json.dumps(steps),
             source, proposal_id or "", tags or [], created_by),
        )
        conn.commit(); cur.close(); conn.close()
        return rid
    except Exception as e:
        log.debug("create_runbook failed: %s", e)
        return ""

def search_runbooks(query: str, limit: int = 5) -> list:
    """Full-text search on title + description + tags. Used by runbook_search() tool."""
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, title, description, steps, source, tags, run_count, created_at
               FROM runbooks
               WHERE title ILIKE %s OR description ILIKE %s
                  OR %s = ANY(tags)
               ORDER BY run_count DESC, created_at DESC
               LIMIT %s""",
            (f"%{query}%", f"%{query}%", query.lower(), limit),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [
            {"id": r[0], "title": r[1], "description": r[2],
             "steps": r[3] or [], "source": r[4], "tags": list(r[5] or []),
             "run_count": r[6], "created_at": r[7].isoformat() if r[7] else ""}
            for r in rows
        ]
    except Exception as e:
        log.debug("search_runbooks failed: %s", e)
        return []

def list_runbooks(limit: int = 50) -> list:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, title, description, steps, source, tags, run_count, created_by, created_at
               FROM runbooks ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [
            {"id": r[0], "title": r[1], "description": r[2],
             "steps": r[3] or [], "source": r[4], "tags": list(r[5] or []),
             "run_count": r[6], "created_by": r[7],
             "created_at": r[8].isoformat() if r[8] else ""}
            for r in rows
        ]
    except Exception as e:
        log.debug("list_runbooks failed: %s", e)
        return []

def delete_runbook(runbook_id: str) -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM runbooks WHERE id=%s", (runbook_id,))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("delete_runbook failed: %s", e)
        return False

def increment_run_count(runbook_id: str):
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            "UPDATE runbooks SET run_count=run_count+1, updated_at=NOW() WHERE id=%s",
            (runbook_id,),
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass
