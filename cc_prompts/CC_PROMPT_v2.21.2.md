# CC PROMPT — v2.21.2 — Data pipeline health tab

## What this does

The Platform Core card shows collector health dots but nothing about whether data is
actually flowing. There's no way to see: "is postgres receiving snapshots?", "when did
kafka_cluster last write?", "are ES documents arriving?", "is any collector stale?".

This adds a "Data Health" section to the Logs tab (new sub-tab) that shows the full
data pipeline status: per-collector freshness, PostgreSQL snapshot staleness, and
Elasticsearch ingest health with document counts.

Version bump: 2.21.1 → 2.21.2

---

## Change 1 — api/routers/status.py

Add a new endpoint that returns a single consolidated data pipeline health response.
Add at the end of the file:

```python
@router.get("/pipeline")
async def get_pipeline_health(_: str = Depends(get_current_user)):
    """Consolidated data pipeline health — collector freshness, PG snapshot age, ES ingest."""
    from api.collectors import manager as coll_mgr
    import os
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    # ── Collector freshness from in-memory status ─────────────────────────────
    collectors_raw = coll_mgr.status()
    collector_rows = []
    for name, c in sorted(collectors_raw.items()):
        last_poll_str = c.get("last_poll")
        age_s = None
        stale = False
        if last_poll_str:
            try:
                lp = datetime.fromisoformat(last_poll_str.replace("Z", "+00:00"))
                age_s = int((now - lp).total_seconds())
                interval = c.get("interval_s", 60)
                stale = age_s > interval * 3  # stale if >3x interval since last poll
            except Exception:
                pass
        collector_rows.append({
            "name": name,
            "running": c.get("running", False),
            "health": c.get("last_health", "unknown"),
            "interval_s": c.get("interval_s", 0),
            "last_poll": last_poll_str,
            "age_s": age_s,
            "stale": stale,
            "error": c.get("last_error"),
        })

    # ── PostgreSQL snapshot freshness per collector ───────────────────────────
    pg_rows = []
    try:
        async with get_engine().connect() as conn:
            # Get latest snapshot timestamp per component
            result = await conn.execute(
                text("""
                    SELECT component, MAX(timestamp) as latest, COUNT(*) as total_24h
                    FROM status_snapshots
                    WHERE timestamp >= NOW() - INTERVAL '24 hours'
                    GROUP BY component
                    ORDER BY component
                """)
            )
            for row in result.mappings():
                ts = row["latest"]
                age_s = int((now - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else now - ts).total_seconds()) if ts else None
                pg_rows.append({
                    "component": row["component"],
                    "latest_snapshot": ts.isoformat() if ts else None,
                    "age_s": age_s,
                    "snapshots_24h": row["total_24h"],
                    "stale": age_s is not None and age_s > 300,  # >5 min = stale
                })
    except Exception as e:
        pg_rows = [{"error": str(e)}]

    # ── Elasticsearch ingest health ───────────────────────────────────────────
    es_health = {}
    try:
        import httpx
        elastic_url = os.environ.get("ELASTIC_URL", "").rstrip("/")
        if elastic_url:
            # Document count + last document timestamp in hp1-logs-*
            r = httpx.post(
                f"{elastic_url}/hp1-logs-*/_search",
                json={
                    "size": 1,
                    "sort": [{"@timestamp": "desc"}],
                    "_source": ["@timestamp"],
                    "query": {"match_all": {}},
                    "aggs": {
                        "total_1h": {
                            "filter": {"range": {"@timestamp": {"gte": "now-1h"}}}
                        },
                        "total_5m": {
                            "filter": {"range": {"@timestamp": {"gte": "now-5m"}}}
                        }
                    }
                },
                timeout=8.0,
            )
            if r.is_success:
                data = r.json()
                hits = data.get("hits", {})
                aggs = data.get("aggregations", {})
                last_doc_ts = None
                if hits.get("hits"):
                    last_doc_ts = hits["hits"][0].get("_source", {}).get("@timestamp")
                last_doc_age_s = None
                if last_doc_ts:
                    try:
                        ld = datetime.fromisoformat(last_doc_ts.replace("Z", "+00:00"))
                        last_doc_age_s = int((now - ld).total_seconds())
                    except Exception:
                        pass
                es_health = {
                    "configured": True,
                    "total_docs": hits.get("total", {}).get("value", 0),
                    "docs_last_1h": aggs.get("total_1h", {}).get("doc_count", 0),
                    "docs_last_5m": aggs.get("total_5m", {}).get("doc_count", 0),
                    "last_document": last_doc_ts,
                    "last_document_age_s": last_doc_age_s,
                    "stale": last_doc_age_s is not None and last_doc_age_s > 600,  # >10min
                    "ingest_rate_per_min": round(aggs.get("total_5m", {}).get("doc_count", 0) / 5, 1),
                }
            else:
                es_health = {"configured": True, "error": f"HTTP {r.status_code}"}
        else:
            es_health = {"configured": False}
    except Exception as e:
        es_health = {"configured": True, "error": str(e)}

    # ── PostgreSQL connectivity + table sizes ─────────────────────────────────
    pg_meta = {}
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT
                      (SELECT COUNT(*) FROM status_snapshots) as snapshots_total,
                      (SELECT COUNT(*) FROM operations) as operations_total,
                      (SELECT COUNT(*) FROM tool_calls) as tool_calls_total,
                      (SELECT COUNT(*) FROM entity_changes) as entity_changes_total,
                      (SELECT COUNT(*) FROM entity_events) as entity_events_total
                """)
            )
            row = result.mappings().fetchone()
            if row:
                pg_meta = dict(row)
                pg_meta["connected"] = True
    except Exception as e:
        pg_meta = {"connected": False, "error": str(e)}

    # Overall pipeline health
    stale_collectors = [c["name"] for c in collector_rows if c.get("stale")]
    stale_pg = [r["component"] for r in pg_rows if r.get("stale")]
    es_stale = es_health.get("stale", False)

    if stale_collectors or stale_pg or es_stale:
        pipeline_health = "degraded"
    elif not pg_meta.get("connected"):
        pipeline_health = "error"
    else:
        pipeline_health = "healthy"

    return {
        "health": pipeline_health,
        "timestamp": now.isoformat(),
        "collectors": collector_rows,
        "postgres": {
            "connected": pg_meta.get("connected", False),
            "error": pg_meta.get("error"),
            "table_counts": {k: v for k, v in pg_meta.items() if k not in ("connected", "error")},
            "snapshots_by_component": pg_rows,
            "stale_components": stale_pg,
        },
        "elasticsearch": es_health,
        "alerts": {
            "stale_collectors": stale_collectors,
            "stale_pg_components": stale_pg,
            "es_stale": es_stale,
        },
    }
```

Also add the `text` import at the top of the file if not already present:

Find the existing imports and ensure this is present:
```python
from sqlalchemy import text
```

---

## Change 2 — gui/src/api.js

Add the pipeline health fetch function after the existing `fetchResultRef` function:

```js
export async function fetchPipelineHealth() {
  const r = await fetch(`${BASE}/api/status/pipeline`, { headers: { ...authHeaders() } })
  if (!r.ok) return null
  return r.json()
}
```

---

## Change 3 — gui/src/components/LogsPanel.jsx

### 3a — Add import

Add `fetchPipelineHealth` to the existing api import:

```js
import { createUnifiedLogStream, authHeaders, fetchResultRefs, fetchResultRef, fetchPipelineHealth } from '../api'
```

### 3b — Add DataHealthView component

Before the `// ── Root ──` comment, add this component:

```jsx
function DataHealthView() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    fetchPipelineHealth()
      .then(d => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const ageStr = (s) => {
    if (s === null || s === undefined) return '—'
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.round(s / 60)}m ago`
    return `${Math.round(s / 3600)}h ago`
  }

  const dot = (ok, stale) => {
    if (stale) return { color: 'var(--red)', label: 'STALE' }
    if (!ok) return { color: 'var(--amber)', label: 'WARN' }
    return { color: 'var(--green)', label: 'OK' }
  }

  const healthColor = (h) =>
    h === 'healthy' ? 'var(--green)' : h === 'degraded' ? 'var(--amber)' : 'var(--red)'

  if (loading) return (
    <div className="p-4 text-xs font-mono" style={{ color: 'var(--text-3)' }}>Loading pipeline health…</div>
  )

  if (!data) return (
    <div className="p-4 text-xs font-mono" style={{ color: 'var(--text-3)' }}>Pipeline health unavailable</div>
  )

  const { collectors, postgres, elasticsearch, alerts } = data

  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 12, gap: 12, background: 'var(--bg-0)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: healthColor(data.health) }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-1)', letterSpacing: '0.06em' }}>
            DATA PIPELINE — {data.health?.toUpperCase()}
          </span>
        </div>
        <button onClick={load} style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', background: 'none', border: 'none', cursor: 'pointer' }}>↻ refresh</button>
      </div>

      {/* Alert strip */}
      {(alerts?.stale_collectors?.length > 0 || alerts?.stale_pg_components?.length > 0 || alerts?.es_stale) && (
        <div style={{ padding: '6px 10px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 2, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--red)' }}>
          ⚠ STALE DATA:
          {alerts.stale_collectors?.length > 0 && ` collectors: ${alerts.stale_collectors.join(', ')}`}
          {alerts.stale_pg_components?.length > 0 && ` pg: ${alerts.stale_pg_components.join(', ')}`}
          {alerts.es_stale && ' elasticsearch ingest stale'}
        </div>
      )}

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>

        {/* Collectors */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em', marginBottom: 8 }}>COLLECTORS ({collectors?.length})</div>
          {(collectors || []).map(c => {
            const d = dot(c.health === 'healthy' || c.health === 'unconfigured', c.stale)
            const dimmed = c.health === 'unconfigured'
            return (
              <div key={c.name} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '3px 0', borderBottom: '1px solid var(--bg-3)',
                opacity: dimmed ? 0.45 : 1,
              }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: c.stale ? 'var(--red)' : c.health === 'healthy' ? 'var(--green)' : c.health === 'unconfigured' ? 'var(--text-3)' : c.health === 'degraded' ? 'var(--amber)' : 'var(--red)', flexShrink: 0 }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)', flex: 1 }}>{c.name}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{c.interval_s}s</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: c.stale ? 'var(--red)' : 'var(--text-3)' }}>
                  {c.age_s !== null ? ageStr(c.age_s) : '—'}
                </span>
                {c.stale && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>STALE</span>}
                {c.error && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)', maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.error}>ERR</span>}
              </div>
            )
          })}
        </div>

        {/* PostgreSQL */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: postgres?.connected ? 'var(--green)' : 'var(--red)', flexShrink: 0 }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em' }}>POSTGRESQL</span>
          </div>
          {/* Table counts */}
          <div style={{ marginBottom: 8 }}>
            {Object.entries(postgres?.table_counts || {}).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: '2px 0' }}>
                <span>{k.replace(/_/g, '_')}</span>
                <span style={{ color: 'var(--text-2)' }}>{Number(v).toLocaleString()}</span>
              </div>
            ))}
          </div>
          {/* Snapshot freshness */}
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.06em', marginBottom: 4 }}>SNAPSHOT FRESHNESS (24h)</div>
          {(postgres?.snapshots_by_component || []).map(s => (
            <div key={s.component} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 0', borderTop: '1px solid var(--bg-3)' }}>
              <div style={{ width: 5, height: 5, borderRadius: '50%', background: s.stale ? 'var(--red)' : 'var(--green)', flexShrink: 0 }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-2)', flex: 1 }}>{s.component}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: s.stale ? 'var(--red)' : 'var(--text-3)' }}>
                {s.age_s !== null ? ageStr(s.age_s) : '—'}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 7, color: 'var(--text-3)' }}>{s.snapshots_24h} snaps</span>
            </div>
          ))}
        </div>
      </div>

      {/* Elasticsearch */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%',
            background: !elasticsearch?.configured ? 'var(--text-3)' : elasticsearch?.stale ? 'var(--red)' : elasticsearch?.error ? 'var(--amber)' : 'var(--green)',
            flexShrink: 0 }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em' }}>ELASTICSEARCH — hp1-logs-*</span>
          {elasticsearch?.stale && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>INGEST STALE</span>}
        </div>
        {!elasticsearch?.configured ? (
          <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>ELASTIC_URL not configured</span>
        ) : elasticsearch?.error ? (
          <span style={{ fontSize: 9, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>Error: {elasticsearch.error}</span>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {[
              { label: 'TOTAL DOCS', value: elasticsearch.total_docs?.toLocaleString() },
              { label: 'LAST HOUR', value: elasticsearch.docs_last_1h?.toLocaleString() },
              { label: 'LAST 5 MIN', value: elasticsearch.docs_last_5m?.toLocaleString() },
              { label: 'INGEST RATE', value: `${elasticsearch.ingest_rate_per_min}/min` },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: 'var(--bg-3)', borderRadius: 2, padding: '6px 8px' }}>
                <div style={{ fontSize: 7, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 13, color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}>{value ?? '—'}</div>
              </div>
            ))}
          </div>
        )}
        {elasticsearch?.last_document && (
          <div style={{ marginTop: 6, fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            Last document: {ageStr(elasticsearch.last_document_age_s)} — {elasticsearch.last_document?.slice(0, 19).replace('T', ' ')}
            {elasticsearch.stale && <span style={{ color: 'var(--red)' }}> ⚠ STALE (&gt;10min)</span>}
          </div>
        )}
      </div>
    </div>
  )
}
```

### 3c — Add tab to TABS array

Find:
```js
const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats', 'Result Refs']
```

Replace with:
```js
const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats', 'Result Refs', 'Data Health']
```

### 3d — Add tab render

Find:
```jsx
        {tab === 'Result Refs' && <ResultRefsView />}
```

After that line, add:
```jsx
        {tab === 'Data Health' && <DataHealthView />}
```

---

## Do NOT touch

- Any collector files
- Any other router or component

---

## Version bump

Update `VERSION`: `2.21.1` → `2.21.2`

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.21.2 Data Health tab — pipeline monitoring for ES + PostgreSQL

- GET /api/status/pipeline: consolidated pipeline health endpoint
  - per-collector: running, health, last_poll age, stale flag (>3x interval)
  - PostgreSQL: connected, table row counts, snapshot freshness per component
  - Elasticsearch: total docs, docs last hour/5min, ingest rate/min, last doc age
  - alerts: stale_collectors, stale_pg_components, es_stale
- DataHealthView: new 'Data Health' sub-tab in LogsPanel
  - collector grid: dot + name + interval + last poll age + STALE badge if stuck
  - PG section: table row counts + per-component snapshot freshness with age
  - ES section: 4 metric tiles (total/1h/5m/rate) + last document timestamp
  - STALE alerts banner at top when any source is stale
  - Auto-refreshes every 30s
- fetchPipelineHealth() added to api.js"
git push origin main
```
