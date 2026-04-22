# CC PROMPT — v2.40.1 — feat(agents): semantic runbook classifier using bge-small-en-v1.5

## What this does

`_semantic_select()` in `api/agents/runbook_classifier.py` has been a stub
returning `None` since v2.35.4. The runbook classifier falls back to keyword-only
matching which misses paraphrased tasks ("why is the broker not in ISR" won't
match the keyword "kafka" if the runbook only has "broker" as a keyword).

Fix: implement `_semantic_select()` using the same `embed()` function and
`_cosine()` helper already used by the semantic tool ranking in
`api/agents/router.py` (v2.34.9). Embed each runbook's title + keywords at
call time (cached per call with a 60s TTL), score against the task embedding,
return the top match above a threshold.

Also add `runbookClassifierMode` setting support — when set to `"semantic"`,
the classifier uses embeddings instead of keywords; `"keyword"` (default) keeps
existing behaviour.

Version bump: 2.40.0 → 2.40.1.

---

## Change 1 — `api/agents/runbook_classifier.py` — implement _semantic_select

Replace the current stub:

```python
def _semantic_select(task: str, agent_type: str) -> dict | None:
    # Stub for v2.35.5 — embedding-based
    return None
```

Replace with:

```python
# Module-level embedding cache for runbooks (60s TTL)
_runbook_embed_cache: dict[str, list[float]] = {}
_runbook_embed_cache_ts: float = 0.0
_RUNBOOK_EMBED_CACHE_TTL = 60.0


def _embed(text: str) -> list[float] | None:
    """Embed text using the RAG model (bge-small-en-v1.5). Returns None on failure."""
    try:
        from api.rag.doc_search import embed
        return embed(text)
    except Exception as _e:
        log.debug("runbook_classifier._embed failed: %s", _e)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _semantic_select(task: str, agent_type: str,
                     threshold: float = 0.55) -> dict | None:
    """Embedding-based runbook selection using bge-small-en-v1.5.

    Embeds each runbook as '<title>: <keywords joined>' and scores against
    the task embedding. Returns the highest-scoring runbook above threshold,
    filtered by agent_type. Falls back to None if embedding unavailable.
    """
    import time as _t
    global _runbook_embed_cache, _runbook_embed_cache_ts

    task_vec = _embed(task[:512])
    if task_vec is None:
        return None  # embedding not available — caller falls back to keyword

    try:
        from api.db.runbooks import list_active_runbooks_for_agent_type
        candidates = list_active_runbooks_for_agent_type(agent_type)
    except Exception as e:
        log.debug("runbook_classifier._semantic_select: list query failed: %s", e)
        return None

    if not candidates:
        return None

    # Rebuild cache if stale
    now = _t.monotonic()
    if now - _runbook_embed_cache_ts > _RUNBOOK_EMBED_CACHE_TTL:
        _runbook_embed_cache = {}
        _runbook_embed_cache_ts = now

    scored = []
    for rb in candidates:
        rb_id = str(rb.get("id") or rb.get("title", ""))
        if rb_id not in _runbook_embed_cache:
            title = rb.get("title") or ""
            kws = " ".join(rb.get("triage_keywords") or [])
            rb_text = f"{title}: {kws}"[:512]
            vec = _embed(rb_text)
            if vec is None:
                continue
            _runbook_embed_cache[rb_id] = vec

        rb_vec = _runbook_embed_cache.get(rb_id)
        if rb_vec is None:
            continue

        sim = _cosine(task_vec, rb_vec)
        if sim >= threshold:
            scored.append((sim, int(rb.get("priority", 100)), rb))

    if not scored:
        return None

    scored.sort(key=lambda x: (-x[0], x[1]))
    sim, _prio, rb = scored[0]
    return {
        "runbook":          rb,
        "score":            round(sim, 4),
        "matched_keywords": [],   # semantic — no discrete keyword list
    }
```

---

## Change 2 — `api/agents/runbook_classifier.py` — wire semantic mode in select_runbook

Locate `select_runbook()`:

```python
def select_runbook(task: str, agent_type: str, settings: dict | None = None) -> dict | None:
```

Find the mode dispatch block inside it. It currently reads `runbookClassifierMode`
from settings and calls either `_semantic_select` or `_keyword_select`. Since
`_semantic_select` was a stub, the semantic path was dead. Now that it is
implemented, the wiring just needs to ensure the threshold is also read from
settings.

Locate the `_semantic_select` call (if present) or add it. The dispatch should be:

```python
    if mode == "semantic":
        result = _semantic_select(
            task, agent_type,
            threshold=float(s.get("runbookSemanticThreshold", 0.55)),
        )
        # Fall back to keyword if embedding unavailable
        if result is None:
            result = _keyword_select(task, agent_type)
        return result
```

If the mode block doesn't yet read `runbookSemanticThreshold` from settings,
add it as shown above. The setting defaults to 0.55 which is a safe starting
threshold for bge-small-en-v1.5 cosine similarity.

---

## Change 3 — `api/routers/settings.py` — register runbookSemanticThreshold

Locate the `SETTINGS_KEYS` dict. Find the `runbookClassifierMode` entry
(it should be under the "Facts & Knowledge" group). Add the threshold key
immediately after it:

```python
"runbookSemanticThreshold": {
    "type": "float",
    "default": 0.55,
    "group": "Facts & Knowledge",
    "label": "Runbook semantic similarity threshold",
    "description": "Cosine similarity threshold for semantic runbook matching (0.0-1.0). Lower = more permissive.",
},
```

---

## Change 4 — `gui/src/context/OptionsContext.jsx` — add to SERVER_KEYS + DEFAULTS

Locate `SERVER_KEYS` and `DEFAULTS` in OptionsContext.jsx. Add:

```javascript
// In DEFAULTS:
runbookSemanticThreshold: 0.55,

// In SERVER_KEYS (the Set):
"runbookSemanticThreshold",
```

---

## Version bump

Update `VERSION` file: `2.40.0` → `2.40.1`

---

## Commit

```
git add -A
git commit -m "feat(agents): v2.40.1 semantic runbook classifier — bge-small-en-v1.5 with keyword fallback"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
