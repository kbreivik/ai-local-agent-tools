# CC PROMPT — v2.35.7 — Entity-identifier disambiguation between PREFLIGHT FACTS and vm_host connection labels

## What this does

When a task involves "all VM hosts" / "all registered hosts" / "every node", the agent is shown two name spaces in its system prompt:

1. **`AVAILABLE VM HOSTS` capability injection** (from `api/routers/agent.py`
   `_stream_agent`) — real vm_host connection labels the agent must use for
   `vm_exec` calls: `ds-docker-worker-01`, `ds-docker-manager-02`,
   `hp1-ai-agent-lab`, etc.

2. **`PREFLIGHT FACTS` section** (from `api/agents/preflight.py`
   `format_preflight_facts_section`, v2.35.1) — fact rows keyed on entity_ids
   that come from whichever collector produced the fact. For Proxmox VMs the
   fact key is `prod.proxmox.vm.<pve_vm_name>.<attr>` where `<pve_vm_name>` is
   the NAME PROXMOX KNOWS THE VM BY (e.g. `hp1-prod-worker-03`,
   `hp1-prod-manager-02`) — NOT the vm_host connection label.

These are the same physical boxes with different identifiers. The agent is
currently conflating them: when asked "check disk usage on all hosts", it
extracts `hp1-prod-worker-03` from PREFLIGHT FACTS and passes it as
`vm_exec(host="hp1-prod-worker-03")`, which fails because no vm_host
connection has that label. On v2.35.5 smoke (op `a7e146a1`, task "VM host
overview") the agent burned 6 consecutive `vm_exec` errors before recovering
via `infra_lookup` — status ended as `capped`, template failed.

This prompt:

1. Adds a disambiguation note inside `format_preflight_facts_section()` that
   tells the agent PREFLIGHT FACTS entity_ids are **not SSH targets**.
2. Strengthens the `AVAILABLE VM HOSTS` capability hint to explicitly claim
   authority over `vm_exec host=` targets.
3. Updates the five affected task templates to cite the authoritative name
   source.
4. Adds a regression test that fires an "all hosts" task at a mock harness
   and asserts the system prompt contains the disambiguation clause.

Version bump: 2.35.6 → 2.35.7.

---

## Evidence gathered before this prompt was written

Op `a7e146a1` (v2.35.5 VM host overview smoke test, captured 2026-04-18):

```
system_prompt (14939 chars) contained:
  - "AVAILABLE VM HOSTS (use vm_exec to query, ...)"
      ds-docker-worker-01 (192.168.199.31)
      ds-docker-worker-02 (192.168.199.32)
      ds-docker-worker-03 (192.168.199.33)
      ds-docker-manager-01 (192.168.199.21)
      ...
  - "PREFLIGHT FACTS (confidence ≥ 0.70, ...)"
      prod.proxmox.vm.hp1-prod-worker-03.memory_gb = 4.3
      prod.proxmox.vm.hp1-prod-manager-03.memory_gb = 1.6
      ...

tool_calls (first 6, all status=error):
  vm_exec(host="hp1-prod-worker-01", command="df -h /")  ← hallucinated
  vm_exec(host="hp1-prod-worker-02", command="df -h /")  ← from PREFLIGHT pattern
  vm_exec(host="hp1-prod-worker-03", command="df -h /")
  vm_exec(host="hp1-prod-manager-01", command="df -h /")
  vm_exec(host="hp1-prod-manager-02", command="df -h /")
  vm_exec(host="hp1-prod-manager-03", command="df -h /")

tool_calls 7-8 (recovery):
  infra_lookup(query="")  → ok
  result_query(ref="rs-...", where="platform = 'vm_host'", ...)  → ok

status: capped (hit 8/8 observe tool budget without completing)
final_answer: truncated XML-style "<tool_call>\n<function=vm_exec>..." drift
```

---

## Change 1 — `api/agents/preflight.py` — disambiguation header in `format_preflight_facts_section()`

Find the function that renders the PREFLIGHT FACTS block. It currently
starts with:

```python
def format_preflight_facts_section(result) -> str:
    ...
    lines = [
        "═══ PREFLIGHT FACTS (confidence ≥ 0.70, verified within refresh cadence) ═══",
    ]
    for row in ...:
        lines.append(f"{row.fact_key} = {json.dumps(row.value)}  ({row.source}, age: {row.age}, conf: {row.conf})")
    return "\n".join(lines)
```

(exact structure may vary — grep for the header string.)

Insert a disambiguation footer immediately BEFORE the closing `"═══"` line
(or append at the end of the block, before the function returns):

```python
NOTE: Fact keys here encode the entity as each collector sees it (e.g.
`prod.proxmox.vm.<pve_name>.*`, `prod.swarm.service.<service>.*`,
`prod.unifi.device.<mac>.*`). These entity identifiers are for
REASONING ONLY — they may NOT be valid as `host=` arguments to `vm_exec`
or `ssh_exec`. For SSH-addressable hosts, use the names in the
`AVAILABLE VM HOSTS` section of this prompt (or call `list_connections`
/ `infra_lookup`) — never use entity_ids from PREFLIGHT FACTS as
vm_exec targets unless they also appear in the AVAILABLE VM HOSTS list.
```

(Render this as a string append; it will appear inside the PREFLIGHT FACTS
block right above the closing `"═══"` delimiter.)

---

## Change 2 — `api/routers/agent.py` — strengthen `AVAILABLE VM HOSTS` hint

In `_stream_agent()`, inside the `if domain == "vm_host":` block (grep for
`"AVAILABLE VM HOSTS (use vm_exec"`), modify the `cap_hint` string to end
with an explicit authority claim:

```python
cap_hint = (
    "AVAILABLE VM HOSTS (AUTHORITATIVE — use ONLY these names as `host=` for vm_exec):\n"
    + "\n".join(lines)
    + "\n\nThese are the only SSH-reachable host labels in this system. Do NOT "
    + "use hostnames from PREFLIGHT FACTS, tool results, memory, or runbooks as "
    + "vm_exec targets — they may refer to Proxmox VM names, Swarm service names, "
    + "UniFi MACs, or other non-SSH entities. If you need a name that isn't in "
    + "the list above, call list_connections(platform='vm_host') or "
    + "infra_lookup(query='<partial>') FIRST; do not guess.\n\n"
    + "vm_exec commands: df -h, free -m, journalctl -n 50, "
    + "find / -size +100M -type f, docker system df, "
    + "docker volume ls | head -20, apt list --upgradable\n\n"
)
```

Keep the existing `sanitise(cap_hint, ...)` call around it.

---

## Change 3 — `gui/src/components/TaskTemplates.jsx` — hostname authority line in 5 templates

Update the `task` text for each of these templates so the agent knows where
the authoritative host list lives. Each change appends a single sentence
(preserves existing intent, adds the guardrail):

| Group | Label | Current ending | Add this sentence |
|---|---|---|---|
| INFRASTRUCTURE | Disk usage — all hosts | "...any full disks." | " Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform='vm_host') first." |
| INFRASTRUCTURE | Memory and load — all hosts | "...load above 4." | (same sentence) |
| INFRASTRUCTURE | VM host overview | "...needs attention." | (same sentence) |
| STORAGE | Storage capacity overview | "...Flag anything above 80%." | (same sentence) |
| SECURITY | SSH access audit | "...last 7 days." | " Treat the AVAILABLE VM HOSTS list in your system prompt as the source of truth for which hosts should have SSH access." |

Implement as a JSX-literal edit to the relevant `task:` values inside the
`TEMPLATES` const. Other templates unchanged.

---

## Change 4 — `tests/test_preflight_hostname_disambiguation.py` (new file)

```python
"""v2.35.7 regression — PREFLIGHT FACTS must carry a disambiguation note
preventing the agent from using fact entity_ids as vm_exec host= targets."""
from __future__ import annotations

import pytest


def test_preflight_block_contains_disambiguation_note():
    """format_preflight_facts_section() must warn the agent that entity_ids
    in the block are not guaranteed to be SSH-reachable."""
    from api.agents.preflight import format_preflight_facts_section, PreflightResult

    # Build a minimal fake result with at least one fact so the block renders
    # The exact shape depends on PreflightResult's constructor — adapt as needed.
    # If PreflightResult requires full fields, use a namedtuple or dataclass shim.
    class _FakeFact:
        fact_key = "prod.proxmox.vm.hp1-prod-worker-03.memory_gb"
        value = 4.3
        source = "proxmox_collector"
        age_s = 14
        confidence = 1.00

    class _FakeResult:
        facts = [_FakeFact()]
        clarifying_needed = False
        candidates = []
        trace = []
        def as_dict(self): return {}

    rendered = format_preflight_facts_section(_FakeResult())
    assert rendered, "non-empty facts should produce non-empty block"
    # Disambiguation note must be present
    assert "may NOT be valid as `host=`" in rendered or \
           "may not be valid as" in rendered.lower(), \
        (f"PREFLIGHT FACTS block missing disambiguation clause.\n"
         f"Got:\n{rendered[-500:]}")
    assert "vm_exec" in rendered.lower(), \
        "disambiguation clause must mention vm_exec explicitly"
    assert "AVAILABLE VM HOSTS" in rendered, \
        "disambiguation clause must point the agent to the AVAILABLE VM HOSTS section"


def test_available_vm_hosts_hint_claims_authority():
    """The vm_host capability hint in _stream_agent must claim sole authority
    over vm_exec host= parameters, so the agent doesn't pull names from
    PREFLIGHT FACTS / memory."""
    import api.routers.agent as agent_mod
    src = open(agent_mod.__file__, encoding='utf-8').read()
    # Find the AVAILABLE VM HOSTS hint literal
    assert "AVAILABLE VM HOSTS" in src
    # Must contain the authority claim
    assert ("AUTHORITATIVE" in src) or ("ONLY these names" in src), \
        ("_stream_agent vm_host capability hint does not claim sole authority. "
         "Without this the agent will pull hostnames from PREFLIGHT FACTS / "
         "memory and fail vm_exec calls — see op a7e146a1.")
    # Must explicitly warn about PREFLIGHT FACTS
    assert "PREFLIGHT FACTS" in src or "preflight" in src.lower(), \
        "vm_host capability hint does not warn about PREFLIGHT entity_ids"
```

---

## Change 5 — `VERSION`

Replace file contents with:

```
2.35.7
```

---

## Verify

```bash
pytest tests/test_preflight_hostname_disambiguation.py -v
```

Both tests must pass. Also run the existing preflight tests to confirm no
regression in fact-block rendering:

```bash
pytest tests/ -v -k "preflight"
```

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.7 disambiguate PREFLIGHT FACTS entity_ids from vm_exec host names

On v2.35.5 smoke the VM host overview template failed because the agent
pulled 'hp1-prod-worker-03' (a Proxmox VM entity_id from PREFLIGHT FACTS)
and used it as vm_exec(host=...) — but the vm_host connection for that
machine is labelled 'ds-docker-worker-03'. 6 wasted vm_exec calls, then
status=capped.

Fix has three layers:
1. format_preflight_facts_section() now appends a disambiguation note that
   names are per-collector entity_ids, not SSH targets.
2. _stream_agent()'s AVAILABLE VM HOSTS capability hint now explicitly
   claims sole authority over vm_exec host= parameters.
3. Five 'all hosts' task templates now instruct the agent to use the
   AVAILABLE VM HOSTS list.

Regression tests lock in both the disambiguation note and the authority
claim so future collector additions can't re-introduce the ambiguity."
git push origin main
```

---

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

---

## Smoke test (post-deploy, LM Studio must be loaded)

Fire "VM host overview" template. Expected:
- First vm_exec call uses `ds-docker-*` or `hp1-ai-agent-lab` — NOT `hp1-prod-*`
- No hostname errors in tool history
- Status: `completed` within 8 tool budget
- Final answer is readable prose (not XML-style drift)
