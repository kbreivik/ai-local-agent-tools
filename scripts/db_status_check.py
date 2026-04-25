#!/usr/bin/env python3
"""One-shot health queries against the running Postgres.

Usage:
    DATABASE_URL='postgresql://user:pass@host:5433/dbname' \
        python scripts/db_status_check.py

Accepts both `postgresql://` and `postgresql+asyncpg://` (the +asyncpg
prefix is stripped automatically). Designed to be run from agent-01 or
from a host with network access to the Postgres instance.
"""
from __future__ import annotations

import os
import sys

import psycopg2
import psycopg2.extras


QUERIES = [
    (
        "1. Latest test runs (last 7 days)",
        """
        SELECT suite_name, started_at, score_pct, duration_seconds
        FROM test_runs
        WHERE started_at > NOW() - INTERVAL '7 days'
        ORDER BY started_at DESC
        LIMIT 10;
        """,
    ),
    (
        "2. Facts source distribution",
        """
        SELECT source, COUNT(*) AS facts, MAX(last_verified) AS most_recent
        FROM known_facts_current
        GROUP BY source
        ORDER BY facts DESC;
        """,
    ),
    (
        "3. agent_attempts.summary populated ratio (last 7 days)",
        """
        SELECT
            COUNT(*) FILTER (WHERE summary != '' AND summary IS NOT NULL) AS populated,
            COUNT(*) AS total
        FROM agent_attempts
        WHERE created_at > NOW() - INTERVAL '7 days';
        """,
    ),
]


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    # psycopg2 doesn't grok the SQLAlchemy +asyncpg prefix.
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]

    try:
        conn = psycopg2.connect(url, connect_timeout=5)
    except psycopg2.OperationalError as e:
        print(f"ERROR: could not connect: {e}", file=sys.stderr)
        return 1

    conn.set_session(readonly=True, autocommit=True)

    for title, sql in QUERIES:
        print(f"\n── {title} " + "─" * (70 - len(title)))
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        except psycopg2.errors.UndefinedTable as e:
            print(f"  table missing: {e.diag.message_primary}")
            conn.rollback()
            continue
        except psycopg2.Error as e:
            print(f"  error: {e}")
            conn.rollback()
            continue
        if not rows:
            print("  (no rows)")
            continue
        cols = list(rows[0].keys())
        widths = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}
        header = "  " + " | ".join(c.ljust(widths[c]) for c in cols)
        sep = "  " + "-+-".join("-" * widths[c] for c in cols)
        print(header)
        print(sep)
        for r in rows:
            print("  " + " | ".join(str(r[c]).ljust(widths[c]) for c in cols))

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
