# CC PROMPT — v2.35.9 — Hostname resolution hardening + safe boolean chaining + DNS template fix

## What this does

Three tight fixes surfaced during v2.35.8 template smoke-testing. None is a
catastrophic regression — agent runs still complete with `status=capped` and
meaningful tool history — but each silently burns 1-3 tool calls from the
already-tight observe budget (8 calls) on a workflow that *should* be a
first-tool succeed.

Version bump: 2.35.8 → 2.35.9.

---

## Evidence gathered before this prompt was written

Four v2.35.8 template smoke tests (ops `7f1fb061`, `d6f52901`, `27b5be44`,
`7660a0de`, captured 2026-04-19 against commit `3cf80a2`):

1. **`_resolve_connection` returns first-match on ambiguous partial**
   (potential correctness issue, has not yet fired in prod). In
   `mcp_server/tools/vm.py` the final tier of the resolver is:
   ```python
   for c in all_conns:
       if q in c.get("label", "").lower():
           return c
   ```
   Any substring match wins the first iteration of the loop. Today this
   happens to work (only one connection contains `manager-01` as a substring)
   but as soon as two connections share any substring (e.g. a second
   `*manager-01*`) the resolver returns arbitrary ordering. Silent wrong-host
   dispatch is the worst possible failure for an ops tool.

2. **`&&` / `||` chaining is blocked by `_validate_command` even when every
   segment is an allowed read-only command.** Observed in
   - op `7f1fb061` (VM host overview): `free -m && uptime` → error, forced
     two separate calls, burned an extra tool slot of the 8-call observe
     budget
   - op `27b5be44` (Certificate expiry check): `ls -la ... || echo "not found"`
     → error

   The `_validate_command` metachar check blocks `&` wholesale. v2.34.10 added
   a PIPE_SAFELIST and REDIRECT_SAFELIST but no chain safelist. For pure-read
   workflows `cmdA && cmdB` is strictly safer than running them separately
   because it short-circuits on failure; blocking it pushes the agent to
   spend budget linearly.

3. **`gui/src/components/TaskTemplates.jsx` — DNS resolver consistency
   template literally references `agent-01` as a host name.** The agent-01
   vm_host connection is labelled `hp1-ai-agent-lab`; no connection is named
   `agent-01`. Op `7660a0de` called `vm_exec(host="agent-01",
   command="cat /etc/resolv.conf")` → status=blocked because the COMMAND was
   blocked (not in allowlist), but the host string was also wrong. Template
   text authored by me in v2.35.8 — authoring bug, not an LLM error.

4. **Capability hint wording could prevent abbreviation drift.** Current
   hint (in `_stream_agent`, vm_host domain): "These are the only
   SSH-reachable host labels in this system. Do NOT use hostnames from
   PREFLIGHT FACTS, tool results, memory, or runbooks as vm_exec targets".
   Doesn't explicitly forbid **abbreviating** a valid label. Agents on longer
   runs sometimes drop `ds-docker-` prefix from a label they saw earlier.

---

## Change 1 — `mcp_server/tools/vm.py` — require unique partial match in `_resolve_connection`

Modify the last tier of the resolver (after label-exact + IP-exact). Current:

```python
# 2. Direct connection match -- label exact -> IP exact -> label partial
for c in all_conns:
    if c.get("label", "").lower() == q:
        return c
for c in all_conns:
    if c.get("host", "") == host:
        return c
for c in all_conns:
    if q in c.get("label", "").lower():
        return c

return None
```

Replace the final loop with a **unique suffix match** — preferring
end-anchored over substring because that's what the LLM abbreviation
pattern actually looks like (drops prefixes, keeps the trailing `-01`
suffix) — and require exactly ONE match:

```python
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
```

Also update the caller in `vm_exec()` so the "No vm_host connection found"
error path can distinguish **unknown** from **ambiguous**. Grep for the
existing error-formatting block (produces the string "No vm_host connection
found for ...") and add an ambiguity branch:

```python
# Right before building the "No vm_host connection found" error, detect ambiguity:
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
```

---

## Change 2 — `mcp_server/tools/vm.py` — allow `&&` / `||` for read-only chains

Extend `_validate_command` to split the command on `&&` / `||` AFTER the
metachar check, validate each segment independently, and allow the whole
thing if every segment is allowed.

Add a helper and integrate it into `_validate_command`:

```python
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
    # Tokenise respecting quotes so && inside a string doesn't split.
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
```

Then modify `_validate_command`. **Crucially, move the chain-split BEFORE
the metachar check** because the metachar check blocks `&`. Recursively
validate each chain segment:

```python
def _validate_command(command: str, session_id: str = "") -> tuple:
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
                # Propagate the detailed error; prepend a note about which
                # chain segment failed so the model can fix surgically.
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
        # All segments pass — return the full chain to the shell.
        return True, command

    # (existing v2.34.10 pipeline logic follows unchanged from here)
    # ...
```

Add the Prometheus counter in `api/metrics.py`:

```python
VM_EXEC_CHAIN_COUNTER = Counter(
    "deathstar_vm_exec_chain_operators_total",
    "Count of vm_exec commands using && or || boolean chains.",
    ["op"],
)
```

---

## Change 3 — `api/routers/agent.py` — strengthen `AVAILABLE VM HOSTS` hint

Inside `_stream_agent`, the vm_host capability hint (added by v2.35.7 —
grep for `"AVAILABLE VM HOSTS (AUTHORITATIVE"`). Append one sentence about
abbreviation:

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
    + "USE THE COMPLETE LABEL STRING. Do NOT abbreviate — "   # NEW (v2.35.9)
    + "'manager-01' and 'agent-01' are NOT valid; use "       # NEW
    + "'ds-docker-manager-01' and 'hp1-ai-agent-lab' exactly. "  # NEW
    + "vm_exec will do unique-suffix matching as a fallback but emits a "  # NEW
    + "warning and will reject ambiguous abbreviations.\n\n"  # NEW
    + "vm_exec commands: df -h, free -m, journalctl -n 50, "
    + "find / -size +100M -type f, docker system df, "
    + "docker volume ls | head -20, apt list --upgradable\n\n"
)
```

---

## Change 4 — `gui/src/components/TaskTemplates.jsx` — DNS resolver consistency text

Find the `DNS resolver consistency` template in the NETWORK group and
replace the `agent-01` reference. Current fragment:

```javascript
...check via list_connections platform=pihole and platform=technitium; also check /etc/resolv.conf on agent-01)...
```

Replace with:

```javascript
...check via list_connections platform=pihole and platform=technitium; also check /etc/resolv.conf on the agent host — use the hp1-ai-agent-lab vm_host connection label OR call list_connections(platform='vm_host') first to confirm)...
```

And replace this later reference:

```javascript
...the agent-01 host itself, one external record (google.com)...
```

with:

```javascript
...the hp1-ai-agent-lab host itself, one external record (google.com)...
```

---

## Change 5 — `tests/test_vm_exec_hardening.py` (new file)

```python
"""v2.35.9 regression tests.

1. _resolve_connection must be unambiguous or return None.
2. _validate_command must allow && / || when every segment is allowed.
3. _validate_command must still reject single & (background) and lone $/`.
"""
from __future__ import annotations

import pytest


# ── Unique partial match ──────────────────────────────────────────────────

def test_resolve_connection_unique_suffix_match():
    from mcp_server.tools.vm import _resolve_connection
    conns = [
        {"id": 1, "label": "ds-docker-manager-01", "host": "192.168.199.21"},
        {"id": 2, "label": "ds-docker-manager-02", "host": "192.168.199.22"},
        {"id": 3, "label": "hp1-ai-agent-lab",     "host": "192.168.199.10"},
    ]
    # Exact label
    assert _resolve_connection("ds-docker-manager-01", conns)["id"] == 1
    # Unique suffix
    assert _resolve_connection("manager-01", conns)["id"] == 1
    assert _resolve_connection("agent-lab", conns)["id"] == 3


def test_resolve_connection_ambiguous_returns_none():
    from mcp_server.tools.vm import _resolve_connection
    conns = [
        {"id": 1, "label": "ds-docker-manager-01", "host": "192.168.199.21"},
        {"id": 2, "label": "hp1-prod-manager-01",  "host": "192.168.199.221"},
    ]
    # 'manager-01' ends both labels — must NOT silently pick one
    assert _resolve_connection("manager-01", conns) is None


def test_resolve_connection_ip_still_works():
    from mcp_server.tools.vm import _resolve_connection
    conns = [{"id": 1, "label": "foo", "host": "192.168.199.10"}]
    assert _resolve_connection("192.168.199.10", conns)["id"] == 1


# ── Boolean chain validation ──────────────────────────────────────────────

def test_validate_command_allows_and_chain():
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("free -m && uptime", session_id="")
    assert ok, f"expected && chain of read-only cmds allowed, got: {result!r}"


def test_validate_command_allows_or_chain():
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("df -h / || uptime", session_id="")
    assert ok, f"expected || chain of read-only cmds allowed, got: {result!r}"


def test_validate_command_rejects_chain_with_blocked_segment():
    from mcp_server.tools.vm import _validate_command
    # `rm` is not in the allowlist — chain with && must fail as a whole
    ok, result = _validate_command("df -h && rm -rf /", session_id="")
    assert not ok
    # Error should name the bad segment
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "rm" in err_text


def test_validate_command_still_rejects_single_ampersand_background():
    """Single & (background process) must stay blocked.
    This test ensures our chain-split doesn't accidentally allow it.
    """
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("sleep 100 &", session_id="")
    assert not ok
    # Error mentions metachar or disallowed character
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "&" in err_text or "metachar" in err_text.lower()


def test_validate_command_still_rejects_command_substitution():
    """$() and backticks must stay blocked regardless of chaining."""
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("df $(echo /)", session_id="")
    assert not ok
    ok, _ = _validate_command("df `echo /`", session_id="")
    assert not ok


def test_validate_command_chain_depth_cap():
    from mcp_server.tools.vm import _validate_command
    # 4+ segments not allowed
    ok, result = _validate_command(
        "df -h && uptime && free -m && uname -a", session_id=""
    )
    assert not ok
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "chain" in err_text.lower() or "boolean" in err_text.lower()


# ── Template text regression ──────────────────────────────────────────────

def test_dns_resolver_template_no_agent01_literal():
    """The DNS resolver consistency template must not reference a
    non-existent host label 'agent-01'."""
    import pathlib
    p = (pathlib.Path(__file__).parent.parent
         / "gui" / "src" / "components" / "TaskTemplates.jsx")
    src = p.read_text(encoding="utf-8")
    # Locate the DNS template block
    idx = src.find("DNS resolver consistency")
    assert idx > 0, "template not found"
    # Take a generous window after the label
    block = src[idx:idx + 2000]
    assert "agent-01" not in block, (
        "DNS resolver consistency template references non-existent host label "
        "'agent-01'. Use 'hp1-ai-agent-lab' or point the agent at "
        "list_connections(platform='vm_host')."
    )
```

---

## Change 6 — `VERSION`

Replace with:

```
2.35.9
```

---

## Verify

```bash
pytest tests/test_vm_exec_hardening.py -v
pytest tests/test_task_templates.py -v    # v2.35.8 catalogue tests still pass
```

All must pass.

---

## Commit

```bash
git add -A
git commit -m "fix(vm_exec): v2.35.9 hostname resolution hardening + safe boolean chaining + DNS template fix

Surfaced during v2.35.8 template smoke tests. Three tight fixes:

1. _resolve_connection — unique-suffix / unique-substring matching with
   ambiguity detection. Previously returned first match on a substring
   scan, which silently dispatched to arbitrary hosts once any two
   connection labels shared a substring. Now returns None on ambiguous
   partials; vm_exec formats a useful error naming all candidates.

2. _validate_command — new _split_chain() allows && / || when every
   segment independently validates. Read-only chains like 'free -m &&
   uptime' or 'ls /foo || echo missing' now execute in one tool call
   instead of two. Single & (background), \$(), backticks, and file
   redirects remain blocked. Max 3 segments.

3. AVAILABLE VM HOSTS capability hint strengthened to explicitly forbid
   abbreviation and cite concrete examples (manager-01 invalid,
   ds-docker-manager-01 correct).

4. DNS resolver consistency template — removes 'agent-01' literal which
   was never a valid vm_host connection label. Replaced with
   hp1-ai-agent-lab + list_connections hint."
git push origin main
```

---

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

---

## Smoke test (post-deploy, LM Studio loaded)

1. Fire "VM host overview" template again. Expected: agent uses
   `free -m && uptime` in ONE call (not blocked), fewer tool calls per host,
   more hosts covered within the 8-tool observe budget.

2. Fire "DNS resolver consistency" template. Expected: no `host="agent-01"`
   calls — either `hp1-ai-agent-lab` directly or via `list_connections`.

3. Check `/metrics` for `deathstar_vm_exec_chain_operators_total` — should
   increment on each `&&` / `||` use.
