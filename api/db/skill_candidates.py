"""
skill_candidates — auto-detected patterns awaiting operator approval for promotion.
"""
import json

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS skill_candidates (
    id SERIAL PRIMARY KEY,
    tool TEXT NOT NULL,
    args_shape_hash TEXT NOT NULL,
    sample_args JSONB NOT NULL,
    occurrences INT NOT NULL,
    distinct_tasks INT NOT NULL,
    suggested_name TEXT NOT NULL,
    suggested_description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | promoted
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decided_by TEXT,
    promoted_skill_id INT,
    UNIQUE (tool, args_shape_hash)
);
"""

async def ensure_schema(pool):
    async with pool.acquire() as c:
        await c.execute(CREATE_SQL)

async def list_candidates(pool, status='pending'):
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM skill_candidates WHERE status = $1 ORDER BY occurrences DESC LIMIT 50",
            status
        )
        return [dict(r) for r in rows]

async def upsert_candidate(pool, tool, shape_hash, sample_args, occ, tasks, name, desc):
    async with pool.acquire() as c:
        await c.execute("""
            INSERT INTO skill_candidates (tool, args_shape_hash, sample_args,
                occurrences, distinct_tasks, suggested_name, suggested_description)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)
            ON CONFLICT (tool, args_shape_hash) DO UPDATE
              SET occurrences = EXCLUDED.occurrences,
                  distinct_tasks = EXCLUDED.distinct_tasks,
                  suggested_description = EXCLUDED.suggested_description
        """, tool, shape_hash, json.dumps(sample_args), occ, tasks, name, desc)
