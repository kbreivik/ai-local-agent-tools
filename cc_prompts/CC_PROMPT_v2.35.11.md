# CC PROMPT — v2.35.11 — Forced synthesis hardening + fabrication detector tightening

## What this does

v2.35.10 deploy verification fired 4 capped runs with clear 3-way pattern:
XML drift is gone from `final_answer` (primary win), but two residual bugs
show up. This prompt closes both plus one optimisation that removes a
systematic wasted LLM call per capped run.

Version bump: 2.35.10 → 2.35.11.

---

## Evidence gathered before this prompt was written

Four v2.35.10 smoke runs against commit `39372ed` on 2026-04-19
(ops `e8a625ad`, `e442810b`, `c21565be`, `234e828e`):

| test | attempt 1 | attempt 2 | final_answer outcome |
|---|---|---|---|
| VM host overview | drifted | returned placeholder echo | **bad** — persisted 47-char placeholder string |
| DNS resolver | drifted | clean synthesis | **ok** — but fabrication-DRAFT warning (false positive) |
| Certificate expiry | drifted | drifted | **good** — programmatic fallback fired |
| Docker overlay health | drifted | good synthesis | **good** — clean 732-char output |

Prometheus state on closeout:
```
deathstar_forced_synthesis_total{agent_type="status",reason="budget_cap"} = 4
deathstar_forced_synthesis_drift_total{attempt="1",reason="tool_call_prefix"} = 4
deathstar_forced_synthesis_drift_total{attempt="2",reason="tool_call_prefix"} = 1
deathstar_forced_synthesis_fallback_total{reason="budget_cap"} = 1
deathstar_forced_synthesis_fabricated_total{agent_type="status"} = 1
deathstar_vm_exec_chain_operators_total{op="&&"} = 6
deathstar_vm_exec_chain_operators_total{op="||"} = 1
```

Three actionable findings:

1. **Placeholder echo leak.** `_strip_xml_drift_from_messages()` replaces
   drifted assistant messages with the literal string
   `"[prior step: tool call attempt, see tool_calls]"`. When the cleaned
   messages list is used for the retry attempt, the model sometimes echoes
   the placeholder verbatim as its "prose" output. That string is plain
   text (doesn't match `_DRIFT_PREFIX_RE`, has 0% XML density), so
   `_is_drift()` returns `False`, programmatic fallback is NOT triggered,
   and the 47-char placeholder is persisted as `final_answer`.

2. **Fabrication detector false positive on failure reports.** The DNS
   synthesis said `list_connections(platform='pihole') ... are unavailable
   (tool not registered)` and `hp1-ai-agent-lab (agent-01, 192.168.199.10)
   confirmed reachable`. `_PROSE_CITE_RE` (`\b([a-z][a-z0-9_]{2,40})\s*\(`)
   allows whitespace between the identifier and `(`, which matches
   `unavailable (` and `lab (` as tool citations. Score 2/3 — fires,
   prepending `[HARNESS: ... DRAFT]` to a synthesis that was actually
   correct. Real tool calls are always `name(args)` with no whitespace.

3. **Attempt-1 drifts 4/4 times consistently.** With Qwen3-Coder-Next,
   the long tool-call history primes the model to continue emitting XML
   tool calls even when `tools=None`. The v2.35.10 retry path already
   applies the mitigation (cleaned messages + strong anti-XML prompt)
   on attempt 2. Promoting that same mitigation to attempt 1 saves one
   wasted LLM call per capped run (~2-3s latency + tokens) and eliminates
   the attempt-1 drift metric entirely.

---

## Change 1 — `api/agents/forced_synthesis.py` — unique placeholder marker + echo detection

### 1a. Replace the placeholder string

Find the line in `_strip_xml_drift_from_messages`:

```python
cleaned.append({
    "role": "assistant",
    "content": "[prior step: tool call attempt, see tool_calls]",
})
```

Replace with a clearly-marked sentinel and move it to a module constant so
`_is_drift` can reference the same string:

```python
# Module-level constant — used by both _strip_xml_drift_from_messages
# and _is_drift so the placeholder can never be echoed back as valid
# synthesis output.
_DRIFT_STRIPPED_PLACEHOLDER = "[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]"
```

And the replacement inside `_strip_xml_drift_from_messages`:

```python
cleaned.append({
    "role": "assistant",
    "content": _DRIFT_STRIPPED_PLACEHOLDER,
})
```

### 1b. Detect placeholder echo in `_is_drift`

Update `_is_drift` to treat the placeholder (or any output whose majority
content is the placeholder) as drift. Add two checks before the existing
regex checks:

```python
def _is_drift(text: str, *, density_threshold: float = 0.30) -> tuple[bool, str]:
    """Return (is_drift, reason) for a synthesis candidate."""
    if not text:
        return True, "empty"

    # v2.35.11: defend against the model echoing the stripped-drift
    # placeholder from cleaned retry context. If the output IS the
    # placeholder or substantially contains it (>50% of output), treat
    # as drift so the programmatic fallback fires.
    stripped = text.strip()
    if stripped == _DRIFT_STRIPPED_PLACEHOLDER:
        return True, "placeholder_echo"
    if (_DRIFT_STRIPPED_PLACEHOLDER in text
            and len(_DRIFT_STRIPPED_PLACEHOLDER) / max(len(text), 1) > 0.5):
        return True, "placeholder_echo"

    if _DRIFT_PREFIX_RE.match(text):
        return True, "tool_call_prefix"
    if _xml_density(text) > density_threshold:
        return True, f"xml_density>{density_threshold:.2f}"
    if "<parameter=" in text[:500] or "<function=" in text[:500]:
        return True, "parameter_tag_in_head"
    return False, ""
```

The new `placeholder_echo` reason will surface in
`deathstar_forced_synthesis_drift_total{reason="placeholder_echo"}` so
we can track in production how often the echo defence fires.

---

## Change 2 — `api/agents/forced_synthesis.py` — promote retry prompt to attempt 1

Metrics show attempt 1 drifts every single time with Qwen3-Coder-Next
(4/4). The retry path already knows how to avoid this. Refactor the
synthesis flow so both attempts use cleaned messages + the strong
anti-XML prompt — eliminating the systematic wasted call while keeping
a single "last-chance" retry for resilience.

Replace the `run_forced_synthesis` body's attempt section with:

```python
# v2.35.11: both attempts use cleaned history + strong anti-drift prompt.
# Historical context showed attempt 1 drifts 4/4 times on Qwen3-Coder-Next
# when left to use raw message history — the cleaned/strong path is
# strictly better, so we promote it to attempt 1 and retain attempt 2
# as one last-chance retry with even stronger prompt.
cleaned_msgs = _strip_xml_drift_from_messages(messages)

def _synthesis_messages(attempt: int) -> list:
    if attempt == 1:
        synth_harness = (
            harness_msg
            + "\n\nIMPORTANT: No tools are available in this final "
            "synthesis step. Write PLAIN PROSE only — no <tool_call>, "
            "<function=...>, <parameter=...>, or ```json``` syntax. "
            "Start with 'EVIDENCE:' and synthesise only from real tool "
            "results already in this conversation."
        )
    else:  # attempt 2 — even stronger
        synth_harness = (
            harness_msg
            + "\n\nSYSTEM: Your previous response was rejected because "
            "it contained <tool_call> / <function=...> XML syntax OR "
            "echoed a context placeholder. You CANNOT make tool calls "
            "\u2014 no tools are available. Write plain natural-language "
            "prose ONLY. Do NOT copy any prior message from this "
            "conversation \u2014 write a FRESH synthesis in your own "
            "words. Start with the literal word 'EVIDENCE:' (not '<') "
            "and do not include ANY angle-bracket tags."
        )
    return cleaned_msgs + [{"role": "system", "content": synth_harness}]

# Attempt 1 — cleaned history + strong anti-XML prompt from the start
synthesis_text, raw = _call_synthesis(
    client, model, _synthesis_messages(1), max_tokens
)

# Attempt 2 — only if attempt 1 drifted
if synthesis_text:
    drift, drift_reason = _is_drift(synthesis_text)
    if drift:
        if FORCED_SYNTHESIS_DRIFT_COUNTER is not None:
            try:
                FORCED_SYNTHESIS_DRIFT_COUNTER.labels(
                    reason=drift_reason, attempt="1"
                ).inc()
            except Exception:
                pass
        log.warning(
            "forced_synthesis: drift on attempt 1 despite cleaned history "
            "(%s), retrying with stronger prompt", drift_reason,
        )
        synthesis_text, raw = _call_synthesis(
            client, model, _synthesis_messages(2), max_tokens
        )
        if synthesis_text:
            drift2, drift_reason2 = _is_drift(synthesis_text)
            if drift2:
                if FORCED_SYNTHESIS_DRIFT_COUNTER is not None:
                    try:
                        FORCED_SYNTHESIS_DRIFT_COUNTER.labels(
                            reason=drift_reason2, attempt="2"
                        ).inc()
                    except Exception:
                        pass
                log.warning(
                    "forced_synthesis: drift persisted (%s) on attempt 2, "
                    "using programmatic fallback", drift_reason2,
                )
                synthesis_text = ""   # trigger fallback
```

The rest of `run_forced_synthesis` (programmatic fallback + fabrication
detector) is unchanged from v2.35.10.

---

## Change 3 — `api/agents/fabrication_detector.py` — tighten regex + expand denylist

### 3a. Tighten `_PROSE_CITE_RE`

Real tool calls have no whitespace between the identifier and `(`. The
current regex allows any whitespace which matches natural-language
patterns like `unavailable (tool not registered)` and
`hp1-ai-agent-lab (agent-01, 192.168.199.10)`. Replace:

```python
_PROSE_CITE_RE = re.compile(
    r"\b([a-z][a-z0-9_]{2,40})\s*\(",
)
```

with:

```python
# v2.35.11: require IMMEDIATE `(` after identifier — no whitespace.
# Tool calls are always `name(args)`. A space before `(` means
# parenthetical prose, not a citation.
_PROSE_CITE_RE = re.compile(
    r"\b([a-z][a-z0-9_]{2,40})\(",
)
```

Apply the same change to `_TOOL_CITE_RE`:

```python
_TOOL_CITE_RE = re.compile(
    r"(?:^|\n)\s*(?:[-\u2022*]|\d+\.)\s*`?([a-z][a-z0-9_]{2,40})\(",
    re.MULTILINE,
)
```

Note the trailing `\s*` before `\(` is removed in both regexes.

### 3b. Expand `_CITE_DENYLIST`

Add common English verbs/adjectives/conjunctions that show up in prose
and could theoretically be followed by `(` in some edge case. This is
belt-and-suspenders after the regex tightening.

```python
_CITE_DENYLIST = frozenset({
    "print", "log", "return", "type", "int", "str", "list", "dict",
    "any", "all", "len", "min", "max", "sum", "map", "filter",
    "open", "close", "read", "write", "run", "get", "set", "add",
    "e.g", "i.e",
    # v2.35.11: common English words observed in synthesis prose
    "see", "via", "with", "using", "for", "from", "and", "or", "but",
    "unavailable", "available", "reachable", "failed", "running",
    "blocked", "registered", "scheduled", "confirmed", "lab", "tool",
    "call", "time", "step", "note", "tip", "hint", "e.g", "i.e",
    "docker", "swarm",  # tools start with `docker_` or `swarm_` not bare
})
```

---

## Change 4 — `tests/test_forced_synthesis_drift.py` — extend with placeholder-echo test

Append to the existing v2.35.10 test file:

```python
def test_placeholder_echo_treated_as_drift():
    """The unique placeholder must be detected as drift so the fallback fires."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    drift, reason = _is_drift(_DRIFT_STRIPPED_PLACEHOLDER)
    assert drift
    assert reason == "placeholder_echo"


def test_placeholder_echo_with_small_wrapper_still_drift():
    """Model might wrap the placeholder in a few words — still drift."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    text = f"Sure: {_DRIFT_STRIPPED_PLACEHOLDER}"
    drift, reason = _is_drift(text)
    # Placeholder is majority content -> drift
    assert drift
    assert reason == "placeholder_echo"


def test_placeholder_substring_in_long_prose_not_drift():
    """A long clean synthesis that happens to mention the placeholder
    name (e.g. in a docstring quote) must NOT trigger drift — the
    majority-content check prevents this false positive."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    # 2000 chars of clean prose + one mention of the placeholder
    text = (
        "EVIDENCE:\n- Tool A returned foo\n- Tool B returned bar\n" * 50
        + f"\n\n(debug note: context included the sentinel "
        f"{_DRIFT_STRIPPED_PLACEHOLDER} from stripping)\n"
    )
    drift, reason = _is_drift(text)
    assert not drift, (
        f"placeholder appearing in long prose should not trigger drift; "
        f"reason={reason!r}, length={len(text)}"
    )


def test_run_forced_synthesis_falls_back_on_placeholder_echo(monkeypatch):
    """Integration: if attempt 1 drifts via XML and attempt 2 echoes the
    placeholder, the programmatic fallback must fire — the placeholder
    MUST NOT leak into final_answer."""
    from api.agents import forced_synthesis as fs

    class _FakeMsg:
        def __init__(self, content): self.content = content
    class _FakeChoice:
        def __init__(self, content): self.message = _FakeMsg(content)
    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]
        def model_dump(self):
            return {"choices": [{"message": {"content": self.choices[0].message.content}}]}

    class _FakeCompletions:
        def __init__(self):
            self.call_count = 0
            self.responses = [
                "<tool_call>\n<function=vm_exec>\n</tool_call>",   # attempt 1 drift
                fs._DRIFT_STRIPPED_PLACEHOLDER,                    # attempt 2 echo
            ]
        def create(self, **kw):
            i = self.call_count
            self.call_count += 1
            return _FakeResp(self.responses[min(i, len(self.responses) - 1)])

    class _FakeClient:
        def __init__(self):
            self.chat = type("X", (), {"completions": _FakeCompletions()})()

    client = _FakeClient()
    text, harness, raw = fs.run_forced_synthesis(
        client=client, model="fake",
        messages=[{"role": "user", "content": "x"}],
        agent_type="observe", reason="budget_cap",
        tool_count=8, budget=8,
        actual_tool_names=["vm_exec"],
    )
    # 2 attempts made
    assert client.chat.completions.call_count == 2
    # Neither XML drift nor placeholder must leak into output
    assert "<tool_call>" not in text
    assert fs._DRIFT_STRIPPED_PLACEHOLDER not in text
    # Must be programmatic fallback
    assert "HARNESS FALLBACK" in text
    assert "EVIDENCE" in text
```

Also REPLACE the existing `test_strip_xml_drift_from_messages_preserves_non_drift`
so it references the new constant:

```python
def test_strip_xml_drift_from_messages_preserves_non_drift():
    from api.agents.forced_synthesis import (
        _strip_xml_drift_from_messages, _DRIFT_STRIPPED_PLACEHOLDER,
    )
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "Sure, I'll check."},                       # keep
        {"role": "assistant", "content": "<tool_call>\n<function=foo>\n</tool_call>"}, # strip
        {"role": "tool", "tool_call_id": "x", "content": "{}"},                      # keep
    ]
    out = _strip_xml_drift_from_messages(msgs)
    assert len(out) == len(msgs)
    assert out[0] == msgs[0]
    assert out[1] == msgs[1]
    assert out[2] == msgs[2]
    assert out[3]["content"] == _DRIFT_STRIPPED_PLACEHOLDER
    assert out[4] == msgs[4]
```

---

## Change 5 — `tests/test_fabrication_detector_regex.py` (new file)

```python
"""v2.35.11 regression — fabrication detector must not flag prose.

Three common false-positive patterns observed on v2.35.10 synthesis
outputs (op e442810b): 'word (parenthetical)' mentions that were
extracted by _PROSE_CITE_RE because it allowed whitespace before `(`.
"""
from __future__ import annotations

import pytest


def test_parenthetical_prose_not_cited():
    from api.agents.fabrication_detector import extract_cited_tools
    text = (
        "EVIDENCE:\n"
        "- list_connections(platform='pihole') are unavailable "
        "(tool not registered)\n"
        "- hp1-ai-agent-lab (agent-01, 192.168.199.10) confirmed reachable\n"
    )
    cites = extract_cited_tools(text)
    # list_connections IS a tool call (no whitespace before `(`).
    assert "list_connections" in cites
    # These are prose words followed by space + `(` — NOT tool citations.
    assert "unavailable" not in cites
    assert "lab" not in cites
    assert "registered" not in cites


def test_real_tool_call_still_cited():
    from api.agents.fabrication_detector import extract_cited_tools
    text = "- swarm_node_status() returned 6 nodes"
    cites = extract_cited_tools(text)
    assert "swarm_node_status" in cites


def test_prose_citations_also_require_immediate_paren():
    from api.agents.fabrication_detector import extract_cited_tools
    text = (
        "The agent called vm_exec(host='worker-01') and got a result. "
        "This analysis (running now) does not cite other tools."
    )
    cites = extract_cited_tools(text)
    assert "vm_exec" in cites
    assert "analysis" not in cites
    assert "running" not in cites


def test_is_fabrication_no_longer_fires_on_dns_synthesis():
    """The exact synthesis from op e442810b should not be flagged."""
    from api.agents.fabrication_detector import is_fabrication
    text = (
        "EVIDENCE:\n"
        "- list_connections(platform='pihole') and list_connections"
        "(platform='technitium') are unavailable (tool not registered)\n"
        "- /etc/resolv.conf check blocked despite allowlist pattern '^cat\\b'\n"
        "- hp1-ai-agent-lab (agent-01, 192.168.199.10) confirmed reachable "
        "via vm_host\n"
        "\nROOT CAUSE: DNS resolver chain health cannot be assessed.\n"
        "\nNEXT STEPS:\n"
        "- Manually run `cat /etc/resolv.conf` on hp1-ai-agent-lab\n"
    )
    actual_tools = [
        "list_connections", "vm_exec", "vm_exec_allowlist_request",
        "vm_exec_allowlist_add", "infra_lookup",
    ]
    fired, detail = is_fabrication(text, actual_tool_names=actual_tools)
    assert not fired, (
        f"False positive on valid failure-report synthesis. Cited: "
        f"{detail['cited']!r}, fabricated: {detail['fabricated']!r}"
    )


def test_fabrication_detector_still_catches_real_fabrication():
    """The canonical bf3a71ea-style fabrication must still fire."""
    from api.agents.fabrication_detector import is_fabrication
    # Agent calls zero tools but cites three fake ones
    text = (
        "EVIDENCE:\n"
        "- container_inspect(id='x7k9a') returned IP 10.0.4.17\n"
        "- dns_lookup(host='elastic-ingress.internal') resolved to 10.0.4.17\n"
        "- port_scan(host='10.0.4.17', port=9092) confirmed open\n"
    )
    fired, detail = is_fabrication(text, actual_tool_names=[])
    assert fired
    assert len(detail["fabricated"]) >= 3
```

---

## Change 6 — `VERSION`

Replace with:

```
2.35.11
```

---

## Verify

```bash
pytest tests/test_forced_synthesis_drift.py -v
pytest tests/test_fabrication_detector_regex.py -v
pytest tests/ -v -k "forced_synthesis or fabrication"
```

All must pass.

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.11 forced_synthesis placeholder defence + fabrication regex tightening

Three fixes surfaced during v2.35.10 verification (4 capped runs
2026-04-19):

1. forced_synthesis placeholder echo leak (layer-2 bug):
   _strip_xml_drift_from_messages used a human-readable placeholder
   that the retry LLM could echo back verbatim as 'prose'. _is_drift
   passed it through (plain text, 0% XML density), fallback never
   fired, operator saw the 47-char placeholder as final_answer.
   Fixed with unique sentinel constant + placeholder-echo detection
   in _is_drift with majority-content guard.

2. fabrication_detector false positives on failure-report synthesis:
   _PROSE_CITE_RE allowed whitespace before '(' which matched
   parenthetical prose like 'unavailable (tool not registered)' and
   'hp1-ai-agent-lab (agent-01, 192.168.199.10)'. Tightened both
   regexes to require immediate paren. Expanded denylist as
   belt-and-suspenders. Real synthesis with legitimate failure
   reports no longer triggers DRAFT warnings.

3. Attempt 1 drifted 4/4 times with Qwen3-Coder-Next. Promoted the
   v2.35.10 retry mitigation (cleaned messages + strong anti-XML
   prompt) to attempt 1. Saves one wasted LLM call (~2-3s + tokens)
   per capped run. Attempt 2 retained as last-chance retry with
   even stronger prompt.

Three new test files: placeholder-echo detection, parenthetical-prose
non-citation, and an end-to-end integration test that proves the
programmatic fallback fires when attempt 2 echoes the placeholder."
git push origin main
```

---

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

---

## Smoke test (post-deploy)

1. Fire **VM host overview** (the failing case). Expected: `final_answer`
   begins with `EVIDENCE:` or `[HARNESS FALLBACK]`, NEVER with the
   `[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]` sentinel.

2. Fire **DNS resolver consistency** (the false-positive case).
   Expected: no `[HARNESS: ... DRAFT]` prefix on clean synthesis.

3. Check `/metrics`:
   - `deathstar_forced_synthesis_drift_total{attempt="1"}` should now
     grow MUCH slower than before (ideally 0 growth — cleaned history
     + strong prompt eliminates the pattern).
   - `deathstar_forced_synthesis_drift_total{reason="placeholder_echo"}`
     may appear if the model echoes the new sentinel — fallback will
     fire automatically.
   - `deathstar_forced_synthesis_fabricated_total{agent_type="status"}`
     should stop growing on failure-report synthesis.
