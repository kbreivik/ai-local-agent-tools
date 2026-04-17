# CC PROMPT — v2.33.11 — fix(tools): elastic_search_logs level kwarg + alias safety

## What this does
Surfaced by a live trace on 2026-04-17 09:39: the investigate agent called
`elastic_search_logs(level="error", ...)` and got back
`got an unexpected keyword argument 'level'`. The tool's schema must accept
`level` (single string or list) and translate it to a real Elasticsearch
filter on the `log.level` / `level` / `severity` field.

Also: add a silent alias so `severity=` and `log_level=` map to the same filter,
because models guess these names frequently.

Version bump: 2.33.10 → 2.33.11

## Change 1 — locate the tool definition

Find the module containing `elastic_search_logs`. Likely under:

- `mcp_server/tools/elastic.py`, OR
- `mcp_server/tools/logs.py`, OR
- `api/integrations/elastic.py`

Search with:

```
grep -rn "def elastic_search_logs" api/ mcp_server/
```

## Change 2 — update signature + body

Add `level`, plus silent aliases. Pattern:

```python
from typing import Union, Sequence

_LEVEL_FIELDS = ("log.level", "level", "severity")

def _norm_levels(level: Union[str, Sequence[str], None]) -> list[str]:
    if level is None:
        return []
    if isinstance(level, str):
        vals = [level]
    else:
        vals = list(level)
    out = []
    for v in vals:
        if not v:
            continue
        s = str(v).strip().lower()
        if s in ("warn", "warning"):
            out.extend(["warn", "warning"])
        elif s in ("err", "error"):
            out.extend(["err", "error"])
        elif s in ("crit", "critical", "fatal"):
            out.extend(["crit", "critical", "fatal"])
        else:
            out.append(s)
    # dedupe preserving order
    seen = set()
    ordered = []
    for v in out:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def elastic_search_logs(
    query: str = "",
    minutes_ago: int = 60,
    size: int = 50,
    service: str | None = None,
    host: str | None = None,
    level: Union[str, Sequence[str], None] = None,
    # Silent aliases — models guess these:
    severity: Union[str, Sequence[str], None] = None,
    log_level: Union[str, Sequence[str], None] = None,
    **_ignored,
) -> dict:
    """
    Search Elasticsearch logs.

    Parameters:
      query: Optional free-text query (Lucene syntax). Empty string = match_all.
      minutes_ago: Lookback window (default 60).
      size: Max hits to return (default 50, cap 500).
      service: Optional container/service name filter.
      host: Optional host.name filter.
      level: Log level filter. Accepts "error" | "warn" | "info" | list of same.
             Aliases "warning"↔"warn", "err"↔"error", "crit"↔"critical" are normalised.
             Synonyms `severity=` and `log_level=` accepted silently.

    Returns:
      {
        "hits": [...],
        "total": <int, from ES hits.total>,
        "total_in_window": <int, unfiltered count in same window>,
        "applied_filters": {"level": [...], "service": ..., "host": ..., "query": ...},
        "index": <matched index pattern>,
      }
    """
    # Merge aliased level parameters
    merged_levels = _norm_levels(level) + _norm_levels(severity) + _norm_levels(log_level)
    # Final dedupe
    seen = set()
    merged_levels = [v for v in merged_levels if not (v in seen or seen.add(v))]

    must_clauses = []
    if query:
        must_clauses.append({"query_string": {"query": query, "default_operator": "AND"}})
    if service:
        must_clauses.append({"term": {"container.name.keyword": service}})
    if host:
        must_clauses.append({"term": {"host.name.keyword": host}})
    if merged_levels:
        # Match any of the level fields (ES will use the one that exists)
        level_should = []
        for field in _LEVEL_FIELDS:
            level_should.append({"terms": {f"{field}.keyword": merged_levels}})
            level_should.append({"terms": {field: merged_levels}})
        must_clauses.append({"bool": {"should": level_should, "minimum_should_match": 1}})

    time_filter = {
        "range": {"@timestamp": {"gte": f"now-{int(minutes_ago)}m", "lte": "now"}}
    }

    body = {
        "size": min(int(size), 500),
        "sort": [{"@timestamp": "desc"}],
        "query": {"bool": {"must": must_clauses + [time_filter]}},
    }

    # ... existing ES client call, unchanged ...
    # result = es_client.search(index=INDEX_PATTERN, body=body)
    # hits = result["hits"]["hits"]
    # total = result["hits"]["total"]["value"]

    # After the existing search, also compute total_in_window for reasoning context:
    window_body = {"size": 0, "query": {"bool": {"must": [time_filter]}}}
    # total_in_window = es_client.count(index=INDEX_PATTERN, body=window_body)["count"]
    # Fallback if count() unavailable: second search with size=0

    return {
        "hits": [...],                       # existing shape
        "total": total,
        "total_in_window": total_in_window,
        "applied_filters": {
            "level":   merged_levels,
            "service": service,
            "host":    host,
            "query":   query or None,
            "minutes_ago": int(minutes_ago),
        },
        "index": INDEX_PATTERN,
    }
```

**Integrate into the existing function body** — keep the real ES client call
and existing hit-shaping logic as-is. Only the **input parsing** and the
**response envelope** change.

## Change 3 — update the tool manifest description

Wherever this tool is registered with the MCP server / agent router,
update its docstring or schema to explicitly list `level` in the
parameters. Example, in the agent tool manifest:

```python
"elastic_search_logs": {
    "description": (
        "Search Elasticsearch logs. Filters: query, service, host, level "
        "(error|warn|info|critical, single or list), minutes_ago, size."
    ),
    "parameters": {
        "query": "str — Lucene query",
        "minutes_ago": "int — lookback window",
        "size": "int — max hits",
        "service": "str — container/service name",
        "host": "str — host.name filter",
        "level": "str|list — log level filter",
    },
},
```

## Change 4 — update investigate prompt's ELK section

In `api/agents/router.py` RESEARCH_PROMPT, find the Elasticsearch / logs
guidance section (if present) or add one. Add:

```
═══ ELASTICSEARCH QUERY GUIDANCE ═══
- elastic_search_logs accepts level="error"|"warn"|"info"|"critical", or a list.
- If a filtered call returns 0 hits while an unfiltered call in the same window
  returned >0 hits, the filter is likely too narrow — broaden or drop fields
  before concluding "no data".
- The response now includes total_in_window (unfiltered count in the same window)
  and applied_filters. Use these to reason about narrow-filter false negatives.
```

## Change 5 — tests

`tests/test_elastic_search_logs_signature.py`:

```python
def test_level_kwarg_accepted():
    """Regression: 2026-04-17 trace — agent called level='error' and got
    'unexpected keyword argument'."""
    import inspect
    from mcp_server.tools.elastic import elastic_search_logs  # adjust import
    sig = inspect.signature(elastic_search_logs)
    assert "level" in sig.parameters, "level kwarg must be accepted"

def test_aliases_accepted():
    import inspect
    from mcp_server.tools.elastic import elastic_search_logs
    sig = inspect.signature(elastic_search_logs)
    assert "severity" in sig.parameters
    assert "log_level" in sig.parameters

def test_level_normalisation():
    from mcp_server.tools.elastic import _norm_levels
    assert "error" in _norm_levels("err")
    assert "warn" in _norm_levels("warning") and "warning" in _norm_levels("warning")
    assert _norm_levels(None) == []
    assert "critical" in _norm_levels(["crit"])
```

## Version bump
Update `VERSION`: 2.33.10 → 2.33.11

## Commit
```
git add -A
git commit -m "fix(tools): v2.33.11 elastic_search_logs accepts level kwarg + aliases"
git push origin main
```

## How to test after push
1. Redeploy.
2. Investigate: "Search Elasticsearch for error-level log entries in the last hour."
3. Expect step 1 to succeed — no `unexpected keyword argument 'level'`.
4. Tool response includes `total_in_window` and `applied_filters` keys.
5. Run `severity="error"` variant — same result shape (alias works).
