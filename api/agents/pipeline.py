"""Setup pipeline helpers for `_stream_agent` (api/routers/agent.py).

Extracted in v2.45.17 to keep `_stream_agent` focused on orchestration rather
than system-prompt assembly. Each function does ONE coherent setup step:

  build_system_prompt       — base prompt for intent + runbook injection
  run_preflight             — preflight resolve + skills + DB status update
  broadcast_preflight       — WS broadcast of the preflight event
  inject_tool_signatures    — MCP tool signatures section
  inject_capability_hint    — domain-specific capability hint (e.g. VM hosts)
  inject_memory_history     — recent entity activity from entity_history
  inject_prior_attempts     — cross-task learning from agent_attempts
  inject_facts_block        — past outcomes + RAG + MuninnDB + preflight facts

Rules:
- No global state, no module-level side effects.
- Exceptions are logged and swallowed — prompt assembly must never crash
  the agent loop; worst case is a less-rich prompt.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def build_system_prompt(task: str, first_intent: str) -> str:
    """Get base prompt for `first_intent` and apply runbook injection."""
    from api.agents.router import get_prompt
    system_prompt = get_prompt(first_intent)
    try:
        from api.agents.router import maybe_inject_runbook
        system_prompt = maybe_inject_runbook(system_prompt, task, first_intent)
    except Exception as e:
        log.debug("runbook injection skipped: %s", e)
    return system_prompt


async def run_preflight(task: str, first_intent: str, operation_id: str):
    """Run preflight resolution and skills matching.

    Returns (preflight_result, facts_block, skills_block). `preflight_result`
    is None if the resolver errored. Updates operations.status to
    'awaiting_clarification' when the resolver flags `clarifying_needed`.
    """
    preflight_result = None
    facts_block = ""
    skills_block = ""
    try:
        from api.agents.preflight import (
            preflight_resolve,
            format_preflight_facts_section,
        )
        preflight_result = preflight_resolve(task, first_intent)
        facts_block = format_preflight_facts_section(preflight_result)
        try:
            from api.agents.preflight import preflight_skills
            skills_block = preflight_skills(task, first_intent)
        except Exception as e:
            log.debug("preflight_skills failed: %s", e)

        if preflight_result.clarifying_needed:
            try:
                from api.db.base import get_engine
                from sqlalchemy import text
                async with get_engine().begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE operations SET status='awaiting_clarification' "
                            "WHERE id=:oid AND status='running'"
                        ),
                        {"oid": operation_id},
                    )
            except Exception as e:
                log.debug("preflight op status update failed: %s", e)
    except Exception as e:
        log.debug("preflight resolve skipped: %s", e)
    return preflight_result, facts_block, skills_block


async def broadcast_preflight(manager, session_id: str, operation_id: str,
                              preflight_result, skills_block: str) -> None:
    """Broadcast a `preflight` WS event so the Preflight Panel can render.

    `manager` is the WebSocket manager from api.websocket. Silently no-ops
    when `preflight_result` is None (resolver failed) or broadcast errors.
    """
    if preflight_result is None:
        return
    try:
        skills_matched = 0
        if skills_block:
            skills_matched = len([
                ln for ln in skills_block.splitlines()
                if ln.startswith("- ")
            ])
        await manager.broadcast({
            "type": "preflight",
            "session_id": session_id,
            "operation_id": operation_id,
            "preflight": preflight_result.as_dict(),
            "skills_matched": skills_matched,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


def inject_tool_signatures(system_prompt: str, agent_type: str,
                           domain: str) -> str:
    """Append the MCP tool signatures section for this agent/domain."""
    try:
        from api.agents.router import (
            allowlist_for,
            format_tool_signatures_section,
        )
        sig_block = format_tool_signatures_section(
            allowlist_for(agent_type, domain)
        )
        if sig_block:
            system_prompt = system_prompt + "\n\n" + sig_block + "\n"
    except Exception as e:
        log.debug("tool signatures injection skipped: %s", e)
    return system_prompt


def inject_capability_hint(system_prompt: str, task: str,
                           agent_type: str = "") -> str:
    """Prepend a domain-specific capability hint.

    Currently covers the vm_host domain: authoritative VM host list so the
    agent uses valid `host=` values for vm_exec. No-op for other domains.
    """
    try:
        from api.agents.router import detect_domain
        domain = detect_domain(task)
        if domain != "vm_host":
            return system_prompt

        from api.connections import get_all_connections_for_platform
        vms = get_all_connections_for_platform("vm_host")
        if not vms:
            return system_prompt

        inv = {}
        try:
            from api.db.infra_inventory import list_inventory
            inv = {e["connection_id"]: e for e in list_inventory("vm_host")}
        except Exception:
            pass

        lines = []
        for c in vms[:8]:
            cid = str(c.get("id", ""))
            label = c.get("label", c.get("host", "?"))
            ip = c.get("host", "")
            entry = inv.get(cid)
            hostname = entry.get("hostname", "") if entry else ""
            if hostname and hostname != label:
                display = f"{label} (hostname: {hostname})"
            else:
                display = f"{label} ({ip})"
            lines.append(f"  - {display}")

        cap_hint = (
            "AVAILABLE VM HOSTS (AUTHORITATIVE — use ONLY these names as `host=` for vm_exec):\n"
            + "\n".join(lines)
            + "\n\nThese are the only SSH-reachable host labels in this system. Do NOT "
            + "use hostnames from PREFLIGHT FACTS, tool results, memory, or runbooks as "
            + "vm_exec targets — they may refer to Proxmox VM names, Swarm service names, "
            + "UniFi MACs, or other non-SSH entities. If you need a name that isn't in "
            + "the list above, call list_connections(platform='vm_host') or "
            + "infra_lookup(query='<partial>') FIRST; do not guess.\n\n"
            + "USE THE COMPLETE LABEL STRING. Do NOT abbreviate — "
            + "'manager-01' and 'agent-01' are NOT valid; use "
            + "'ds-docker-manager-01' and 'hp1-ai-agent-lab' exactly. "
            + "vm_exec will do unique-suffix matching as a fallback but emits a "
            + "warning and will reject ambiguous abbreviations.\n\n"
            + "vm_exec commands: df -h, free -m, journalctl -n 50, "
            + "find / -size +100M -type f, docker system df, "
            + "docker volume ls | head -20, apt list --upgradable\n\n"
        )
        from api.security.prompt_sanitiser import sanitise
        cap_hint, _ = sanitise(
            cap_hint, max_chars=2000, source_hint="vm_host_capabilities"
        )
        return cap_hint + system_prompt
    except Exception:
        return system_prompt


def inject_memory_history(system_prompt: str, task: str,
                          first_intent: str = "") -> str:
    """Prepend recent entity activity (changes + warning/critical events).

    Pulls from api.db.entity_history for the first host-like token in the
    task. Uses infra_inventory.resolve_host to map token -> entity.
    """
    try:
        from api.db.entity_history import (
            get_recent_changes_summary, get_events,
        )
        from api.db.infra_inventory import resolve_host

        hints = []
        for word in task.split():
            if len(word) < 4:
                continue
            entry = resolve_host(word)
            if not entry:
                continue
            entity_id = entry.get("label", word)
            summary = get_recent_changes_summary(entity_id, hours=48)
            if summary:
                hints.append(f"  {entity_id}: {summary}")
            warning = get_events(
                entity_id, hours=48, severity="warning", limit=3
            )
            critical = get_events(
                entity_id, hours=48, severity="critical", limit=3
            )
            all_events = critical + warning
            if all_events:
                ev_str = "; ".join(
                    e["description"][:80] for e in all_events[:3]
                )
                hints.append(f"  {entity_id} events: {ev_str}")
            break  # one entity per task is enough

        if hints:
            block = (
                "RECENT ENTITY ACTIVITY (last 48h):\n"
                + "\n".join(hints) + "\n\n"
            )
            from api.security.prompt_sanitiser import sanitise
            block, _ = sanitise(
                block, max_chars=2000, source_hint="entity_history"
            )
            system_prompt = block + system_prompt
    except Exception:
        pass
    return system_prompt


def inject_prior_attempts(system_prompt: str, task: str,
                          first_intent: str) -> str:
    """Prepend prior-attempt context for investigate/execute tasks.

    Resolves the scoped entity (host label or kafka_cluster/swarm_cluster),
    fetches prior attempts, and formats them so the agent can avoid
    repeating failed tool chains. Opt-out via coordinatorPriorAttemptsEnabled
    is handled inside fetch_prior_attempts.
    """
    if first_intent not in ("investigate", "execute"):
        return system_prompt
    try:
        from api.db.infra_inventory import resolve_host
        from api.agents.router import detect_domain
        from api.agents.orchestrator import (
            fetch_prior_attempts, format_attempts_for_prompt,
        )

        entity = None
        for word in task.split():
            if len(word) < 4:
                continue
            entry = resolve_host(word)
            if entry:
                entity = entry.get("label", word)
                break
        if not entity:
            domain = detect_domain(task)
            if domain == "kafka":
                entity = "kafka_cluster"
            elif domain == "swarm":
                entity = "swarm_cluster"

        if not entity:
            return system_prompt

        attempts = fetch_prior_attempts(
            scope_entity=entity, agent_type=first_intent,
        )
        prior_section = format_attempts_for_prompt(attempts, first_intent)
        if prior_section:
            from api.security.prompt_sanitiser import sanitise
            prior_section, _ = sanitise(
                prior_section + "\n",
                max_chars=2000, source_hint="attempt_history",
            )
            system_prompt = prior_section + system_prompt
    except Exception:
        pass
    return system_prompt


# Meta-tools that don't answer a status question — never accept these as
# the canonical first tool, even if memory hints suggest them.
_META_FIRST_TOOLS = frozenset({
    "audit_log", "runbook_search", "memory_recall", "engram_activate",
    "propose_subtask", "plan_action", "checkpoint_save",
})


def _canonical_first_tool_for_status(task: str, first_intent: str) -> str:
    """Return a canonical first tool for status/observe tasks, or "".

    Matches v2.47.8's reactive hint logic (in step_guard.py) but fires
    proactively at prompt-build time. Only applies to status/observe
    intents; investigate/execute/build have richer first-tool patterns
    that are better served by memory than by hardcoded mapping.

    Returns "" when no strong keyword match exists — caller falls
    through to MuninnDB's hint.
    """
    if first_intent not in ("status", "observe"):
        return ""
    t = (task or "").lower()
    if not t:
        return ""

    # Elastic
    if "elastic" in t or "elasticsearch" in t:
        if "index" in t or "stat" in t:
            return "elastic_index_stats"
        if "log" in t or "search" in t:
            return "elastic_search_logs"
        return "elastic_cluster_health"

    # Kafka
    if "kafka" in t:
        if "broker" in t:
            return "kafka_broker_status"
        if "lag" in t or "consumer" in t:
            return "kafka_consumer_lag"
        if "topic" in t:
            return "kafka_topic_health"
        return "kafka_broker_status"

    # Swarm
    if "swarm" in t:
        if "node" in t:
            return "swarm_node_status"
        return "swarm_status"

    # Service
    if "service" in t:
        if "list" in t or "running" in t:
            return "service_list"
        if "version" in t and "history" in t:
            return "service_version_history"
        if "version" in t:
            return "service_current_version"
        return "service_health"

    return ""


async def inject_facts_block(system_prompt: str, task: str, first_intent: str,
                             preflight_facts_block: str = "",
                             preflight_skills_block: str = ""):
    """Prepend past outcomes + RAG docs + MuninnDB chunks + preflight facts.

    Returns (system_prompt, boost_tools, context_parts, first_tool_hint):
      - boost_tools:      list of tool names frequently successful on similar tasks
      - context_parts:    summary strings like "3 doc(s)", "2 outcome(s)"
      - first_tool_hint:  suggested first tool from history, or ""

    The caller is responsible for any WS logging about what was injected.
    """
    boost_tools: list[str] = []
    context_parts: list[str] = []
    first_tool_hint = ""
    try:
        from api.memory.feedback import (
            get_past_outcomes, build_outcome_prompt_section,
        )
        from api.memory.client import get_client as _get_mem_client

        injected_sections: list = []
        doc_chunks: list = []
        rag_doc_count = 0

        past_outcomes = await get_past_outcomes(task, max_results=4)
        outcome_section = build_outcome_prompt_section(past_outcomes)
        if outcome_section:
            injected_sections.append(outcome_section)

        # Extract tool boost list from successful past outcomes
        raw_boost: list[str] = []
        for o in past_outcomes:
            content = o.get("content", "")
            bt_m = re.search(r"Tools:\s*(.+)", content)
            if bt_m and "completed" in content.lower():
                names = [n.strip() for n in bt_m.group(1).split(",") if n.strip()]
                raw_boost.extend(names[:4])
        seen = set()
        for n in raw_boost:
            if n not in seen:
                seen.add(n)
                boost_tools.append(n)
            if len(boost_tools) >= 8:
                break

        # pgvector documentation (tiered by agent type)
        _RAG_BUDGETS = {
            "research":    (3000, None),
            "investigate": (3000, None),
            "execute":     (1500, ["api_reference", "cli_reference"]),
            "action":      (1500, ["api_reference", "cli_reference"]),
        }
        rag_cfg = _RAG_BUDGETS.get(first_intent)
        if rag_cfg:
            try:
                from api.rag.doc_search import search_docs, format_doc_results
                rag_budget, rag_type_filter = rag_cfg
                rag_results = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: search_docs(
                        query=task,
                        doc_type_filter=rag_type_filter,
                        token_budget=rag_budget,
                    )
                )
                rag_results = [
                    r for r in rag_results if r.get("rrf_score", 0) >= 0.02
                ]
                if rag_results:
                    rag_section = format_doc_results(rag_results)
                    if rag_section:
                        injected_sections.insert(0, rag_section)
                        rag_doc_count = len(rag_results)
            except Exception as e:
                log.debug("RAG injection skipped: %s", e)

        # MuninnDB doc chunks (research/investigate — gated by memoryEnabled)
        mem_enabled = True
        try:
            from api.settings_manager import get_setting
            v = get_setting("memoryEnabled").get("value", True)
            mem_enabled = v is not False and str(v).lower() not in (
                "false", "0", "no",
            )
        except Exception:
            pass

        if mem_enabled and first_intent in ("research", "investigate"):
            _mem = _get_mem_client()
            doc_context_terms = [
                w for w in task.lower().split() if len(w) > 3
            ][:6] + ["documentation"]
            doc_activations = await _mem.activate(
                doc_context_terms, max_results=5,
            )
            doc_chunks = [
                a for a in doc_activations
                if "documentation" in a.get("tags", [])
                or a.get("concept", "").startswith("docs:")
            ]
            if doc_chunks:
                doc_lines = ["OPERATIONAL MEMORY:"]
                for dc in doc_chunks:
                    content = dc.get("content", "")
                    body = re.sub(
                        r'^\[source:[^\]]+\]\n\n', '', content
                    ).strip()
                    src_m = re.search(r'source:\s*([^|]+)', content)
                    src = src_m.group(1).strip() if src_m else "docs"
                    doc_lines.append(f"[{src}]\n{body[:500]}")
                injected_sections.append("\n\n".join(doc_lines))

        # Prepend PREFLIGHT FACTS above RELEVANT PAST OUTCOMES
        if preflight_facts_block:
            injected_sections.insert(0, preflight_facts_block)
        if preflight_skills_block:
            injected_sections.insert(
                1 if preflight_facts_block else 0,
                preflight_skills_block,
            )

        # MuninnDB first-tool hint (step 0)
        try:
            from api.memory.feedback import get_first_tool_hint
            first_tool_hint = await get_first_tool_hint(task, first_intent) or ""
        except Exception as e:
            log.debug("first_tool_hint failed: %s", e)
            first_tool_hint = ""

        # v2.47.15 — proactive canonical first-tool override for
        # status/observe tasks. When the task has a strong domain
        # keyword match, the canonical tool wins over MuninnDB's hint
        # if MuninnDB returned nothing or a meta-tool (audit_log,
        # runbook_search). Fixes the persistent status-elastic-01
        # failure where the model picks audit_log instead of
        # elastic_cluster_health.
        canonical = _canonical_first_tool_for_status(task, first_intent)
        if canonical and (not first_tool_hint
                          or first_tool_hint in _META_FIRST_TOOLS):
            if first_tool_hint and first_tool_hint != canonical:
                log.info(
                    "first_tool_hint canonical override: muninn=%s -> canonical=%s "
                    "(task=%r intent=%s)",
                    first_tool_hint, canonical, task[:80], first_intent,
                )
            first_tool_hint = canonical

        if first_tool_hint:
            # v2.47.15 — stronger directive for canonical hints; the
            # weaker "Consider this" wording from MuninnDB hints was
            # ignored by the model on status-elastic-01.
            if canonical and first_tool_hint == canonical:
                hint_block = (
                    f"FIRST TOOL DIRECTIVE: For this task, your FIRST "
                    f"tool call MUST be {first_tool_hint}(). This is the "
                    f"canonical tool for this question type. Do NOT call "
                    f"audit_log, runbook_search, or any meta-tool first. "
                    f"Call {first_tool_hint}() now."
                )
            else:
                hint_block = (
                    f"HISTORICAL HINT: For tasks similar to this, "
                    f"successful runs typically started with: {first_tool_hint}. "
                    f"Consider this as your first tool call."
                )
            injected_sections.append(hint_block)

        if injected_sections:
            injection = "\n\n".join(injected_sections) + "\n\n"
            system_prompt = injection + system_prompt
            if rag_doc_count:
                context_parts.append(f"{rag_doc_count} doc(s)")
            if past_outcomes:
                context_parts.append(f"{len(past_outcomes)} outcome(s)")
            if doc_chunks:
                context_parts.append(f"{len(doc_chunks)} memory chunk(s)")
    except Exception:
        pass
    return system_prompt, boost_tools, context_parts, first_tool_hint
