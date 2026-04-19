# CC PROMPT — v2.35.20 — `infra_lookup(not_found)` returns status=ok with found:false

## What this does

Fixes a semantic bug in `infra_lookup(query=X)` where "no match found"
returns `status="error"`. This is incorrect tool-contract semantics:
`status` should reflect tool *execution health*, not *data cardinality*.

The same tool's `list_inventory` branch (called with empty `query`)
already returns `status="ok"` when zero rows exist
(`"0 infrastructure entities known"`). The query-specific branch is
asymmetric and trains the agent to treat benign "nothing matched"
as an actionable error — wasting budget on retries and
polluting fabrication-detector's view of the tool history.

Version bump: 2.35.19 → 2.35.20.

≤15 LOC production change, single function, surgical fix.

---

## Evidence

Trace op `b196f049` (UniFi device status, commit `2620552`,
v2.35.19 era, 2026-04-19 19:41):

```
Step 4: result_query(rs-5cb3809ab778) status=ok  — 19 AP rows
Step 5: infra_lookup('e4:38:83:62:af:6b') status=error  ← FAKE ERROR
Step 6: infra_lookup('e4:38:83:78:ac:1b') status=error  ← FAKE ERROR
```

The agent, looking up AP MAC addresses returned by the UniFi tool,
got `status=error` twice and then changed strategy (retried
`unifi_network_status` on step 7 — wasted). Budget hit 8/8 on
step 8, forced-synthesis fired. Two of the eight calls were
"errors" that weren't errors.

Direct-invoke reproduces cleanly:

```
POST /api/tools/infra_lookup/invoke {"query": "aa:bb:cc:dd:ee:ff"}
→ {"status": "error", "message": "No infrastructure entity
                                   found for 'aa:bb:cc:dd:ee:ff'"}

POST /api/tools/infra_lookup/invoke {"query": "", "platform": "nonexistent"}
→ {"status": "ok", "message": "0 infrastructure entities known",
   "data": {"entities": []}}
```

Same tool, same "empty result" semantic, different status. Bug.

---

## Change 1 — `mcp_server/tools/vm.py` — fix `infra_lookup` not-found branch

Locate `infra_lookup` in `mcp_server/tools/vm.py`. Inside the
`if query:` branch, the final `return` after `resolve_host` returns
`None` currently emits `status="error"`. Replace it with:

```python
# Before (buggy):
return {"status": "error",
        "message": f"No infrastructure entity found for {query!r}",
        "data": None, "timestamp": _ts()}

# After (v2.35.20):
return {
    "status": "ok",
    "message": f"No match for {query!r}",
    "data": {
        "found": False,
        "query": query,
        "platform_filter": platform or None,
    },
    "timestamp": _ts(),
}
```

The `data.found` boolean gives the agent a discoverable signal:
`if result["data"]["found"]: use entity ...`. Agents were already
seeing empty `data` on the old error path; the new shape is
additive and operationally cleaner.

`list_inventory` branch (empty query) is already correct — do not
touch it. The happy-path `resolve_host` returning an entry is
also correct — do not touch it.

## Change 2 — callers of `infra_lookup` — audit for breakage

`git grep -n "infra_lookup"` across the codebase. Typical callers
invoke via the MCP tool registry, so they read `result["status"]`
and `result["data"]`. Any caller that specifically branches on
`status == "error"` to mean "not found" would be broken by this
change — it would now see `status == "ok"` and need to check
`data.found`.

Check these specific call sites:
- `api/agents/preflight.py` — does it call `infra_lookup`
  directly? If yes, verify the branch.
- Any `api/facts/*` files — fact extractors may cross-reference
  via infra_lookup.
- `api/routers/agent.py` — may pre-invoke infra_lookup during
  preflight.

**Most likely outcome**: no internal Python caller depends on
the error status for the not-found case, because the same
"not found" path exists in `resolve_host` directly (returns
`None`) and every internal caller reads that instead. The MCP
tool wrapper is what the LLM sees.

If CC finds an internal caller that breaks, choose the narrowest
fix (usually `result.get("data", {}).get("found", True)` as a
replacement predicate).

## Change 3 — `api/metrics.py` — optional telemetry

Add a counter to surface how often infra_lookup returns
not-found so operators can see agents churning through lookups:

```python
INFRA_LOOKUP_RESULT_COUNTER = Counter(
    "deathstar_infra_lookup_result_total",
    "infra_lookup outcomes",
    ["outcome"],  # found | not_found | list | error
)
```

Wire it into the four paths of `infra_lookup`:
- `resolve_host` returns entry → `outcome="found"`
- `resolve_host` returns None → `outcome="not_found"`
- empty query → `outcome="list"`
- exception → `outcome="error"`

Wrapped in `try: ... except: pass` per the existing counter-
usage idiom so a metrics import failure can never break the
tool itself.

## Change 4 — tests

Create `tests/test_infra_lookup_contract.py`:

```python
"""v2.35.20 — infra_lookup tool contract: not-found is status=ok,
not status=error. Semantic fix — 'no match' is not a tool failure."""
from unittest.mock import patch


def test_found_returns_ok_and_found_true():
    from mcp_server.tools.vm import infra_lookup
    fake_entry = {
        "connection_id": "abc",
        "platform": "vm_host",
        "label": "worker-01",
        "hostname": "ds-docker-worker-01",
        "ips": ["192.168.199.31"],
        "aliases": [],
        "meta": {},
    }
    with patch("api.db.infra_inventory.resolve_host", return_value=fake_entry):
        r = infra_lookup(query="worker-01")
    assert r["status"] == "ok"
    # For a found result, data is the entry itself (no 'found' key needed)
    assert r["data"]["label"] == "worker-01"


def test_not_found_returns_ok_with_found_false():
    """v2.35.20: critical regression — NOT an error."""
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host", return_value=None):
        r = infra_lookup(query="aa:bb:cc:dd:ee:ff")
    assert r["status"] == "ok", (
        f"Expected status=ok for not-found, got {r['status']}: {r['message']!r}"
    )
    assert r["data"]["found"] is False
    assert r["data"]["query"] == "aa:bb:cc:dd:ee:ff"
    assert "aa:bb:cc:dd:ee:ff" in r["message"]


def test_not_found_with_platform_filter_preserves_filter():
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host", return_value=None):
        r = infra_lookup(query="unknown-thing", platform="vm_host")
    assert r["status"] == "ok"
    assert r["data"]["found"] is False
    assert r["data"]["platform_filter"] == "vm_host"


def test_list_inventory_branch_unchanged():
    """Regression: the empty-query branch was already returning ok.
    Don't accidentally break it."""
    from mcp_server.tools.vm import infra_lookup
    fake_entries = [
        {"label": "worker-01", "hostname": "h1", "ips": ["10.0.0.1"],
         "platform": "vm_host", "meta": {}},
    ]
    with patch("api.db.infra_inventory.list_inventory", return_value=fake_entries):
        r = infra_lookup(query="", platform="vm_host")
    assert r["status"] == "ok"
    assert "entities" in r["data"]
    assert len(r["data"]["entities"]) == 1


def test_db_exception_still_returns_error():
    """Only genuine exec failures (DB error, exception) are status=error.
    'Not found' is not an exec failure."""
    from mcp_server.tools.vm import infra_lookup
    with patch("api.db.infra_inventory.resolve_host",
               side_effect=RuntimeError("DB connection lost")):
        r = infra_lookup(query="worker-01")
    assert r["status"] == "error"
    assert "DB connection lost" in r["message"] or "error" in r["message"].lower()
```

## Change 5 — `VERSION`

```
2.35.20
```

## Verify

```bash
pytest tests/test_infra_lookup_contract.py -v
pytest tests/ -v -k "infra_lookup"
```

## Commit

```bash
git add -A
git commit -m "fix(tools): v2.35.20 infra_lookup not-found returns status=ok, not error

Semantic fix: infra_lookup(query=X) where X doesn't match any
infrastructure entity was returning status='error'. Not finding a
thing is not a tool execution failure — it's a successful query
with a negative result. The same tool's list_inventory branch
already returned status='ok' when empty ('0 infrastructure
entities known'); only the query-specific branch was asymmetric.

Trace op b196f049 (UniFi device status, v2.35.19 era):
  Step 5: infra_lookup('e4:38:83:62:af:6b') status=error  ← fake
  Step 6: infra_lookup('e4:38:83:78:ac:1b') status=error  ← fake
Both MAC addresses were valid UniFi-reported APs; infra_inventory
doesn't index MACs. Agent saw two 'errors', changed strategy,
retried unifi_network_status, hit budget cap with nothing useful.

Fix: not-found now returns status='ok', data={found: False,
query, platform_filter}. Caller uses data.found as the
discoverable predicate. DB exceptions still return status='error'.
list_inventory and happy-path branches unchanged.

5 regression tests lock in all four branches (found, not_found,
list, db_error) plus platform-filter preservation."
git push origin main
```

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

1. **Direct invoke** `infra_lookup(query='aa:bb:cc:dd:ee:ff')` →
   `status=ok`, `data.found=false`.
2. **Direct invoke** `infra_lookup(query='ds-docker-worker-01')` →
   `status=ok`, `data.label='ds-docker-worker-01'` (happy path
   unchanged).
3. **Re-run UniFi device status template** — infra_lookup
   failures should be gone from the trace's error list. Budget
   may still be tight because of Qwen's SQL quoting on
   `result_query` (separate bug), but this specific failure mode
   is eliminated.
4. `/metrics` — new series
   `deathstar_infra_lookup_result_total{outcome="not_found"}`
   should appear (and likely tick up faster than
   `{outcome="found"}` in practice, since agents routinely
   lookup things the inventory doesn't contain).

## Scope guard

Do NOT touch:
- `resolve_host` / `list_inventory` in `api/db/infra_inventory.py`
  — those return `None` / `[]` respectively, which is correct Python semantics.
- Other tools' "not found" paths — they may have their own
  contracts (e.g. `elastic_search_logs` with `total=0` is already
  correct). This fix is scoped to `infra_lookup` only.
- The agent loop, synthesis, rescue machinery, classifier.

If in doubt about whether to touch another tool, stop and ask.
