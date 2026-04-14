
| CC_PROMPT_v2.26.5.md | v2.26.5 | EntityDrawer Ask: 300→600 tokens + platform-aware suggestions | PENDING |
| CC_PROMPT_v2.26.6.md | v2.26.6 | Entity detail performance: /find/{id} endpoint + 30s cache | PENDING |
| CC_PROMPT_v2.26.7.md | v2.26.7 | VM Hosts: entity_id, to_entities(), ask/detail buttons, naming fix | PENDING |

**v2.26.6** — Entity detail performance.
Adds GET /api/entities/find/{entity_id:path} endpoint to entities.py. Loads only the
relevant collector's snapshot (1 DB query, prefix-mapped from entity_id). 30s in-memory
cache. Falls back to full _build_entities() scan for bare labels (vm_host). EntityDrawer
switches from GET /api/entities (all) + client-side find to GET /api/entities/find/{id}:
~5ms vs ~300ms. Route uses /find/ prefix to avoid conflict with /{id}/history.

**v2.26.7** — VM Hosts entity detail + naming.
vm_hosts.py: stamp entity_id=label on every VM card dict (success + error returns);
add to_entities() to VMHostsCollector returning one Entity per polled VM host, using
bare label as entity_id (consistent with existing entity_history records).
VMHostsSection.jsx: add onEntityDetail prop to VMCard; add ⌘ (ask) and › (detail)
buttons in VMCard header using existing entityId local var; thread onEntityDetail from
VMHostsSection down to each VMCard.
App.jsx: pass onEntityDetail={onEntityClick} to VMHostsSection in VM_HOSTS section.
DashboardLayout.jsx: add TILE_DISPLAY_NAMES constant; render TILE_DISPLAY_NAMES[name]
in tile header — "VM_HOSTS" → "VM Hosts", "PLATFORM" → "Platform", etc.

---

## Key file paths

```
api/routers/entities.py                   — /find/{id} fast path + cache (v2.26.6)
gui/src/components/EntityDrawer.jsx       — uses /find/{id} endpoint (v2.26.6)
api/collectors/vm_hosts.py                — entity_id + to_entities() (v2.26.7)
gui/src/components/VMHostsSection.jsx     — ask/detail buttons + onEntityDetail (v2.26.7)
gui/src/App.jsx                           — onEntityDetail passed to VMHostsSection (v2.26.7)
gui/src/components/DashboardLayout.jsx    — TILE_DISPLAY_NAMES, "VM Hosts" label (v2.26.7)
api/agents/router.py                      — allowlists, prompts, classifier (v2.26.2, v2.26.3)
api/routers/agent.py                      — loop, plan gate, ambiguous label (v2.26.2, v2.26.5)
api/db/runbooks.py                        — BASE_RUNBOOKS + seed_base_runbooks() (v2.26.4)
api/db/vm_exec_allowlist.py               — allowlist table + cache + session purge (v2.23.3)
api/routers/vm_exec_allowlist.py          — REST API for allowlist management (v2.23.3)
mcp_server/tools/vm.py                    — _validate_command DB-backed + 3 new tools (v2.23.3)
gui/src/components/OptionsModal.jsx       — Allowlist tab (v2.23.3)
api/routers/settings.py                   — agentHostIp setting key (v2.22.6)
api/collectors/docker_agent01.py          — entity_id + to_entities() per container (v2.26.0)
api/collectors/swarm.py                   — entity_id + to_entities() per service (v2.26.0)
api/collectors/external_services.py      — entity_id on all probe returns (v2.26.0)
api/collectors/unifi.py                   — entity_id per device in _build_result (v2.26.0)
api/collectors/pbs.py                     — entity_id per datastore in _poll_one_conn (v2.26.0)
api/collectors/truenas.py                 — entity_id per pool in _collect_sync (v2.26.0)
api/collectors/fortigate.py               — entity_id per interface in _collect_sync (v2.26.0)
gui/src/components/ServiceCards.jsx       — InfraCard universal entity buttons (v2.26.1)
api/routers/dashboard.py                  — _vm_ssh_exec credential fix + Proxmox action fix (v2.23.0)
api/db/infra_inventory.py                 — resolve_entity + write_cross_reference (v2.23.1)
api/collectors/proxmox_vms.py             — write VMs to infra_inventory (v2.23.1)
gui/src/context/DashboardDataContext.jsx  — shared dashboard state + version gate (v2.22.0)
api/db/metric_samples.py                  — time-series metrics (v2.21.0)
mcp_server/tools/metric_tools.py          — metric_trend + list_metrics (v2.21.0)
```
