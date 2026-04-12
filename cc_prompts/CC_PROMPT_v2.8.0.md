# CC PROMPT — v2.8.0 — AI Loop Quality: Semantic Tool Routing + Thinking Memory + Feedback Pre-ranking

## What this does

Three improvements to how the agent selects tools and preserves context between steps:

1. **Semantic tool routing** — embed tool descriptions at startup, rank by cosine similarity
   to the task embedding so only the 8 most relevant tools are sent to the LLM per step.
   Uses the bge-small-en-v1.5 ONNX model already loaded for RAG — no new dependency.

2. **Thinking extraction as working memory** — after each step, parse the model's <think>
   block for key facts (numbers, hostnames, refs, statuses). Store as a compact working
   memory string prepended to the next step — preserves continuity through message trimming.

3. **Feedback-driven tool pre-ranking** — tools_for: MuninnDB engrams already store
   successful tool sequences per task type. Boost those tools to the front of the manifest
   so historically correct tools are seen first by the LLM.

Version bump: 2.6.0 → 2.8.0 (significant AI loop quality improvement)

---

## Change 1 — api/rag/doc_search.py — export embed function

The embed() function already exists. Ensure it's importable from outside the module
(it already is — just verify it handles short strings gracefully, no change needed if so).

---

## Change 2 — api/agents/router.py — semantic tool ranking

Add this function after the existing `filter_tools()` function:

```python
# ── Semantic tool ranking ─────────────────────────────────────────────────────

# Module-level cache: tool_name → embedding vector
_tool_embedding_cache: dict[str, list[float]] = {}
_tool_embedding_cache_ts: float = 0.0
_TOOL_EMBED_CACHE_TTL = 300  # 5 minutes


def _embed_text(text: str) -> list[float] | None:
    """Embed text using the RAG model. Returns None if embedding unavailable."""
    try:
        from api.rag.doc_search import embed
        return embed(text)
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _get_tool_embeddings(tools_spec: list[dict]) -> dict[str, list[float]]:
    """Return cached embeddings for all tools in the spec. Updates stale cache."""
    import time as _t
    global _tool_embedding_cache, _tool_embedding_cache_ts

    now = _t.monotonic()
    if now - _tool_embedding_cache_ts < _TOOL_EMBED_CACHE_TTL:
        return _tool_embedding_cache

    new_cache = {}
    for tool in tools_spec:
        name = tool.get("function", {}).get("name", "")
        desc = tool.get("function", {}).get("description", "")
        if not name or not desc:
            continue
        text_to_embed = f"{name}: {desc}"[:512]
        vec = _embed_text(text_to_embed)
        if vec:
            new_cache[name] = vec

    _tool_embedding_cache = new_cache
    _tool_embedding_cache_ts = now
    return new_cache


def rank_tools_for_task(
    task: str,
    tools_spec: list[dict],
    top_n: int = 8,
    boost_names: list[str] | None = None,
) -> list[dict]:
    """Rank tools by semantic similarity to task, return top_n.

    Combines two signals:
      1. Cosine similarity between task embedding and tool description embedding
      2. Boost score for tools that appeared in recent successful sequences (boost_names)

    Always includes plan_action, escalate, audit_log if in the spec.
    Falls back to returning all tools if embedding unavailable.

    Args:
        task:        User task string
        tools_spec:  Already-filtered tools list from filter_tools()
        top_n:       Max tools to return (default 8)
        boost_names: Tool names to boost (from MuninnDB successful sequences)
    """
    # Always include these structural tools regardless of ranking
    _ALWAYS_INCLUDE = {"plan_action", "escalate", "audit_log", "clarifying_question",
                       "result_fetch", "result_query"}

    if len(tools_spec) <= top_n:
        return tools_spec   # small enough — no filtering needed

    task_vec = _embed_text(task[:512])
    if task_vec is None:
        return tools_spec   # embedding unavailable — pass all through

    tool_embeddings = _get_tool_embeddings(tools_spec)
    boost_set = set(boost_names or [])

    scored = []
    always = []
    for tool in tools_spec:
        name = tool.get("function", {}).get("name", "")
        if name in _ALWAYS_INCLUDE:
            always.append(tool)
            continue
        vec = tool_embeddings.get(name)
        if vec is None:
            scored.append((0.0, tool))
            continue
        sim = _cosine(task_vec, vec)
        # Boost: +0.2 for historically successful tools, capped at 1.0
        if name in boost_set:
            sim = min(1.0, sim + 0.2)
        scored.append((sim, tool))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [t for _, t in scored[:max(0, top_n - len(always))]]

    return always + top
```

---

## Change 3 — api/routers/agent.py — integrate semantic ranking + working memory

### 3a — Add working memory extractor

Add this function near `_summarize_tool_result`:

```python
def _extract_working_memory(think_text: str, step: int) -> str:
    """Extract key facts from a model <think> block for inter-step continuity.

    Parses numbers, hostnames, ref tokens, status words, and tool plans
    from the model's reasoning. Returns a compact string (≤120 chars)
    suitable for prepending to the next step's user message.

    Returns empty string if nothing useful found.
    """
    if not think_text or len(think_text) < 20:
        return ""

    import re
    facts = []

    # Result store refs
    refs = re.findall(r'rs-[a-f0-9]{8,}', think_text)
    if refs:
        facts.append(f"ref={refs[0]}")

    # Numbers with units (disk, memory, counts)
    nums = re.findall(
        r'(\d+(?:\.\d+)?)\s*(GB|MB|TB|%|clients?|devices?|images?|containers?)',
        think_text, re.IGNORECASE
    )
    for val, unit in nums[:3]:
        facts.append(f"{val}{unit.lower()}")

    # Hostnames / labels in quotes or after "on "
    hosts = re.findall(r'(?:on|host|label)\s+["\']?([\w-]{3,30})["\']?', think_text, re.IGNORECASE)
    if hosts:
        facts.append(f"host={hosts[0]}")

    # Status findings
    statuses = re.findall(
        r'\b(healthy|degraded|critical|error|ok|success|failed|stopped|running)\b',
        think_text, re.IGNORECASE
    )
    if statuses:
        facts.append(f"status={statuses[0].lower()}")

    if not facts:
        return ""

    return f"[Step {step} found: {', '.join(facts[:5])}]"
```

### 3b — Load boost list from MuninnDB before building tools spec

In `_stream_agent()`, after loading `past_outcomes`, extract boost tool names:

```python
    # Extract tool boost list from successful past outcomes
    _boost_tools: list[str] = []
    for o in past_outcomes:
        content = o.get("content", "")
        import re as _re
        m = _re.search(r"Tools:\s*(.+)", content)
        if m and "completed" in content.lower():
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            _boost_tools.extend(names[:4])
    # Deduplicate preserving order, cap at 8
    seen = set()
    boost_tools: list[str] = []
    for n in _boost_tools:
        if n not in seen:
            seen.add(n); boost_tools.append(n)
        if len(boost_tools) >= 8:
            break
```

Store `boost_tools` in a local variable accessible to the step loop.

### 3c — Apply ranking in the step loop

In the `for step_info in steps:` loop, replace:

```python
        step_tools = filter_tools(all_tools, step_agent_type, domain=step_domain or "general")
```

With:

```python
        from api.agents.router import rank_tools_for_task
        step_tools_filtered = filter_tools(all_tools, step_agent_type, domain=step_domain or "general")
        step_tools = rank_tools_for_task(
            step_task,
            step_tools_filtered,
            top_n=10,           # leave room for always-include tools
            boost_names=boost_tools,
        )
        log.info(
            "Agent=%s ranked tools (%d→%d): %s",
            step_agent_type, len(step_tools_filtered), len(step_tools),
            [t["function"]["name"] for t in step_tools],
        )
```

### 3d — Extract working memory after each LLM response and pass forward

In `_run_single_agent_step`, after `if msg.content:` sets `last_reasoning`:

```python
            if msg.content:
                last_reasoning = msg.content
                await manager.send_line("reasoning", msg.content, session_id=session_id)
                # Extract working memory from <think> content (separate from visible reasoning)
                # The raw msg.content may include the think block before model strips it
                _wm = _extract_working_memory(msg.content, step)
```

Add `_working_memory: str = ""` to the per-run accumulators at the top of the function.

Update `_wm` into `_working_memory` when non-empty:
```python
                if _wm:
                    _working_memory = _wm
```

Before each LLM call (at the top of the while loop, after the step counter increment),
prepend working memory to the last user message if we have it and step > 1:

```python
            # Inject working memory into context for step > 1
            if step > 1 and _working_memory and len(messages) >= 2:
                # Find the last user message and prefix it
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "user" and isinstance(messages[i]["content"], str):
                        if not messages[i]["content"].startswith("[Step"):
                            messages[i] = {
                                **messages[i],
                                "content": f"{_working_memory}\n{messages[i]['content']}",
                            }
                        break
```

---

## Version bump

Update VERSION file: `2.6.0` → `2.8.0`

Update version string in `api/main.py` or wherever `version` is returned in `/api/health`.

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.8.0 semantic tool routing + thinking memory + feedback pre-ranking

- rank_tools_for_task(): cosine similarity via bge-small-en-v1.5, top-10 per step
- Tool embedding cache: 5min TTL, warm on first request
- Boost tools from MuninnDB successful sequences (+0.2 similarity bonus)
- _extract_working_memory(): parse <think> blocks for facts between steps
- Working memory injected as compact [Step N found: ...] prefix
- Always-include set: plan_action, escalate, audit_log, clarifying_question, result_*"
git push origin main
```
