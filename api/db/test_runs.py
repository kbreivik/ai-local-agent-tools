"""DB helpers for test run history (v2.44.1)."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

import logging
log = logging.getLogger(__name__)


def _conn():
    from api.connections import _get_conn
    return _get_conn()


def _is_pg():
    try:
        c = _conn()
        if c:
            c.close()
            return True
    except Exception:
        return False
    return False


def _ts():
    return datetime.now(timezone.utc).isoformat()


# ── Suites ────────────────────────────────────────────────────────────────────

def list_suites() -> list[dict]:
    if not _is_pg():
        return []
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT id, name, description, test_ids, categories, config, created_at, updated_at FROM test_suites ORDER BY updated_at DESC")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k in ('test_ids', 'categories', 'config'):
                if isinstance(r.get(k), str):
                    try:
                        r[k] = json.loads(r[k])
                    except Exception:
                        pass
            r['id'] = str(r['id'])
        return rows
    except Exception as e:
        log.debug("list_suites: %s", e)
        return []


def upsert_suite(name: str, description: str = '', test_ids: list = None,
                 categories: list = None, config: dict = None, suite_id: str = None) -> dict:
    if not _is_pg():
        return {}
    try:
        conn = _conn(); cur = conn.cursor()
        sid = suite_id or str(uuid.uuid4())
        cur.execute("""
            INSERT INTO test_suites (id, name, description, test_ids, categories, config, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (name) DO UPDATE SET
                description=EXCLUDED.description, test_ids=EXCLUDED.test_ids,
                categories=EXCLUDED.categories, config=EXCLUDED.config, updated_at=NOW()
            RETURNING id, name
        """, (sid, name, description or '',
              json.dumps(test_ids or []), json.dumps(categories or []), json.dumps(config or {})))
        row = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return {'id': str(row[0]), 'name': row[1]}
    except Exception as e:
        log.debug("upsert_suite: %s", e)
        return {}


def delete_suite(suite_id: str) -> bool:
    if not _is_pg():
        return False
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("DELETE FROM test_suites WHERE id=%s", (suite_id,))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("delete_suite: %s", e)
        return False


# ── Runs ──────────────────────────────────────────────────────────────────────

def create_run(suite_id: str = None, suite_name: str = '', config: dict = None,
               triggered_by: str = 'manual', started_at=None) -> str:
    if not _is_pg():
        return str(uuid.uuid4())
    try:
        conn = _conn(); cur = conn.cursor()
        run_id = str(uuid.uuid4())
        if started_at is not None:
            cur.execute("""
                INSERT INTO test_runs (id, suite_id, suite_name, config, triggered_by, started_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (run_id, suite_id, suite_name, json.dumps(config or {}), triggered_by, started_at))
        else:
            cur.execute("""
                INSERT INTO test_runs (id, suite_id, suite_name, config, triggered_by)
                VALUES (%s, %s, %s, %s, %s)
            """, (run_id, suite_id, suite_name, json.dumps(config or {}), triggered_by))
        conn.commit(); cur.close(); conn.close()
        return run_id
    except Exception as e:
        log.debug("create_run: %s", e)
        return str(uuid.uuid4())


def finish_run(run_id: str, total: int, passed: int, score_pct: float,
               weighted_pct: float = 0.0, error: str = '', finished_at=None) -> None:
    if not _is_pg():
        return
    try:
        conn = _conn(); cur = conn.cursor()
        status = 'error' if error else 'completed'
        _fin = finished_at if finished_at is not None else 'NOW()'
        if finished_at is not None:
            cur.execute("""
                UPDATE test_runs SET
                    finished_at=%s, status=%s, total=%s, passed=%s,
                    failed=%s, score_pct=%s, weighted_pct=%s, error=%s
                WHERE id=%s
            """, (finished_at, status, total, passed, total - passed, score_pct, weighted_pct, error, run_id))
        else:
            cur.execute("""
                UPDATE test_runs SET
                    finished_at=NOW(), status=%s, total=%s, passed=%s,
                    failed=%s, score_pct=%s, weighted_pct=%s, error=%s
                WHERE id=%s
            """, (status, total, passed, total - passed, score_pct, weighted_pct, error, run_id))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("finish_run: %s", e)


def insert_result(run_id: str, r: dict) -> None:
    if not _is_pg():
        return
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO test_run_results
                (run_id, test_id, category, task, passed, soft, critical,
                 failures, warnings, agent_type, tools_called, step_count,
                 duration_s, timed_out,
                 clarification_question, clarification_answer_used,
                 plan_summary, plan_steps_count, plan_approved, operation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s)
        """, (run_id, r['id'], r.get('category', ''), r.get('task', ''),
              r.get('passed', False), r.get('soft', False), r.get('critical', False),
              json.dumps(r.get('failures', [])), json.dumps(r.get('warnings', [])),
              r.get('agent_type', ''), json.dumps(r.get('tools_called', [])),
              r.get('step_count', 0), r.get('duration_s', 0),
              r.get('timed_out', False),
              r.get('clarification_question', ''),
              r.get('clarification_answer_used', ''),
              r.get('plan_summary', ''),
              r.get('plan_steps_count', 0),
              r.get('plan_approved', False),
              r.get('operation_id', '')))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("insert_result: %s", e)


def list_runs(limit: int = 50, suite_id: str = None) -> list[dict]:
    if not _is_pg():
        return []
    try:
        conn = _conn(); cur = conn.cursor()
        if suite_id:
            cur.execute("SELECT id,suite_id,suite_name,config,started_at,finished_at,status,total,passed,failed,score_pct,weighted_pct,triggered_by FROM test_runs WHERE suite_id=%s ORDER BY started_at DESC LIMIT %s", (suite_id, limit))
        else:
            cur.execute("SELECT id,suite_id,suite_name,config,started_at,finished_at,status,total,passed,failed,score_pct,weighted_pct,triggered_by FROM test_runs ORDER BY started_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            r['id'] = str(r['id'])
            if r.get('suite_id'):
                r['suite_id'] = str(r['suite_id'])
            if isinstance(r.get('config'), str):
                try:
                    r['config'] = json.loads(r['config'])
                except Exception:
                    pass
        return rows
    except Exception as e:
        log.debug("list_runs: %s", e)
        return []


def get_run(run_id: str) -> dict:
    if not _is_pg():
        return {}
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT id,suite_id,suite_name,config,started_at,finished_at,status,total,passed,failed,score_pct,weighted_pct,triggered_by,error FROM test_runs WHERE id=%s", (run_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return {}
        run = dict(zip(cols, row))
        run['id'] = str(run['id'])
        if isinstance(run.get('config'), str):
            try:
                run['config'] = json.loads(run['config'])
            except Exception:
                pass

        cur.execute("""
            SELECT id,test_id,category,task,passed,soft,critical,failures,warnings,
                   agent_type,tools_called,step_count,duration_s,timed_out,timestamp,
                   clarification_question,clarification_answer_used,
                   plan_summary,plan_steps_count,plan_approved,operation_id
            FROM test_run_results WHERE run_id=%s ORDER BY timestamp ASC
        """, (run_id,))
        rcols = [d[0] for d in cur.description]
        results = []
        for rrow in cur.fetchall():
            res = dict(zip(rcols, rrow))
            res['id'] = str(res['id'])
            for k in ('failures', 'warnings', 'tools_called'):
                if isinstance(res.get(k), str):
                    try:
                        res[k] = json.loads(res[k])
                    except Exception:
                        pass
            results.append(res)
        run['results'] = results
        cur.close(); conn.close()
        return run
    except Exception as e:
        log.debug("get_run: %s", e)
        return {}


def get_compare(run_ids: list[str]) -> list[dict]:
    return [get_run(rid) for rid in run_ids[:4]]


def get_trend(suite_id: str = None, limit: int = 30) -> list[dict]:
    if not _is_pg():
        return []
    try:
        conn = _conn(); cur = conn.cursor()
        if suite_id:
            cur.execute("SELECT id,started_at,score_pct,weighted_pct,total,passed FROM test_runs WHERE suite_id=%s AND status='completed' ORDER BY started_at DESC LIMIT %s", (suite_id, limit))
        else:
            cur.execute("SELECT id,started_at,score_pct,weighted_pct,total,passed FROM test_runs WHERE status='completed' ORDER BY started_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            r['id'] = str(r['id'])
        return list(reversed(rows))
    except Exception as e:
        log.debug("get_trend: %s", e)
        return []


# ── Schedules ─────────────────────────────────────────────────────────────────

def list_schedules() -> list[dict]:
    if not _is_pg():
        return []
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("SELECT id,name,suite_id,cron,enabled,last_run_at,next_run_at,created_at FROM test_schedules ORDER BY created_at DESC")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            r['id'] = str(r['id'])
            if r.get('suite_id'):
                r['suite_id'] = str(r['suite_id'])
        return rows
    except Exception as e:
        log.debug("list_schedules: %s", e)
        return []


def upsert_schedule(name: str, suite_id: str, cron: str, enabled: bool = True) -> dict:
    if not _is_pg():
        return {}
    try:
        conn = _conn(); cur = conn.cursor()
        sid = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO test_schedules (id, name, suite_id, cron, enabled)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING id
        """, (sid, name, suite_id, cron, enabled))
        row = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return {'id': str(row[0])}
    except Exception as e:
        log.debug("upsert_schedule: %s", e)
        return {}


def delete_schedule(schedule_id: str) -> bool:
    if not _is_pg():
        return False
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("DELETE FROM test_schedules WHERE id=%s", (schedule_id,))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("delete_schedule: %s", e)
        return False


def toggle_schedule(schedule_id: str, enabled: bool) -> bool:
    if not _is_pg():
        return False
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("UPDATE test_schedules SET enabled=%s WHERE id=%s", (enabled, schedule_id))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("toggle_schedule: %s", e)
        return False
