# CC PROMPT — v2.33.6 — Blast radius tagging + tiered plan confirmation

## What this does
Introduces a `BLAST_RADIUS` taxonomy (`node | service | cluster | fleet`) and
tags every destructive tool. The plan modal renders a colored pill per step
and requires an extra confirmation checkbox for `cluster`+ radii. Prevents
"approve-all" blind-spots on high-impact plans.

Version bump: 2.33.5 → 2.33.6

## Change 1 — api/agents/tool_metadata.py — new registry

```python
"""
Per-tool blast radius annotations.
  node    — affects a single host
  service — affects one Swarm service (potentially multi-replica on one cluster)
  cluster — affects cluster-wide behaviour (Kafka, Swarm quorum, Proxmox HA)
  fleet   — affects every tracked asset (cred rotation, connection deletion, etc.)
"""
from typing import Literal

Radius = Literal["none", "node", "service", "cluster", "fleet"]

TOOL_RADIUS: dict[str, Radius] = {
    # observe / read-only — none
    "vm_exec_read":           "none",    # if such a read-only sibling exists
    "kafka_topic_inspect":    "none",
    "kafka_consumer_lag":     "none",
    "swarm_node_status":      "none",
    "service_placement":      "none",

    # node radius
    "vm_exec":                "node",    # default; may escalate via args
    "proxmox_vm_power":       "node",

    # service radius
    "swarm_service_force_update": "service",

    # cluster radius
    "kafka_exec":             "cluster",  # by default any write action
    "connection_delete":      "fleet",
    "credential_profile_rotate": "fleet",
}

_DESTRUCTIVE_CMD_PREFIXES = ("rm ", "dd ", "mkfs", "shutdown", "reboot", "systemctl stop")

def radius_of(tool: str, args: dict | None = None) -> Radius:
    """Static lookup with arg-based escalation for vm_exec."""
    base = TOOL_RADIUS.get(tool, "none")
    if tool == "vm_exec" and args:
        cmd = (args.get("command") or "").strip()
        if any(cmd.startswith(p) for p in _DESTRUCTIVE_CMD_PREFIXES):
            return "node"   # keep at node radius — one host
        return base
    if tool == "kafka_exec" and args:
        # list/describe/show → none; writes → cluster
        cmd = (args.get("command") or "").lower()
        if any(cmd.startswith(p) for p in ("list", "describe", "show", "get")):
            return "none"
    return base

REQUIRES_EXTRA_CONFIRM = frozenset({"cluster", "fleet"})

def needs_extra_confirm(radius: Radius) -> bool:
    return radius in REQUIRES_EXTRA_CONFIRM
```

## Change 2 — api/routers/agent.py — emit radius per plan step

In the plan-emission path (where `plan_action` is forwarded to the frontend),
enrich each step with `radius`:

```python
from api.agents.tool_metadata import radius_of, needs_extra_confirm

def build_plan_payload(steps):
    enriched = []
    for s in steps:
        r = radius_of(s["tool"], s.get("args"))
        enriched.append({
            **s,
            "radius": r,
            "extra_confirm_required": needs_extra_confirm(r),
        })
    plan_radius = _max_radius([s["radius"] for s in enriched])
    return {"steps": enriched, "plan_radius": plan_radius}

def _max_radius(rs):
    order = ["none", "node", "service", "cluster", "fleet"]
    return max(rs, key=order.index) if rs else "none"
```

Refuse any plan with more than one `fleet`-radius step:

```python
n_fleet = sum(1 for s in enriched if s["radius"] == "fleet")
if n_fleet > 1:
    raise HTTPException(400, "Plan has multiple fleet-radius steps. Split into separate tasks.")
```

## Change 3 — gui/src/components/PlanModal.jsx — radius pills + extra confirm

Render a colored pill per step:

```jsx
const RADIUS_COLOR = {
  none:    { bg: 'transparent',       fg: 'var(--text-2)' },
  node:    { bg: 'var(--green-dim)',  fg: 'var(--green)'  },
  service: { bg: 'var(--amber-dim)',  fg: 'var(--amber)'  },
  cluster: { bg: 'var(--red-dim)',    fg: 'var(--red)'    },
  fleet:   { bg: 'var(--violet-dim)', fg: 'var(--violet)' },
};

function RadiusPill({ r }) {
  const c = RADIUS_COLOR[r] || RADIUS_COLOR.none;
  return (
    <span className="mono" style={{
      fontSize: 9, letterSpacing: '0.15em', padding: '2px 6px',
      background: c.bg, color: c.fg, border: `1px solid ${c.fg}`,
      borderRadius: 2
    }}>{r.toUpperCase()}</span>
  );
}
```

For steps with `extra_confirm_required`, add a per-step checkbox:

```jsx
{step.extra_confirm_required && (
  <label className="mono" style={{ fontSize: 11, color: 'var(--red)' }}>
    <input type="checkbox" checked={extraConfirmed[i]}
           onChange={e => setExtraConfirmed({...extraConfirmed, [i]: e.target.checked})} />
    &nbsp;I acknowledge this step has <b>{step.radius}</b>-level blast radius.
  </label>
)}
```

Approve button disabled until all `extra_confirm_required` steps checked:

```jsx
const canApprove = plan.steps.every((s, i) =>
  !s.extra_confirm_required || extraConfirmed[i]
);
```

## Change 4 — tests

`tests/test_blast_radius.py`:

```python
def test_vm_exec_is_node():
    from api.agents.tool_metadata import radius_of
    assert radius_of("vm_exec", {"command": "uptime"}) == "node"

def test_kafka_exec_list_is_none():
    from api.agents.tool_metadata import radius_of
    assert radius_of("kafka_exec", {"command": "list topics"}) == "none"

def test_swarm_force_update_is_service():
    from api.agents.tool_metadata import radius_of
    assert radius_of("swarm_service_force_update") == "service"

def test_connection_delete_is_fleet():
    from api.agents.tool_metadata import radius_of
    assert radius_of("connection_delete") == "fleet"
```

## Version bump
Update `VERSION`: 2.33.5 → 2.33.6

## Commit
```
git add -A
git commit -m "feat(security): v2.33.6 blast radius tagging + tiered plan confirmation"
git push origin main
```

## How to test after push
1. Redeploy.
2. Trigger any execute task — verify plan modal shows a colored pill per step.
3. Trigger `swarm_service_force_update` — expect SERVICE pill (amber).
4. Trigger `kafka_exec` with a `delete` command — expect CLUSTER pill + extra confirm checkbox.
5. Verify Approve button stays disabled until the checkbox is ticked.
6. Attempt to craft a plan with two fleet steps — expect 400 error from backend.
