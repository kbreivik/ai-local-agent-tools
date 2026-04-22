# CC PROMPT — v2.39.3 — feat(agents): skill preflight — inject available skills before agent loop

## What this does

Agents currently discover skills by calling skill_search() or skill_list()
mid-loop, wasting 1-2 tool calls every run. The system prompt says "call
skill_search first" — but the agent has to make that call before it can do
anything useful.

Fix: at preflight time (before the agent loop starts), query the skill registry
for skills relevant to the task + agent_type, and inject a compact
"AVAILABLE SKILLS" section into the system prompt. The agent sees matching
skills in step 1 and can call skill_execute() directly without a discovery call.

Three-part change:
1. New `preflight_skills()` function in `api/agents/preflight.py`
2. Call it from `_stream_agent` in `api/routers/agent.py` and inject into system prompt
3. Update DYNAMIC SKILLS section in `api/agents/router.py` to reference
   the pre-injected list

Version bump: 2.39.2 → 2.39.3.

---

## Change 1 — `api/agents/preflight.py` — add preflight_skills() at end of file

Append after `format_preflight_facts_section`:

```python
# ── Skill preflight (v2.39.3) ─────────────────────────────────────────────────

_AGENT_TYPE_CATEGORIES: dict[str, list[str]] = {
    "observe":     ["monitoring", "compute", "networking", "storage", "general"],
    "status":      ["monitoring", "compute", "networking", "storage", "general"],
    "investigate": ["monitoring", "compute", "networking", "storage", "general"],
    "research":    ["monitoring", "compute", "networking", "storage", "general"],
    "execute":     ["compute", "networking", "storage", "general"],
    "action":      ["compute", "networking", "storage", "general"],
    "build":       ["general"],
}

_TASK_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "compute":    ["proxmox", "vm", "lxc", "container", "docker", "swarm", "node", "worker",
                   "disk", "cpu", "memory", "uptime", "journal", "log"],
    "networking": ["network", "fortigate", "unifi", "nginx", "dns", "firewall", "interface",
                   "vpn", "route", "ping", "port", "latency"],
    "storage":    ["pbs", "truenas", "backup", "disk", "volume", "pool", "snapshot"],
    "monitoring": ["elastic", "kibana", "grafana", "wazuh", "alert", "metric", "health",
                   "status", "check", "monitor"],
    "kafka":      ["kafka", "broker", "topic", "consumer", "lag", "partition", "isr"],
}


def _score_skill_for_task(skill: dict, task_lower: str, agent_categories: list[str]) -> int:
    """Score a skill 0-10 for relevance. Higher = more relevant."""
    score = 0
    cat = (skill.get("category") or "general").lower()
    if cat in agent_categories:
        score += 2
    # Name/description keyword overlap
    name = (skill.get("name") or "").lower()
    desc = (skill.get("description") or "").lower()
    combined = name + " " + desc
    task_words = set(w for w in task_lower.split() if len(w) > 3)
    matches = sum(1 for w in task_words if w in combined)
    score += min(matches * 2, 6)
    # Lifecycle bonus
    if skill.get("lifecycle_state") == "promoted":
        score += 2
    return score


def preflight_skills(task: str, agent_type: str, max_skills: int = 10) -> str:
    """Return an 'AVAILABLE SKILLS' block for injection into the system prompt.

    Queries the skill registry, scores each skill for relevance to the task
    and agent_type, returns the top max_skills as a compact formatted block.
    Returns empty string on any failure (safe fallback — never raises).

    Format:
        ═══ AVAILABLE SKILLS (pre-matched) ═══
        - skill_name: one-line description
        ...
        Call skill_execute(name=..., ...) directly. skill_search() still available
        for skills not listed here.
    """
    try:
        from mcp_server.tools.skills.registry import list_skills
        skills = list_skills(enabled_only=True)
    except Exception as _e:
        log.debug("preflight_skills: list_skills failed: %s", _e)
        return ""

    if not skills:
        return ""

    task_lower = task.lower()
    agent_categories = _AGENT_TYPE_CATEGORIES.get(agent_type, ["general"])

    # Boost categories mentioned in task
    for cat, kws in _TASK_CATEGORY_KEYWORDS.items():
        if any(kw in task_lower for kw in kws):
            if cat not in agent_categories:
                agent_categories = agent_categories + [cat]

    scored = []
    for s in skills:
        score = _score_skill_for_task(s, task_lower, agent_categories)
        if score > 0:
            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_skills]

    if not top:
        return ""

    lines = ["═══ AVAILABLE SKILLS (pre-matched) ═══"]
    for _, s in top:
        name = s.get("name", "")
        desc = (s.get("description") or "").split("\n")[0][:80]
        if name:
            lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    lines.append(
        "Call skill_execute(name=..., ...) for any of the above. "
        "skill_search() still available for skills not listed here."
    )
    return "\n".join(lines)
```

---

## Change 2 — `api/routers/agent.py` — call preflight_skills and inject into system prompt

Locate the preflight block in `_stream_agent` that ends with:

```python
        # v2.35.1 — prepend PREFLIGHT FACTS above RELEVANT PAST OUTCOMES.
        if _preflight_facts_block:
            injected_sections.insert(0, _preflight_facts_block)
```

Add skill preflight injection immediately after the preflight resolution block
but before the injected_sections assembly. Find the preflight try/except block
(starts with `from api.agents.preflight import preflight_resolve`) and add the
skill call just after `_preflight_facts_block` is built:

```python
    # v2.39.3 — skill preflight: inject relevant skills before agent loop
    _preflight_skills_block = ""
    try:
        from api.agents.preflight import preflight_skills as _pskills
        _preflight_skills_block = _pskills(task, first_intent)
    except Exception as _pse:
        log.debug("preflight_skills failed: %s", _pse)
```

Then find where `_preflight_facts_block` is inserted into `injected_sections`:

```python
        if _preflight_facts_block:
            injected_sections.insert(0, _preflight_facts_block)
```

Replace with:

```python
        if _preflight_facts_block:
            injected_sections.insert(0, _preflight_facts_block)
        if _preflight_skills_block:
            # Insert after facts (index 1) so facts stay at top
            injected_sections.insert(
                1 if _preflight_facts_block else 0,
                _preflight_skills_block
            )
```

---

## Change 3 — `api/agents/router.py` — update DYNAMIC SKILLS section in system prompts

Locate the string in the observe/status system prompt:

```
DYNAMIC SKILLS:
Skills are not listed in the tool manifest individually.
To use a skill: call skill_search(query=...) to find it, then skill_execute(name=..., params={...}).
Never guess skill names — always search first.
```

Replace with:

```
DYNAMIC SKILLS:
If an AVAILABLE SKILLS section appears above the system prompt, those skills
are pre-matched for this task — call skill_execute(name=...) directly.
For skills not listed there: call skill_search(query=...) first, then
skill_execute(name=..., params={...}). Never guess skill names.
```

Apply the same replacement in the investigate, execute, and build system prompts
wherever the same DYNAMIC SKILLS block appears.

---

## Version bump

Update `VERSION` file: `2.39.2` → `2.39.3`

---

## Commit

```
git add -A
git commit -m "feat(agents): v2.39.3 skill preflight — inject relevant skills before agent loop"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
