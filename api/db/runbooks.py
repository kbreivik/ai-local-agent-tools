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

-- v2.35.4 — triage classifier routing columns
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS triage_keywords TEXT[] DEFAULT '{}';
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS applies_to_agent_types TEXT[] DEFAULT '{}';
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS priority INT DEFAULT 100;
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS body_md TEXT;
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS last_edited_by TEXT;
ALTER TABLE runbooks ADD COLUMN IF NOT EXISTS last_edited_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS idx_runbooks_name ON runbooks(name) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runbooks_active_priority
    ON runbooks(is_active, priority)
    WHERE is_active = TRUE;
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
    {
        "title": "Diagnose container overlay reachability",
        "description": (
            "Procedure for overlay / hairpin-NAT / 'container cannot reach "
            "another service' investigations. Uses the v2.34.12 "
            "container-introspection tools to compare overlay network "
            "membership and probe TCP reachability from INSIDE the "
            "client container's netns — the only definitive test."
        ),
        "tags": ["overlay", "hairpin", "network", "container", "reachability",
                 "broker-unreachable", "socket-timeout"],
        "steps": [
            {"order": 1, "tool": "container_discover_by_service",
             "description": "Get running container IDs for both endpoints",
             "command": "container_discover_by_service(service_name='<service>')"},
            {"order": 2, "tool": "container_networks",
             "description": "Compare overlay network memberships for each container",
             "command": "container_networks(host='<vm_host_label>', container_id='<id>')"},
            {"order": 3, "tool": "container_tcp_probe",
             "description": "Definitive reachability test from client netns",
             "command": "container_tcp_probe(host='<client-host>', container_id='<client-id>', target_host='<server-ip>', target_port=<port>)"},
            {"order": 4, "tool": "container_config_read",
             "description": "(If probe fails) check client config for the address it's trying",
             "command": "container_config_read(host='<host>', container_id='<id>', path='/etc/<app>/<config>')"},
            {"order": 5, "tool": "container_env",
             "description": "(If config hasn't identified it) check bootstrap env vars",
             "command": "container_env(host='<host>', container_id='<id>', grep_pattern='BOOTSTRAP')"},
            {"order": 6, "tool": None,
             "description": (
                 "Manual: if probe fails from client netns but succeeds from host "
                 "→ hairpin-NAT/overlay routing issue. Workaround: move one "
                 "container to a different node (docker service update "
                 "--constraint-add). Proper fix: attach client to the same overlay "
                 "as server; use internal listener addresses."
             ),
             "command": None},
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
        # v2.35.4 — seed triage-classifier runbooks (idempotent)
        try:
            seed_triage_runbooks()
        except Exception as e:
            log.debug("seed_triage_runbooks skipped: %s", e)
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


# ── Triage runbook helpers (v2.35.4) ──────────────────────────────────────────
# These operate on the extended columns (name, triage_keywords, body_md, etc.)
# Used by the runbook classifier (api/agents/runbook_classifier.py) and the
# runbook editor UI/API.

_TRIAGE_SELECT_COLS = (
    "id, name, title, description, tags, "
    "triage_keywords, applies_to_agent_types, is_active, priority, body_md, "
    "last_edited_by, last_edited_at, created_by, created_at, updated_at"
)


def _triage_row_to_dict(r) -> dict:
    return {
        "id":                     r[0],
        "name":                   r[1] or "",
        "title":                  r[2],
        "description":            r[3] or "",
        "tags":                   list(r[4] or []),
        "triage_keywords":        list(r[5] or []),
        "applies_to_agent_types": list(r[6] or []),
        "is_active":              bool(r[7]),
        "priority":               int(r[8]) if r[8] is not None else 100,
        "body_md":                r[9] or "",
        "last_edited_by":         r[10] or "",
        "last_edited_at":         r[11].isoformat() if r[11] else "",
        "created_by":             r[12] or "",
        "created_at":             r[13].isoformat() if r[13] else "",
        "updated_at":             r[14].isoformat() if r[14] else "",
    }


def get_runbook_by_name(name: str) -> dict | None:
    """Return the runbook with the given `name` column or None."""
    if not name:
        return None
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            f"SELECT {_TRIAGE_SELECT_COLS} FROM runbooks WHERE name=%s LIMIT 1",
            (name,),
        )
        row = cur.fetchone(); cur.close(); conn.close()
        return _triage_row_to_dict(row) if row else None
    except Exception as e:
        log.debug("get_runbook_by_name failed: %s", e)
        return None


def get_runbook_by_id(runbook_id: str) -> dict | None:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            f"SELECT {_TRIAGE_SELECT_COLS} FROM runbooks WHERE id=%s LIMIT 1",
            (runbook_id,),
        )
        row = cur.fetchone(); cur.close(); conn.close()
        return _triage_row_to_dict(row) if row else None
    except Exception as e:
        log.debug("get_runbook_by_id failed: %s", e)
        return None


def list_active_runbooks_for_agent_type(agent_type: str) -> list:
    """Return active runbooks (with body_md set) that target agent_type."""
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        # PostgreSQL: `%s = ANY(column)` — use '' as sentinel for 'any agent type'
        cur.execute(
            f"""SELECT {_TRIAGE_SELECT_COLS}
                FROM runbooks
                WHERE is_active = TRUE
                  AND body_md IS NOT NULL
                  AND body_md <> ''
                  AND (applies_to_agent_types = '{{}}' OR %s = ANY(applies_to_agent_types))
                ORDER BY priority ASC, name ASC""",
            (agent_type,),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_triage_row_to_dict(r) for r in rows]
    except Exception as e:
        log.debug("list_active_runbooks_for_agent_type failed: %s", e)
        return []


def list_triage_runbooks(limit: int = 200) -> list:
    """List runbooks that have triage-classifier metadata (name set)."""
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            f"""SELECT {_TRIAGE_SELECT_COLS}
                FROM runbooks
                WHERE name IS NOT NULL AND name <> ''
                ORDER BY priority ASC, name ASC
                LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [_triage_row_to_dict(r) for r in rows]
    except Exception as e:
        log.debug("list_triage_runbooks failed: %s", e)
        return []


def create_triage_runbook(
    name: str,
    title: str,
    body_md: str,
    triage_keywords: list | None = None,
    applies_to_agent_types: list | None = None,
    priority: int = 100,
    is_active: bool = True,
    description: str = "",
    tags: list | None = None,
    created_by: str = "user",
) -> str:
    """Insert a new triage-classifier runbook. Returns id or '' on failure."""
    rid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """INSERT INTO runbooks
               (id, name, title, description, steps, source, tags,
                triage_keywords, applies_to_agent_types, is_active, priority,
                body_md, created_by, last_edited_by, last_edited_at)
               VALUES (%s,%s,%s,%s,'[]'::jsonb,'triage_seed',%s,
                       %s,%s,%s,%s,%s,%s,%s,NOW())""",
            (rid, name, title, description, tags or [],
             triage_keywords or [], applies_to_agent_types or [],
             bool(is_active), int(priority), body_md,
             created_by, created_by),
        )
        conn.commit(); cur.close(); conn.close()
        return rid
    except Exception as e:
        log.debug("create_triage_runbook failed: %s", e)
        return ""


def update_triage_runbook(
    runbook_id: str,
    *,
    title: str | None = None,
    body_md: str | None = None,
    triage_keywords: list | None = None,
    applies_to_agent_types: list | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    tags: list | None = None,
    edited_by: str = "user",
) -> bool:
    """Partial update — only non-None fields are written. Touches last_edited_*."""
    sets: list[str] = []
    params: list = []
    if title is not None:
        sets.append("title=%s"); params.append(title)
    if body_md is not None:
        sets.append("body_md=%s"); params.append(body_md)
    if triage_keywords is not None:
        sets.append("triage_keywords=%s"); params.append(list(triage_keywords))
    if applies_to_agent_types is not None:
        sets.append("applies_to_agent_types=%s"); params.append(list(applies_to_agent_types))
    if priority is not None:
        sets.append("priority=%s"); params.append(int(priority))
    if is_active is not None:
        sets.append("is_active=%s"); params.append(bool(is_active))
    if description is not None:
        sets.append("description=%s"); params.append(description)
    if tags is not None:
        sets.append("tags=%s"); params.append(list(tags))
    if not sets:
        return True  # nothing to update

    sets.append("last_edited_by=%s"); params.append(edited_by)
    sets.append("last_edited_at=NOW()")
    sets.append("updated_at=NOW()")
    params.append(runbook_id)
    sql = f"UPDATE runbooks SET {', '.join(sets)} WHERE id=%s"
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(sql, tuple(params))
        ok = cur.rowcount > 0
        conn.commit(); cur.close(); conn.close()
        return ok
    except Exception as e:
        log.debug("update_triage_runbook failed: %s", e)
        return False


# ── Triage runbook seeds (v2.35.4) ────────────────────────────────────────────
# Source of truth for the content remains in api/agents/router.py section blocks.
# We extract the body text at seed time so the runbook rows track the prompt.

_TRIAGE_RUNBOOK_SPECS = [
    {
        "name":   "kafka_triage",
        "title":  "Kafka triage — STEP 0",
        "description": "Mandatory first-step triage for Kafka degradation investigations.",
        "triage_keywords": ["kafka", "broker", "consumer lag", "under-replicated", "ISR"],
        "applies_to_agent_types": ["research", "investigate", "status", "observe"],
        "priority": 10,
        "_extract_section": "kafka_triage",
        "_fallback_body_md": (
            "KAFKA TRIAGE — STEP 0 (MANDATORY):\n"
            "kafka_broker_status and kafka_consumer_lag are INDEPENDENT checks.\n"
            "Call BOTH before drawing any conclusions.\n"
            "  Call 1: kafka_broker_status() — broker / ISR health\n"
            "  Call 2: kafka_consumer_lag() — consumer groups\n"
            "Only after BOTH calls can you determine the degradation type.\n"
        ),
    },
    {
        "name":   "consumer_lag_path",
        "title":  "Consumer lag diagnostic path",
        "description": "Step-by-step consumer-lag investigation for the Logstash consumer group.",
        "triage_keywords": ["consumer lag", "lag", "not consuming", "partition lag"],
        "applies_to_agent_types": ["research", "investigate"],
        "priority": 20,
        "_extract_section": "consumer_lag_path",
        "_fallback_body_md": (
            "CONSUMER LAG PATH:\n"
            "1. container_discover_by_service(\"logstash_logstash\")\n"
            "2. vm_exec(host=<vm_host_label>, command=\"docker logs <container_id> --tail 100\")\n"
            "3. elastic_cluster_health()\n"
            "4. kafka_exec(broker_label=<worker>, command=\"kafka-consumer-groups.sh ...\")\n"
        ),
    },
    {
        "name":   "broker_missing_path",
        "title":  "Broker missing diagnostic path",
        "description": "Investigate a kafka broker reported missing from the cluster.",
        "triage_keywords": ["broker missing", "broker down", "unscheduled broker"],
        "applies_to_agent_types": ["research", "investigate"],
        "priority": 20,
        "_extract_section": "broker_missing_path",
        "_fallback_body_md": (
            "BROKER MISSING PATH:\n"
            "1. kafka_broker_status() — which broker ID is missing\n"
            "2. swarm_node_status() — any worker node Down?\n"
            "3. container_discover_by_service(\"kafka_broker-N\")\n"
            "4. kafka_exec(broker_label=<node>, command=\"kafka-topics.sh ...\")\n"
            "5. elastic_kafka_logs() — historical error patterns\n"
        ),
    },
    {
        "name":   "overlay_hairpin_diagnosis",
        "title":  "Overlay network / hairpin diagnosis",
        "description": "Canonical sequence for 'client container A cannot reach service on container B'.",
        "triage_keywords": ["overlay", "hairpin", "docker network", "cross-network", "tcp_probe"],
        "applies_to_agent_types": ["research", "investigate"],
        "priority": 15,
        "_extract_section": "overlay_hairpin_diagnosis",
        "_fallback_body_md": (
            "OVERLAY-LAYER DIAGNOSIS:\n"
            "1. container_discover_by_service(<client>) and (<server>) — get IDs\n"
            "2. container_networks(host, <id>) for each — compare overlay memberships\n"
            "3. container_tcp_probe(host, <client_id>, <target>, <port>) — definitive answer\n"
            "4. If probe fails from client netns but succeeds from host → hairpin-NAT issue\n"
        ),
    },
    {
        "name":   "container_introspect_first",
        "title":  "Container introspection — prefer typed tools",
        "description": "Use typed container_* tools before reaching for raw docker exec.",
        "triage_keywords": ["container", "docker exec", "inside container"],
        "applies_to_agent_types": ["research", "investigate", "action", "execute"],
        "priority": 30,
        "_extract_section": "container_introspect_first",
        "_fallback_body_md": (
            "CONTAINER INTROSPECT FIRST:\n"
            "Prefer container_config_read, container_env, container_tcp_probe,\n"
            "container_networks, container_discover_by_service over raw\n"
            "`docker exec <id> ...` shells. They validate args up front, bypass\n"
            "the vm_exec metachar filter, and return structured JSON.\n"
        ),
    },
]


# Header-marker mapping — used to extract body_md verbatim from router.py.
# Start token, end token (exclusive) — pulls everything in between.
_SECTION_MARKERS = {
    "kafka_triage": (
        "KAFKA TRIAGE — STEP 0 (MANDATORY):",
        "CONSUMER LAG PATH (when message contains \"consumer lag\"):",
    ),
    "consumer_lag_path": (
        "CONSUMER LAG PATH (when message contains \"consumer lag\"):",
        "BROKER MISSING PATH (when message contains \"broker N missing\"):",
    ),
    "broker_missing_path": (
        "BROKER MISSING PATH (when message contains \"broker N missing\"):",
        "REPLICATION PATH (when message contains \"under-replicated\"):",
    ),
    "overlay_hairpin_diagnosis": (
        "OVERLAY-LAYER DIAGNOSIS (canonical sequence for \"client inside",
        "═══ CONTAINER INTROSPECTION (v2.34.12) ═══",
    ),
    "container_introspect_first": (
        "═══ CONTAINER INTROSPECT FIRST — BEFORE RAW docker exec ═══",
        "OVERLAY-LAYER DIAGNOSIS (canonical sequence for \"client inside",
    ),
}


def _extract_section_from_router(section_key: str) -> str:
    """Best-effort extractor — read api/agents/router.py and pull out the
    text between the start and end markers for `section_key`. Returns '' on
    miss so the caller can fall back to a baked-in body_md."""
    markers = _SECTION_MARKERS.get(section_key)
    if not markers:
        return ""
    start, end = markers
    try:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        router_path = os.path.normpath(os.path.join(here, "..", "agents", "router.py"))
        with open(router_path, "r", encoding="utf-8") as f:
            source = f.read()
        s = source.find(start)
        if s < 0:
            return ""
        e = source.find(end, s + len(start))
        if e < 0:
            return ""
        body = source[s:e].rstrip()
        # Strip a trailing triple-quote fragment if we happen to catch one.
        return body
    except Exception as ex:
        log.debug("_extract_section_from_router(%s) failed: %s", section_key, ex)
        return ""


def seed_triage_runbooks() -> int:
    """Idempotent seed. Only inserts if name doesn't exist."""
    inserted = 0
    for spec in _TRIAGE_RUNBOOK_SPECS:
        try:
            if get_runbook_by_name(spec["name"]):
                continue
            body_md = _extract_section_from_router(spec["_extract_section"])
            if not body_md:
                log.warning(
                    "seed_triage_runbooks: extraction failed for %s — "
                    "using fallback body", spec["name"],
                )
                body_md = spec["_fallback_body_md"]
            rid = create_triage_runbook(
                name=spec["name"],
                title=spec["title"],
                body_md=body_md,
                triage_keywords=spec["triage_keywords"],
                applies_to_agent_types=spec["applies_to_agent_types"],
                priority=spec["priority"],
                is_active=True,
                description=spec["description"],
                tags=["triage", "seed"],
                created_by="system",
            )
            if rid:
                inserted += 1
        except Exception as e:
            log.debug("seed_triage_runbooks[%s] failed: %s", spec.get("name"), e)
    if inserted:
        log.info("runbooks: seeded %d triage runbook(s)", inserted)
    return inserted
