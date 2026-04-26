#!/usr/bin/env python3
"""Generate docs/REFERENCE.md — the canonical reference for DEATHSTAR's
runtime contracts: DB schema, route auth, WS events, log channels,
Prometheus counters, and common diagnostic queries.

Run via:
    make reference                   — generate from live PG (default)
    python scripts/gen_reference.py  — same
    python scripts/gen_reference.py --no-db — skip DB schema section

CI runs `make reference-check` which regenerates and fails if the working
tree diverges (i.e. someone forgot to commit after a schema change).

Sources:
  - DB schema: pg_catalog queries against $DATABASE_URL or hp1-postgres container
  - Route auth: AST walk over api/routers/*.py
  - WS events: regex over api/ for manager.broadcast({"type": ...})
  - Counters: AST walk over api/metrics.py
  - Hand-maintained: docs/reference_templates/{log_channels,diagnostic_queries}.md
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = REPO_ROOT / "api" / "routers"
METRICS_PATH = REPO_ROOT / "api" / "metrics.py"
TEMPLATES_DIR = REPO_ROOT / "docs" / "reference_templates"
OUTPUT_PATH = REPO_ROOT / "docs" / "REFERENCE.md"


# ─── Phase 1: DB schema ─────────────────────────────────────────────────────

DB_SCHEMA_QUERY = """
-- All user tables in the public schema
SELECT
    t.table_name,
    obj_description(c.oid, 'pg_class') AS description
FROM information_schema.tables t
JOIN pg_class c ON c.relname = t.table_name
WHERE t.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
ORDER BY t.table_name;
"""

DB_COLUMNS_QUERY = """
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default,
    character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
"""

DB_INDEXES_QUERY = """
SELECT
    t.relname AS table_name,
    i.relname AS index_name,
    array_to_string(array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)), ', ') AS columns,
    ix.indisunique AS is_unique,
    ix.indisprimary AS is_primary
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
GROUP BY t.relname, i.relname, ix.indisunique, ix.indisprimary
ORDER BY t.relname, i.relname;
"""


def fetch_db_schema(database_url: str | None) -> dict | None:
    """Connect to PG, run the three queries, return structured dict.

    Returns None if no DATABASE_URL set and no docker hp1-postgres reachable.
    Tries (1) DATABASE_URL env var with psycopg2, (2) docker exec on
    hp1-postgres container, (3) None (skip section with warning).
    """
    rows_tables: list[tuple] = []
    rows_columns: list[tuple] = []
    rows_indexes: list[tuple] = []

    # Try psycopg2 against DATABASE_URL first
    if database_url:
        try:
            import psycopg2
            # asyncpg-style URL → psycopg2-style
            url = database_url.replace("postgresql+asyncpg://", "postgresql://")
            conn = psycopg2.connect(url)
            cur = conn.cursor()
            cur.execute(DB_SCHEMA_QUERY)
            rows_tables = cur.fetchall()
            cur.execute(DB_COLUMNS_QUERY)
            rows_columns = cur.fetchall()
            cur.execute(DB_INDEXES_QUERY)
            rows_indexes = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[gen_reference] psycopg2 path failed: {e}", file=sys.stderr)
            rows_tables = []

    # Fallback: docker exec on hp1-postgres
    if not rows_tables:
        try:
            import subprocess as _sp
            for query, target in [
                (DB_SCHEMA_QUERY, "tables"),
                (DB_COLUMNS_QUERY, "columns"),
                (DB_INDEXES_QUERY, "indexes"),
            ]:
                result = _sp.run(
                    [
                        "docker", "exec", "-i", "hp1-postgres",
                        "psql", "-U", "hp1", "-d", "hp1_agent",
                        "-A", "-F", "\t", "-t", "-c", query,
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    print(f"[gen_reference] docker exec ({target}) failed: {result.stderr}",
                          file=sys.stderr)
                    return None
                lines = [l for l in result.stdout.split("\n") if l.strip()]
                parsed = [tuple(l.split("\t")) for l in lines]
                if target == "tables":
                    rows_tables = parsed
                elif target == "columns":
                    rows_columns = parsed
                elif target == "indexes":
                    rows_indexes = parsed
        except Exception as e:
            print(f"[gen_reference] docker fallback failed: {e}", file=sys.stderr)
            return None

    if not rows_tables:
        return None

    # Index columns and indexes by table name for assembly
    cols_by_table: dict[str, list] = {}
    for row in rows_columns:
        if not row or len(row) < 6:
            continue
        tbl = row[0]
        cols_by_table.setdefault(tbl, []).append({
            "name":         row[1],
            "type":         row[2],
            "nullable":     row[3] == "YES",
            "default":      row[4] or "",
            "max_length":   row[5] or "",
        })

    idx_by_table: dict[str, list] = {}
    for row in rows_indexes:
        if not row or len(row) < 5:
            continue
        tbl = row[0]
        idx_by_table.setdefault(tbl, []).append({
            "name":     row[1],
            "columns":  row[2],
            "unique":   str(row[3]).lower() in ("t", "true"),
            "primary":  str(row[4]).lower() in ("t", "true"),
        })

    tables = []
    for row in rows_tables:
        if not row:
            continue
        name = row[0]
        desc = row[1] if len(row) > 1 and row[1] else ""
        tables.append({
            "name":        name,
            "description": desc,
            "columns":     cols_by_table.get(name, []),
            "indexes":     idx_by_table.get(name, []),
        })

    return {"tables": tables}


def render_db_schema(schema: dict | None) -> str:
    if schema is None:
        return (
            "## 1. Database schema\n\n"
            "_Schema dump unavailable — DATABASE_URL not set and `hp1-postgres` "
            "container not reachable from the generator host. Run on agent-01 or "
            "set DATABASE_URL to a reachable Postgres instance._\n"
        )
    lines = [
        "## 1. Database schema",
        "",
        f"_{len(schema['tables'])} user tables in the `public` schema. "
        "Generated from live `pg_catalog` queries against the running database._",
        "",
    ]
    for t in schema["tables"]:
        lines.append(f"### `{t['name']}`")
        if t["description"]:
            lines.append("")
            lines.append(f"_{t['description']}_")
        lines.append("")
        if t["columns"]:
            lines.append("| Column | Type | Nullable | Default |")
            lines.append("|--------|------|----------|---------|")
            for col in t["columns"]:
                default = col["default"][:40] if col["default"] else ""
                col_type = col["type"]
                if col["max_length"]:
                    col_type = f"{col_type}({col['max_length']})"
                lines.append(
                    f"| `{col['name']}` | {col_type} | "
                    f"{'OK' if col['nullable'] else 'NO'} | {default} |"
                )
            lines.append("")
        if t["indexes"]:
            lines.append("**Indexes:**")
            for idx in t["indexes"]:
                tags = []
                if idx["primary"]:
                    tags.append("PK")
                if idx["unique"] and not idx["primary"]:
                    tags.append("UNIQUE")
                tag_str = f" _{', '.join(tags)}_" if tags else ""
                lines.append(f"- `{idx['name']}` ({idx['columns']}){tag_str}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


# ─── Phase 2: Route auth ─────────────────────────────────────────────────────

ROUTE_DECORATORS = ("get", "post", "put", "patch", "delete")


def extract_routes_from_router(path: Path) -> list[dict]:
    """AST-walk a single api/routers/*.py file, return route specs.

    Each route is a dict {file, line, method, path, prefix, requires_auth, function_name}.
    Auth detection: a route is "requires_auth" iff at least one of its parameter
    annotations resolves to `Depends(get_current_user)` (or alias).
    """
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return []

    # Detect router prefix from `router = APIRouter(prefix="/api/...")`
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "APIRouter"
            ):
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value or ""

    routes: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            method, route_path = _parse_route_decorator(dec)
            if method is None:
                continue
            requires_auth = _function_requires_auth(node)
            routes.append({
                "file":        path.relative_to(REPO_ROOT).as_posix(),
                "line":        node.lineno,
                "method":      method.upper(),
                "path":        prefix + route_path,
                "function":    node.name,
                "requires_auth": requires_auth,
            })
    return routes


def _parse_route_decorator(dec: ast.AST) -> tuple[str | None, str]:
    """Return (method, path) for @router.<verb>(...) decorator, or (None, '')."""
    if not isinstance(dec, ast.Call):
        return None, ""
    func = dec.func
    method = None
    if isinstance(func, ast.Attribute):
        if func.attr in ROUTE_DECORATORS:
            method = func.attr
    if method is None:
        return None, ""
    route_path = ""
    if dec.args and isinstance(dec.args[0], ast.Constant):
        route_path = dec.args[0].value or ""
    return method, route_path


_AUTH_DEP_NAMES = {"get_current_user", "get_current_user_optional"}


def _function_requires_auth(node: ast.AST) -> bool:
    """True iff any parameter has a default `Depends(get_current_user)`-style call."""
    if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
        return False
    args = node.args
    defaults = list(args.defaults) + list(args.kw_defaults)
    for d in defaults:
        if d is None:
            continue
        if (
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Name)
            and d.func.id == "Depends"
            and d.args
            and isinstance(d.args[0], ast.Name)
            and d.args[0].id in _AUTH_DEP_NAMES
        ):
            # `get_current_user_optional` is auth-aware but doesn't reject — mark partial
            return d.args[0].id == "get_current_user"
    return False


def collect_routes() -> list[dict]:
    routes = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        routes.extend(extract_routes_from_router(path))
    # Also scan main.py — some routes are defined there (e.g. /metrics, /health)
    main_path = REPO_ROOT / "api" / "main.py"
    if main_path.exists():
        routes.extend(extract_routes_from_router(main_path))
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return routes


def render_routes(routes: list[dict]) -> str:
    if not routes:
        return "## 2. Route authentication\n\n_No routes found._\n"
    auth_count = sum(1 for r in routes if r["requires_auth"])
    public_count = len(routes) - auth_count
    lines = [
        "## 2. Route authentication",
        "",
        f"_{len(routes)} routes total — {auth_count} authenticated, "
        f"{public_count} public. Generated by AST walk over `api/routers/*.py` "
        "+ `api/main.py`. A route is marked `auth` iff its handler has a "
        "`Depends(get_current_user)` parameter._",
        "",
        "| Method | Path | Auth | Handler | Source |",
        "|--------|------|------|---------|--------|",
    ]
    for r in routes:
        auth = "auth" if r["requires_auth"] else "public"
        lines.append(
            f"| {r['method']} | `{r['path']}` | {auth} | "
            f"`{r['function']}` | `{r['file']}:{r['line']}` |"
        )
    lines.append("")
    return "\n".join(lines)


# ─── Phase 3: WebSocket event types ──────────────────────────────────────────

_BROADCAST_RE = re.compile(
    r"manager\.broadcast\s*\(\s*\{[^}]*?[\"']type[\"']\s*:\s*[\"']([^\"']+)[\"']",
    re.DOTALL,
)


def collect_ws_events() -> list[dict]:
    """Walk api/ for manager.broadcast({"type": ...}) calls."""
    events: dict[str, list[tuple[str, int]]] = {}
    for path in (REPO_ROOT / "api").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in _BROADCAST_RE.finditer(src):
            ev_type = match.group(1)
            line = src[: match.start()].count("\n") + 1
            events.setdefault(ev_type, []).append(
                (path.relative_to(REPO_ROOT).as_posix(), line)
            )
    out = []
    for ev, sites in sorted(events.items()):
        out.append({"type": ev, "sites": sites, "count": len(sites)})
    return out


def render_ws_events(events: list[dict]) -> str:
    if not events:
        return "## 3. WebSocket event types\n\n_No events found._\n"
    lines = [
        "## 3. WebSocket event types",
        "",
        f"_{len(events)} distinct event types broadcast on `/ws/output`. "
        "Generated by regex over `manager.broadcast({\"type\": ...})` "
        "across `api/`. Sites column shows file and line of each broadcast._",
        "",
        "| Type | Sites |",
        "|------|-------|",
    ]
    for ev in events:
        sites_str = ", ".join(f"`{s[0]}:{s[1]}`" for s in ev["sites"][:3])
        if len(ev["sites"]) > 3:
            sites_str += f" _(+{len(ev['sites']) - 3} more)_"
        lines.append(f"| `{ev['type']}` | {sites_str} |")
    lines.append("")
    return "\n".join(lines)


# ─── Phase 4: Log channels (template) ────────────────────────────────────────

def render_log_channels() -> str:
    template_path = TEMPLATES_DIR / "log_channels.md"
    if template_path.exists():
        return "## 4. Log channels\n\n" + template_path.read_text(encoding="utf-8")
    return (
        "## 4. Log channels\n\n"
        "_(Template at `docs/reference_templates/log_channels.md` missing — "
        "create it.)_\n"
    )


# ─── Phase 5: Prometheus counter inventory ───────────────────────────────────

_COUNTER_TYPES = {"Counter", "Gauge", "Histogram", "Summary", "Info"}


def collect_metrics() -> list[dict]:
    if not METRICS_PATH.exists():
        return []
    src = METRICS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    metrics = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        type_name = None
        if isinstance(func, ast.Name):
            type_name = func.id
        elif isinstance(func, ast.Attribute):
            type_name = func.attr
        if type_name not in _COUNTER_TYPES:
            continue
        # Var name on LHS
        if not (node.targets and isinstance(node.targets[0], ast.Name)):
            continue
        var_name = node.targets[0].id
        # Pull positional + keyword args
        prom_name = ""
        prom_help = ""
        labels: list[str] = []
        if node.value.args and isinstance(node.value.args[0], ast.Constant):
            prom_name = node.value.args[0].value or ""
        if len(node.value.args) >= 2 and isinstance(node.value.args[1], ast.Constant):
            prom_help = node.value.args[1].value or ""
        for kw in node.value.keywords:
            if kw.arg in ("labelnames", "labels") and isinstance(kw.value, (ast.List, ast.Tuple)):
                labels = [
                    el.value for el in kw.value.elts
                    if isinstance(el, ast.Constant)
                ]
        # Third positional may be labels too (Counter("x", "help", ["a","b"]))
        if not labels and len(node.value.args) >= 3:
            third = node.value.args[2]
            if isinstance(third, (ast.List, ast.Tuple)):
                labels = [
                    el.value for el in third.elts
                    if isinstance(el, ast.Constant)
                ]
        metrics.append({
            "var":    var_name,
            "type":   type_name,
            "name":   prom_name,
            "help":   prom_help,
            "labels": labels,
            "line":   node.lineno,
        })
    metrics.sort(key=lambda m: m["line"])
    return metrics


def render_metrics(metrics: list[dict]) -> str:
    if not metrics:
        return "## 5. Prometheus counter inventory\n\n_None found._\n"
    lines = [
        "## 5. Prometheus counter inventory",
        "",
        f"_{len(metrics)} metrics defined in `api/metrics.py`. "
        "**Important:** counters only appear in `/metrics` output AFTER "
        "their first `.inc()` call — a defined-but-never-incremented counter "
        "produces no output line. Use container logs (`[harness]`, etc.) or "
        "`operation_log` table for behaviour confirmation, not just `/metrics`. "
        "Endpoint is auth-gated (since v2.45.21)._",
        "",
        "| Type | Prom name | Labels | Help |",
        "|------|-----------|--------|------|",
    ]
    for m in metrics:
        labels = ", ".join(f"`{l}`" for l in m["labels"]) or "—"
        help_short = m["help"][:80].replace("|", "\\|")
        lines.append(f"| {m['type']} | `{m['name']}` | {labels} | {help_short} |")
    lines.append("")
    return "\n".join(lines)


# ─── Phase 6: Diagnostic queries (template) ─────────────────────────────────

def render_diagnostic_queries() -> str:
    template_path = TEMPLATES_DIR / "diagnostic_queries.md"
    if template_path.exists():
        return "## 6. Common diagnostic queries\n\n" + template_path.read_text(encoding="utf-8")
    return (
        "## 6. Common diagnostic queries\n\n"
        "_(Template at `docs/reference_templates/diagnostic_queries.md` missing — "
        "create it.)_\n"
    )


# ─── Main ────────────────────────────────────────────────────────────────────

def render_header(skipped_db: bool) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = (REPO_ROOT / "VERSION").read_text().strip()
    note = ""
    if skipped_db:
        note = (
            "\n\n> **Note:** DB schema section was skipped (no Postgres reachable). "
            "Regenerate from agent-01 or set `DATABASE_URL` for full output.\n"
        )
    return (
        f"# DEATHSTAR — Reference\n\n"
        f"_Auto-generated by `scripts/gen_reference.py` from live signals.{note}_\n\n"
        f"**Version:** v{version}  •  **Generated:** {ts}\n\n"
        "**This file is generated. Do not edit by hand** — edit the templates "
        "in `docs/reference_templates/` or the generator itself.\n\n"
        "---\n\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-db", action="store_true",
                        help="Skip DB schema phase (use when no PG reachable)")
    parser.add_argument("--check", action="store_true",
                        help="Generate to a temp file and diff against the committed copy. "
                             "Exit 1 if they differ. Used by CI.")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    schema = None if args.no_db else fetch_db_schema(db_url)
    routes = collect_routes()
    ws_events = collect_ws_events()
    metrics = collect_metrics()

    body = "".join([
        render_header(skipped_db=(schema is None and not args.no_db)),
        render_db_schema(schema), "\n\n",
        render_routes(routes), "\n\n",
        render_ws_events(ws_events), "\n\n",
        render_log_channels(), "\n\n",
        render_metrics(metrics), "\n\n",
        render_diagnostic_queries(), "\n",
    ])

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"[gen_reference] {OUTPUT_PATH} missing — run `make reference`",
                  file=sys.stderr)
            return 1
        existing = OUTPUT_PATH.read_text(encoding="utf-8")
        # Strip the "Generated:" timestamp line — that's expected to drift run-to-run
        def _strip_ts(s: str) -> str:
            return re.sub(r"\*\*Generated:\*\*[^\n]+", "**Generated:** -", s)
        if _strip_ts(existing) == _strip_ts(body):
            print("[gen_reference] OK — REFERENCE.md is up-to-date.")
            return 0
        print("[gen_reference] FAIL — REFERENCE.md is stale. Run `make reference` and commit.",
              file=sys.stderr)
        # Show first 30 lines of unified diff for the failure log
        import difflib
        diff = list(difflib.unified_diff(
            _strip_ts(existing).splitlines(keepends=True),
            _strip_ts(body).splitlines(keepends=True),
            fromfile="committed", tofile="regenerated",
            n=2,
        ))
        sys.stderr.writelines(diff[:80])
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(body, encoding="utf-8")
    print(f"[gen_reference] wrote {OUTPUT_PATH} "
          f"({len(routes)} routes, {len(ws_events)} ws events, "
          f"{len(metrics)} metrics, "
          f"{len(schema['tables']) if schema else 0} tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
