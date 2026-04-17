"""
Weekly scan of agent_actions for repeated tool-invocation patterns.
Writes candidates to skill_candidates table.
"""
import asyncio, hashlib, json, logging
from api.db.skill_candidates import upsert_candidate, ensure_schema

log = logging.getLogger(__name__)

# Normalize args -> a "shape" (argnames + value-type, not value).
# For vm_exec specifically, we keep the *host* in the shape because
# per-host skills are more useful than per-command-per-host.
SHAPE_RULES = {
    "vm_exec": lambda args: {"host": args.get("host"), "command_first_token": (args.get("command") or "").split()[0:1]},
    # default: just argnames + types
}

def shape_hash_of(tool: str, args: dict) -> tuple[str, dict]:
    rule = SHAPE_RULES.get(tool)
    if rule:
        shape = rule(args)
    else:
        shape = {k: type(v).__name__ for k, v in (args or {}).items()}
    serialized = json.dumps(shape, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode()).hexdigest(), shape

async def detect_candidates(pool, min_occ=5, min_tasks=2, window_days=7):
    await ensure_schema(pool)
    sql = """
      SELECT tool, args, task_id FROM agent_actions
      WHERE created_at > NOW() - ($1 || ' days')::interval
    """
    async with pool.acquire() as c:
        rows = await c.fetch(sql, str(window_days))
    buckets = {}
    for r in rows:
        args = r["args"] if isinstance(r["args"], dict) else json.loads(r["args"] or "{}")
        h, shape = shape_hash_of(r["tool"], args)
        key = (r["tool"], h)
        b = buckets.setdefault(key, {"count": 0, "tasks": set(), "sample": args, "shape": shape})
        b["count"] += 1
        b["tasks"].add(r["task_id"])
    promoted = 0
    for (tool, h), b in buckets.items():
        if b["count"] >= min_occ and len(b["tasks"]) >= min_tasks:
            name, desc = _suggest_name(tool, b["shape"], b["sample"])
            await upsert_candidate(pool, tool, h, b["sample"], b["count"],
                                   len(b["tasks"]), name, desc)
            promoted += 1
    log.info("auto_promoter: scanned %d actions, %d candidates", len(rows), promoted)
    return promoted

def _suggest_name(tool, shape, sample):
    if tool == "vm_exec" and shape.get("host"):
        first = " ".join(shape.get("command_first_token") or [])
        safe = first.replace("/", "_").replace("-", "_")[:20] or "run"
        name = f"vm_{safe}_on_{shape['host'].replace('-', '_').replace('.', '_')}"
        desc = f"Auto-promoted vm_exec pattern: `{first}` on host {shape['host']}"
    else:
        name = f"auto_{tool}_{hash(str(shape)) & 0xffff:04x}"
        desc = f"Auto-promoted {tool} with shape {shape}"
    return name, desc

async def schedule_weekly(pool):
    while True:
        try:
            await detect_candidates(pool)
        except Exception as e:
            log.exception("auto_promoter loop error: %s", e)
        await asyncio.sleep(7 * 24 * 3600)
