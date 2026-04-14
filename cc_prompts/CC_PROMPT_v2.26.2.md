# CC PROMPT — v2.26.2 — Agent routing fixes: proxmox allowlist, node_activate, ambiguous classification

## What this does
Fixes three correctness gaps in the agent routing layer:
1. EXECUTE_PROXMOX_TOOLS was nearly empty — adds proxmox_vm_power and core diagnostic tools
2. node_activate was missing from all execute allowlists — agents could drain but not un-drain
3. Ambiguous tasks routed to Execute agent (wrong) — now routes to Observe + STATUS_PROMPT
4. propose_subtask was missing from all execute allowlists — agents couldn't offer sub-tasks
Version bump: v2.26.1 → v2.26.2

---

## Change 1 — api/agents/router.py

### 1a — Fix EXECUTE_KAFKA_TOOLS: add missing tools

FIND (exact):
```
EXECUTE_KAFKA_TOOLS = frozenset({
    "pre_kafka_check", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "kafka_rolling_restart_safe", "kafka_exec",
    "swarm_node_status", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

REPLACE WITH:
```
EXECUTE_KAFKA_TOOLS = frozenset({
    "pre_kafka_check", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "kafka_rolling_restart_safe", "kafka_exec",
    "swarm_node_status", "swarm_service_force_update",
    "vm_exec", "infra_lookup",                   # SSH diagnostics on workers
    "service_list", "service_health",             # Swarm service state
    "entity_history", "entity_events",            # change tracking
    "result_fetch", "result_query",               # large result retrieval
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",                            # offer automated fix run to user
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

### 1b — Fix EXECUTE_SWARM_TOOLS: add node_activate + propose_subtask

FIND (exact):
```
EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
    "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

REPLACE WITH:
```
EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "node_activate",   # node_activate un-drains a node
    "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
    "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

### 1c — Fix EXECUTE_PROXMOX_TOOLS: add all core tools (was nearly empty)

FIND (exact):
```
EXECUTE_PROXMOX_TOOLS = frozenset({
    # Populated at startup by _load_promoted_into_allowlists().
    # Only plan_action / escalate / audit_log in base until proxmox skills are promoted.
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

REPLACE WITH:
```
EXECUTE_PROXMOX_TOOLS = frozenset({
    # Core Proxmox operations
    "proxmox_vm_power",                # start/stop/reboot VMs via Proxmox API
    "swarm_node_status",               # check which Swarm worker nodes are Down
    "swarm_service_force_update",      # force-update a Swarm service after node recovery
    "vm_exec", "infra_lookup",         # SSH to VM hosts for diagnostics
    "service_list", "service_health",  # check Swarm services after VM recovery
    "service_placement",               # locate which node a service task is on
    "entity_history", "entity_events", # change tracking
    "result_fetch", "result_query",    # large result retrieval
    "resolve_entity",                  # cross-reference entity names
    # Allowlist management
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
    # Note: promoted skills injected here at startup via _load_promoted_into_allowlists()
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

### 1d — Fix EXECUTE_GENERAL_TOOLS: add node_activate + propose_subtask

FIND (exact):
```
EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "docker_engine_update", "vm_exec", "infra_lookup",
    "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "proxmox_vm_power", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

REPLACE WITH:
```
EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain", "node_activate",
    "docker_engine_update", "vm_exec", "infra_lookup",
    "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "proxmox_vm_power", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
}) | _EXECUTE_BASE | _DIAGNOSTICS
```

### 1e — Fix filter_tools: ambiguous → OBSERVE_AGENT_TOOLS (not all tools)

FIND (exact):
```
    allowlist_map = {
        'observe':     OBSERVE_AGENT_TOOLS,
        'status':      OBSERVE_AGENT_TOOLS,      # alias
        'investigate': INVESTIGATE_AGENT_TOOLS,
        'research':    INVESTIGATE_AGENT_TOOLS,  # alias
        'build':       BUILD_AGENT_TOOLS,
    }
    allowlist = allowlist_map.get(agent_type)
    if allowlist is None:
        return tools_spec  # unknown type — pass all through
```

REPLACE WITH:
```
    allowlist_map = {
        'observe':     OBSERVE_AGENT_TOOLS,
        'status':      OBSERVE_AGENT_TOOLS,      # alias
        'investigate': INVESTIGATE_AGENT_TOOLS,
        'research':    INVESTIGATE_AGENT_TOOLS,  # alias
        'build':       BUILD_AGENT_TOOLS,
        'ambiguous':   OBSERVE_AGENT_TOOLS,      # ambiguous: safe read-only default
    }
    allowlist = allowlist_map.get(agent_type)
    if allowlist is None:
        return tools_spec  # unknown type — pass all through
```

### 1f — Fix get_prompt: ambiguous → STATUS_PROMPT

FIND (exact):
```
def get_prompt(agent_type: str) -> str:
    """Return the system prompt for the given agent type."""
    return {
        'observe':     OBSERVE_PROMPT,
        'status':      STATUS_PROMPT,
        'investigate': INVESTIGATE_PROMPT,
        'research':    RESEARCH_PROMPT,
        'execute':     ACTION_PROMPT,
        'action':      ACTION_PROMPT,
        'build':       BUILD_PROMPT,
    }.get(agent_type, ACTION_PROMPT)
```

REPLACE WITH:
```
def get_prompt(agent_type: str) -> str:
    """Return the system prompt for the given agent type."""
    return {
        'observe':     OBSERVE_PROMPT,
        'status':      STATUS_PROMPT,
        'investigate': INVESTIGATE_PROMPT,
        'research':    RESEARCH_PROMPT,
        'execute':     ACTION_PROMPT,
        'action':      ACTION_PROMPT,
        'build':       BUILD_PROMPT,
        'ambiguous':   STATUS_PROMPT,  # ambiguous: gather info first, ask clarifying_question
    }.get(agent_type, STATUS_PROMPT)
```

---

## Change 2 — api/routers/agent.py

### 2a — Fix _AGENT_LABEL and _AGENT_BADGE_COLOR for ambiguous

FIND (exact):
```
_AGENT_LABEL = {
    'status':      'Observe',
    'observe':     'Observe',
    'action':      'Execute',
    'execute':     'Execute',
    'research':    'Investigate',
    'investigate': 'Investigate',
    'build':       'Build',
    'ambiguous':   'Execute',
}

_AGENT_BADGE_COLOR = {
    'status':      'blue',
    'observe':     'blue',
    'action':      'orange',
    'execute':     'orange',
    'research':    'purple',
    'investigate': 'purple',
    'build':       'yellow',
    'ambiguous':   'orange',
}
```

REPLACE WITH:
```
_AGENT_LABEL = {
    'status':      'Observe',
    'observe':     'Observe',
    'action':      'Execute',
    'execute':     'Execute',
    'research':    'Investigate',
    'investigate': 'Investigate',
    'build':       'Build',
    'ambiguous':   'Observe',   # gather info first, then user can re-run with intent
}

_AGENT_BADGE_COLOR = {
    'status':      'blue',
    'observe':     'blue',
    'action':      'orange',
    'execute':     'orange',
    'research':    'purple',
    'investigate': 'purple',
    'build':       'yellow',
    'ambiguous':   'blue',     # same as observe
}
```

---

## Version bump
Update VERSION: 2.26.1 → 2.26.2

## Commit
```bash
git add -A
git commit -m "fix(agents): v2.26.2 proxmox/swarm allowlist gaps, node_activate, ambiguous→observe"
git push origin main
```
