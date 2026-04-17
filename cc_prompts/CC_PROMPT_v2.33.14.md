# CC PROMPT — v2.33.14 — feat(tools): elastic_search_logs rich query metadata

## What this does
Complements v2.33.11 + v2.33.12 by making the tool's response self-describing.
Every `elastic_search_logs` call returns: `total_in_window` (unfiltered count
in the same time window), `applied_filters` (what the call actually sent to
ES), `index` (which pattern matched), and `query_lucene` (exact query body
for debugging). Gives the agent and the operator enough information to
diagnose "filter too narrow" false negatives without guessing.

Also adds the same envelope to `elastic_log_pattern` for consistency.

Depends on v2.33.11 (level kwarg support).

Version bump: 2.33.13 → 2.33.14

## Change 1 — elastic_search_logs response envelope

v2.33.11 already added `total_in_window` and `applied_filters` to the return.
Extend to also include `query_lucene` (the exact Elasticsearch `query` body
serialised) and compute `total_in_window` via a single additional ES count
call sharing the same client:

```python
import json as _json

# After building `body` (the search request body) and before executing:
_query_body = body.get("query", {})

# Main search call
result = es_client.search(index=INDEX_PATTERN, body=body)
hits_raw = result["hits"]["hits"]
total_val = result["hits"]["total"]
# ES 7+ returns {"value": N, "relation": "eq|gte"}; older returns int
if isinstance(total_val, dict):
    total = total_val.get("value", 0)
    total_relation = total_val.get("relation", "eq")
else:
    total = int(total_val)
    total_relation = "eq"

# Unfiltered window count — minimal body, just the time filter
try:
    window_result = es_client.count(
        index=INDEX_PATTERN,
        body={"query": {"bool": {"must": [time_filter]}}},
    )
    total_in_window = window_result.get("count", 0)
except Exception:
    total_in_window = None

# Shape hits (existing code keeps its projection)
hits = [...]

return {
    "hits": hits,
    "total": total,
    "total_relation": total_relation,
    "total_in_window": total_in_window,
    "applied_filters": {
        "level":   merged_levels or None,
        "service": service,
        "host":    host,
        "query":   query or None,
        "minutes_ago": int(minutes_ago),
    },
    "query_lucene": _json.dumps(_query_body, separators=(",", ":")),
    "index": INDEX_PATTERN,
    "hint": _compute_hint(total, total_in_window, merged_levels, service, host),
}
```

Add a hint generator to make the narrowness-diagnosis obvious to the LLM:

```python
def _compute_hint(total: int, total_in_window: int | None, levels: list,
                  service: str | None, host: str | None) -> str | None:
    """Return a short hint for the agent when results look suspicious."""
    if total == 0 and total_in_window and total_in_window > 0:
        filters = []
        if levels:
            filters.append(f"level={levels}")
        if service:
            filters.append(f"service={service!r}")
        if host:
            filters.append(f"host={host!r}")
        if filters:
            return (
                f"Filter may be too narrow: 0 hits matched but "
                f"{total_in_window} log entries exist in the same window. "
                f"Active filters: {', '.join(filters)}. "
                "Try dropping one filter or broadening."
            )
    return None
```

## Change 2 — elastic_log_pattern consistent envelope

If `elastic_log_pattern` exists in the same module, give it the same shape
(applied_filters + total_in_window) using the same helpers. Exact tool body
depends on existing implementation — follow the v2.33.11 pattern of adding
a `_norm_levels` call and returning `applied_filters`.

## Change 3 — update RESEARCH_PROMPT elastic guidance

In `api/agents/router.py`, extend the ELK guidance added in v2.33.11:

```
═══ ELASTICSEARCH QUERY GUIDANCE ═══
- elastic_search_logs accepts level="error"|"warn"|"info"|"critical", or a list.
- Every response includes:
    total:           hits matched (after all filters)
    total_in_window: unfiltered count in same time window
    applied_filters: what was actually filtered
    hint:            harness diagnostic message if the query looks suspicious
- If hint is present, read it — it likely explains why results are 0.
- If total == 0 and total_in_window > 0, your filter is too narrow.
  Drop the most specific field first (host → service → level → query).
```

## Change 4 — tests

`tests/test_elastic_hint.py`:

```python
def test_hint_flags_narrow_filter():
    from mcp_server.tools.elastic import _compute_hint
    hint = _compute_hint(total=0, total_in_window=500, levels=["error"],
                         service=None, host=None)
    assert hint is not None
    assert "level" in hint
    assert "500" in hint

def test_hint_silent_when_empty_window():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(0, 0, ["error"], None, None) is None
    assert _compute_hint(0, None, ["error"], None, None) is None

def test_hint_silent_when_results_nonzero():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(5, 500, ["error"], None, None) is None

def test_hint_silent_when_no_filters():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(0, 100, [], None, None) is None

def test_response_shape_includes_keys():
    """Contract test — the envelope must carry these keys even on empty results."""
    # Mock or integration test against a local ES, asserting:
    # r.keys() >= {"hits","total","total_in_window","applied_filters","query_lucene","index"}
    pass
```

## Version bump
Update `VERSION`: 2.33.13 → 2.33.14

## Commit
```
git add -A
git commit -m "feat(tools): v2.33.14 elastic_search_logs rich query metadata + diagnostic hint"
git push origin main
```

## How to test after push
1. Redeploy.
2. Manual tool invocation: `elastic_search_logs(level="error", minutes_ago=60)`.
3. Expect response to include `total_in_window`, `applied_filters`, `query_lucene`, `index`, and (if 0 hits but non-zero window) a `hint` string.
4. Run the original trace prompt: "Search Elasticsearch for error-level log entries in the last 1 hour".
5. Observe in the operations log: when the agent sees a response with `hint`, it should quote / respond to it in its next reasoning step.
