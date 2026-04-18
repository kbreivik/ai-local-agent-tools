"""Preflight resolver: figure out what the user's task is actually about,
before the agent loop starts.

Pipeline:
  Tier 1: regex extraction → explicit entity names
  Tier 2: keyword + time-window DB lookup → action-verb resolution
  Tier 3: LLM fallback → natural-language extraction (bounded)

Output is a PreflightResult with:
  - candidates:    list of resolved entities (0..N)
  - ambiguous:     true when candidates > 1 and human disambiguation needed
  - preflight_facts: list of known_facts to inject into system prompt
  - trace:         explanation of how each piece was resolved (for Preflight Panel)

Introduced in v2.35.1. Sync-only — project rule.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)


@dataclass
class PreflightCandidate:
    entity_id:   str
    entity_type: str
    source:      str       # 'regex' | 'keyword_db' | 'llm_fallback'
    confidence:  float
    evidence:    str
    metadata:    dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreflightResult:
    task:              str
    agent_type:        str
    candidates:        list   # [{candidate: PreflightCandidate, matches: [...]}]
    ambiguous:         bool
    preflight_facts:   list
    trace:             list
    tier_used:         str
    clarifying_needed: bool

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "agent_type": self.agent_type,
            "candidates": [_serialize_candidate_block(c) for c in self.candidates],
            "ambiguous": self.ambiguous,
            "preflight_facts": self.preflight_facts,
            "trace": self.trace,
            "tier_used": self.tier_used,
            "clarifying_needed": self.clarifying_needed,
        }


def _serialize_candidate_block(block: dict) -> dict:
    cand = block.get("candidate")
    return {
        "candidate": cand.as_dict() if hasattr(cand, "as_dict") else cand,
        "matches": block.get("matches", []),
    }


# ── Tier 1: regex ─────────────────────────────────────────────────────

# NOTE: more-specific patterns first — dedupe keeps only the first match for (id, type).
ENTITY_PATTERNS = [
    (r'\bkafka_broker-\d+\b',                      'kafka_broker'),
    (r'\bds-docker-(?:manager|worker)-\d+\b',      'swarm_node'),
    (r'\bhp1-prod-\w+\b',                          'proxmox_vm'),
    (r'\blogstash(?:_\w+)?\b',                     'swarm_service'),
    (r'\belasticsearch(?:_\w+)?\b',                'swarm_service'),
    (r'\b(?:nginx|caddy|traefik)(?:_\w+)?\b',      'swarm_service'),
    (r'\b[0-9a-f]{12}\b',                          'container_id'),
    (r'\b[a-z][a-z0-9]+(?:-[a-z0-9]+){1,4}\b',     'generic_host'),
]


def tier1_regex_extract(task: str) -> list:
    """Pull explicit named entities out of the task string via regex."""
    hits = []
    seen = set()
    for pattern, kind in ENTITY_PATTERNS:
        for m in re.finditer(pattern, task, re.IGNORECASE):
            ent = m.group(0)
            key = (ent.lower(), kind)
            if key in seen:
                continue
            # Avoid double-matching the same span under a broader pattern
            span_key = (ent.lower(), m.start())
            if span_key in seen:
                continue
            seen.add(key)
            seen.add(span_key)
            hits.append(PreflightCandidate(
                entity_id=ent,
                entity_type=kind,
                source='regex',
                confidence=0.9,
                evidence=f"regex match on pattern for {kind}",
            ))
    return hits


# ── Tier 2: keyword + time-window DB lookup ───────────────────────────

# Hardcoded defaults. Overridable via known_facts_keywords DB table.
# Each value is (resolver_name, default_window_minutes_or_None).
KEYWORD_RESOLVERS: dict[str, tuple[str, int | None]] = {
    'restarted':  ('_lookup_recent_restart_actions', None),
    'restart':    ('_lookup_recent_restart_actions', None),
    'rebooted':   ('_lookup_recent_reboot_actions', None),
    'reboot':     ('_lookup_recent_reboot_actions', None),
    'upgraded':   ('_lookup_recent_upgrade_actions', None),
    'upgrade':    ('_lookup_recent_upgrade_actions', None),
    'degraded':   ('_lookup_degraded_entities', None),
    'failing':    ('_lookup_failing_entities', None),
    'offline':    ('_lookup_offline_entities', None),
    'broken':     ('_lookup_recent_errors', None),
    'crashed':    ('_lookup_recent_crashes', None),
    'alerting':   ('_lookup_alerting_entities', None),
    'deployed':   ('_lookup_recent_deployments', None),
    'scaled':     ('_lookup_recent_scale_events', None),
}


# Natural-language time hints → lookup window in minutes.
TIME_HINTS: dict[str, int] = {
    'just':           30,
    'moments ago':    10,
    'recently':       120,
    'today':          1440,
    'yesterday':      2880,
    'last hour':      60,
    'last night':     720,
    'this morning':   360,
}


def load_keyword_corpus() -> dict:
    """Merge hardcoded defaults with DB-editable rows from
       known_facts_keywords. Silently falls back to defaults if table
       unavailable (e.g. SQLite, init not run yet)."""
    corpus = dict(KEYWORD_RESOLVERS)
    try:
        from api.db.known_facts import list_keywords_rows
        for row in list_keywords_rows(active_only=True) or []:
            kw = (row.get("keyword") or "").strip().lower()
            if not kw:
                continue
            resolver = row.get("resolver_name") or ""
            win = row.get("default_window_min")
            if resolver:
                corpus[kw] = (resolver, int(win) if win is not None else None)
    except Exception as e:
        log.debug("load_keyword_corpus fell back to defaults: %s", e)
    return corpus


def tier2_keyword_db(task: str, trace: list) -> list:
    task_lower = task.lower()
    corpus = load_keyword_corpus()

    time_window_min: int | None = None
    for hint, minutes in TIME_HINTS.items():
        if hint in task_lower:
            time_window_min = minutes if time_window_min is None else min(time_window_min, minutes)
            trace.append(f"time-hint '{hint}' → window {minutes}min")

    triggered = []
    for kw, (resolver_name, default_win) in corpus.items():
        if re.search(rf'\b{re.escape(kw)}\b', task_lower):
            window = time_window_min or default_win or 60
            triggered.append((kw, resolver_name, window))

    if not triggered:
        return []

    candidates: list[PreflightCandidate] = []
    for kw, resolver_name, window in triggered:
        trace.append(f"keyword '{kw}' → resolver {resolver_name}(window={window}min)")
        resolver = KEYWORD_RESOLVER_FUNCS.get(resolver_name)
        if not resolver:
            trace.append(f"  (resolver {resolver_name} not registered)")
            continue
        try:
            hits = resolver(window_min=window)
        except Exception as e:
            trace.append(f"  resolver {resolver_name} raised: {e}")
            continue
        for h in hits:
            candidates.append(PreflightCandidate(
                entity_id=h.get('entity_id', ''),
                entity_type=h.get('entity_type', 'unknown'),
                source='keyword_db',
                confidence=0.75,
                evidence=f"{kw} in last {window}min",
                metadata={'keyword': kw, 'window_min': window, **{k: v for k, v in h.items() if k not in ('entity_id', 'entity_type')}},
            ))
    return candidates


# ── Resolver implementations ──────────────────────────────────────────

def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _pg_conn():
    try:
        from api.connections import _get_conn
        return _get_conn()
    except Exception as e:
        log.debug("preflight pg conn failed: %s", e)
        return None


def _rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


_RESTART_TOOL_NAMES = (
    'swarm_service_force_update', 'proxmox_vm_power',
    'kafka_exec', 'vm_exec',
)


def _query_agent_actions(window_min: int, tool_patterns: list[str]) -> list[dict]:
    """Return recent agent_actions matching any of the tool_patterns (LIKE)."""
    if not _is_pg() or not tool_patterns:
        return []
    conn = _pg_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        placeholders = " OR ".join(["tool_name LIKE %s"] * len(tool_patterns))
        params = [f"%{p}%" for p in tool_patterns]
        params.append(window_min)
        cur.execute(
            f"SELECT id, timestamp, tool_name, args_redacted, result_status, "
            f"result_summary, owner_user FROM agent_actions "
            f"WHERE ({placeholders}) "
            f"  AND timestamp >= NOW() - (%s || ' minutes')::interval "
            f"ORDER BY timestamp DESC LIMIT 50",
            params,
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("_query_agent_actions failed: %s", e)
        try: conn.close()
        except Exception: pass
        return []


def _extract_entity_from_action(row: dict) -> tuple[str, str] | None:
    """Pull (entity_id, entity_type) out of a redacted agent_action row."""
    tool = row.get('tool_name', '') or ''
    args = row.get('args_redacted') or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if 'proxmox_vm_power' in tool:
        v = args.get('vm_label') or args.get('vmid') or args.get('vm')
        if v:
            return (str(v), 'proxmox_vm')
    if 'swarm_service' in tool:
        v = args.get('service_name') or args.get('service')
        if v:
            return (str(v), 'swarm_service')
    if 'kafka_exec' in tool:
        v = args.get('broker_label') or args.get('broker')
        if v:
            return (str(v), 'kafka_broker')
    if 'vm_exec' in tool:
        v = args.get('host') or args.get('hostname')
        if v:
            return (str(v), 'vm_host')
    return None


def _dedupe_entity_hits(raw_rows: list[dict]) -> list[dict]:
    seen: dict[tuple[str, str], dict] = {}
    for r in raw_rows:
        eid_typ = _extract_entity_from_action(r)
        if not eid_typ:
            continue
        key = eid_typ
        if key not in seen:
            seen[key] = {
                'entity_id': eid_typ[0],
                'entity_type': eid_typ[1],
                'when': r.get('timestamp'),
                'actor': r.get('owner_user') or '',
                'tool': r.get('tool_name') or '',
                'result': r.get('result_status') or '',
            }
    return list(seen.values())


def _lookup_recent_restart_actions(window_min: int = 60) -> list[dict]:
    rows = _query_agent_actions(window_min, list(_RESTART_TOOL_NAMES))
    filtered = []
    for r in rows:
        tool = (r.get('tool_name') or '').lower()
        args = r.get('args_redacted') or {}
        if isinstance(args, str):
            try: args = json.loads(args)
            except Exception: args = {}
        cmd = (args.get('command') or args.get('action') or '').lower()
        if any(x in tool for x in ('force_update', 'restart')) or 'restart' in cmd:
            filtered.append(r)
    return _dedupe_entity_hits(filtered)


def _lookup_recent_reboot_actions(window_min: int = 60) -> list[dict]:
    rows = _query_agent_actions(window_min, ['proxmox_vm_power', 'vm_exec', 'swarm'])
    filtered = []
    for r in rows:
        tool = (r.get('tool_name') or '').lower()
        args = r.get('args_redacted') or {}
        if isinstance(args, str):
            try: args = json.loads(args)
            except Exception: args = {}
        action = (args.get('action') or args.get('command') or '').lower()
        if 'reboot' in tool or 'reboot' in action or 'restart' in action:
            filtered.append(r)
    return _dedupe_entity_hits(filtered)


def _lookup_recent_upgrade_actions(window_min: int = 1440) -> list[dict]:
    rows = _query_agent_actions(window_min, ['swarm_service', 'docker_pull', 'image'])
    return _dedupe_entity_hits(rows)


def _lookup_degraded_entities(window_min: int = 60) -> list[dict]:
    if not _is_pg():
        return []
    conn = _pg_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id, new_status, timestamp FROM entity_history "
            "WHERE lower(new_status) IN ('degraded','warning') "
            "  AND timestamp >= NOW() - (%s || ' minutes')::interval "
            "ORDER BY timestamp DESC LIMIT 40",
            (window_min,),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        seen: dict[str, dict] = {}
        for r in rows:
            eid = r.get('entity_id') or ''
            if eid and eid not in seen:
                seen[eid] = {'entity_id': eid, 'entity_type': 'unknown',
                             'status': r.get('new_status'),
                             'when': r.get('timestamp')}
        return list(seen.values())
    except Exception as e:
        log.debug("_lookup_degraded_entities failed: %s", e)
        try: conn.close()
        except Exception: pass
        return []


def _lookup_failing_entities(window_min: int = 60) -> list[dict]:
    if not _is_pg():
        return []
    conn = _pg_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id, new_status, timestamp FROM entity_history "
            "WHERE lower(new_status) IN ('failed','failing','down','error') "
            "  AND timestamp >= NOW() - (%s || ' minutes')::interval "
            "ORDER BY timestamp DESC LIMIT 40",
            (window_min,),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        seen: dict[str, dict] = {}
        for r in rows:
            eid = r.get('entity_id') or ''
            if eid and eid not in seen:
                seen[eid] = {'entity_id': eid, 'entity_type': 'unknown',
                             'status': r.get('new_status'),
                             'when': r.get('timestamp')}
        return list(seen.values())
    except Exception as e:
        log.debug("_lookup_failing_entities failed: %s", e)
        try: conn.close()
        except Exception: pass
        return []


def _lookup_offline_entities(window_min: int = 60) -> list[dict]:
    if not _is_pg():
        return []
    conn = _pg_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id, new_status, timestamp FROM entity_history "
            "WHERE lower(new_status) IN ('down','offline','missing') "
            "  AND timestamp >= NOW() - (%s || ' minutes')::interval "
            "ORDER BY timestamp DESC LIMIT 40",
            (window_min,),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        seen: dict[str, dict] = {}
        for r in rows:
            eid = r.get('entity_id') or ''
            if eid and eid not in seen:
                seen[eid] = {'entity_id': eid, 'entity_type': 'unknown',
                             'status': r.get('new_status'),
                             'when': r.get('timestamp')}
        return list(seen.values())
    except Exception as e:
        log.debug("_lookup_offline_entities failed: %s", e)
        try: conn.close()
        except Exception: pass
        return []


def _lookup_recent_errors(window_min: int = 60) -> list[dict]:
    return _lookup_failing_entities(window_min)


def _lookup_recent_crashes(window_min: int = 60) -> list[dict]:
    return _lookup_failing_entities(window_min)


def _lookup_alerting_entities(window_min: int = 60) -> list[dict]:
    if not _is_pg():
        return []
    conn = _pg_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id, severity, created_at FROM alerts "
            "WHERE lower(COALESCE(status,'')) = 'firing' "
            "  AND created_at >= NOW() - (%s || ' minutes')::interval "
            "ORDER BY created_at DESC LIMIT 40",
            (window_min,),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        seen: dict[str, dict] = {}
        for r in rows:
            eid = r.get('entity_id') or ''
            if eid and eid not in seen:
                seen[eid] = {'entity_id': eid, 'entity_type': 'unknown',
                             'severity': r.get('severity'),
                             'when': r.get('created_at')}
        return list(seen.values())
    except Exception as e:
        log.debug("_lookup_alerting_entities failed: %s", e)
        try: conn.close()
        except Exception: pass
        return []


def _lookup_recent_deployments(window_min: int = 1440) -> list[dict]:
    rows = _query_agent_actions(window_min, ['swarm_service', 'docker', 'deploy'])
    return _dedupe_entity_hits(rows)


def _lookup_recent_scale_events(window_min: int = 60) -> list[dict]:
    rows = _query_agent_actions(window_min, ['swarm_service_scale', 'scale'])
    return _dedupe_entity_hits(rows)


KEYWORD_RESOLVER_FUNCS = {
    '_lookup_recent_restart_actions': _lookup_recent_restart_actions,
    '_lookup_recent_reboot_actions':  _lookup_recent_reboot_actions,
    '_lookup_recent_upgrade_actions': _lookup_recent_upgrade_actions,
    '_lookup_degraded_entities':      _lookup_degraded_entities,
    '_lookup_failing_entities':       _lookup_failing_entities,
    '_lookup_offline_entities':       _lookup_offline_entities,
    '_lookup_recent_errors':          _lookup_recent_errors,
    '_lookup_recent_crashes':         _lookup_recent_crashes,
    '_lookup_alerting_entities':      _lookup_alerting_entities,
    '_lookup_recent_deployments':     _lookup_recent_deployments,
    '_lookup_recent_scale_events':    _lookup_recent_scale_events,
}


# ── Tier 3: LLM fallback ──────────────────────────────────────────────

def _get_preflight_settings() -> dict:
    """Read preflight-related settings with sensible defaults."""
    out = {
        "preflightPanelMode": "always_visible",
        "preflightDisambiguationTimeout": 300,
        "preflightLLMFallbackEnabled": True,
        "preflightLLMFallbackMaxTokens": 200,
        "factInjectionThreshold": 0.7,
        "factInjectionMaxRows": 40,
    }
    try:
        from api.db.base import get_engine
        from sqlalchemy import text
        import asyncio
        async def _read():
            async with get_engine().connect() as conn:
                r = await conn.execute(text("SELECT key, value FROM settings WHERE key = ANY(:keys)"),
                                       {"keys": list(out.keys())})
                return r.fetchall()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running inside async context — skip (caller's build_prompt is sync)
                raise RuntimeError("skip")
            rows = loop.run_until_complete(_read())
        except Exception:
            rows = []
        for k, v in rows or []:
            if v is None or str(v).strip() == "":
                continue
            s = str(v).strip().lower()
            if s in ("true", "false"):
                out[k] = s == "true"
            else:
                try:
                    out[k] = float(v) if "." in str(v) else int(v)
                except (ValueError, TypeError):
                    out[k] = v
    except Exception:
        pass
    return out


def _llm_extract_entities(task: str, max_tokens: int) -> str:
    """Bounded LLM call. Returns the raw response text (JSON array expected)."""
    try:
        import os as _os
        from openai import OpenAI
        base_url = _os.environ.get("LM_STUDIO_BASE_URL", "http://192.168.199.51:1234/v1")
        api_key = _os.environ.get("LM_STUDIO_API_KEY", "lm-studio")
        model = _os.environ.get("LM_STUDIO_MODEL", "qwen/qwen3-coder-30b")
        client = OpenAI(base_url=base_url, api_key=api_key)
        prompt = (
            "List named infrastructure entities mentioned in this sentence. "
            "Return a JSON array of strings only, no explanation. If none, return []. "
            f"Sentence: {task}"
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.debug("_llm_extract_entities failed: %s", e)
        return ""


def tier3_llm_fallback(task: str, trace: list, settings: dict | None = None) -> list:
    """Last-resort extraction via LM Studio. Sync — bounded by max_tokens."""
    s = settings or _get_preflight_settings()
    if not s.get("preflightLLMFallbackEnabled", True):
        trace.append("tier3 LLM fallback disabled by setting")
        return []
    max_tokens = int(s.get("preflightLLMFallbackMaxTokens", 200))
    trace.append(f"tier3 LLM fallback (max_tokens={max_tokens})")

    raw = _llm_extract_entities(task, max_tokens)
    # Strip common Markdown code fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip().rstrip("`").strip()
    try:
        names = json.loads(cleaned)
        if not isinstance(names, list):
            raise ValueError("not a list")
    except Exception:
        trace.append(f"tier3 LLM response unparseable: {cleaned[:80]!r}")
        # Propose any extractable names as keyword suggestions
        _record_suggestion_from_llm(task, cleaned)
        return []

    hits: list[PreflightCandidate] = []
    for n in names:
        if not isinstance(n, str) or not n.strip():
            continue
        hits.append(PreflightCandidate(
            entity_id=n.strip(),
            entity_type='unknown',
            source='llm_fallback',
            confidence=0.5,
            evidence='LLM extraction from natural language',
        ))

    # Auto-propose suggestions: any LLM-extracted name NOT caught by tier 1/2
    # becomes a keyword suggestion for admin review.
    _record_suggestion_from_llm(task, names)
    return hits


def _record_suggestion_from_llm(task: str, proposal) -> None:
    try:
        from api.db.known_facts import record_keyword_suggestion
        record_keyword_suggestion(task=task, proposal=proposal)
    except Exception as e:
        log.debug("record_keyword_suggestion failed: %s", e)


# ── Inventory resolution ──────────────────────────────────────────────

def lookup_inventory(entity_id: str, entity_type: str) -> list[dict]:
    """Look up candidate matches in infra_inventory + connections."""
    if not entity_id:
        return []
    matches: list[dict] = []
    try:
        from api.db.infra_inventory import resolve_host
        row = resolve_host(entity_id)
        if row:
            matches.append({
                "entity_id": row.get("label") or entity_id,
                "display_name": row.get("label") or row.get("hostname") or entity_id,
                "platform": row.get("platform"),
                "metadata": {
                    "hostname": row.get("hostname"),
                    "ips": row.get("ips"),
                    "connection_id": row.get("connection_id"),
                },
            })
    except Exception as e:
        log.debug("lookup_inventory resolve_host failed: %s", e)
    # Dedupe by entity_id (case-insensitive)
    seen = set()
    out = []
    for m in matches:
        key = (m.get("entity_id") or "").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(m)
    return out


def get_confident_facts_for_entity(entity_id: str, min_confidence: float = 0.7,
                                    max_rows: int = 20) -> list[dict]:
    """Find known_facts rows whose fact_key contains the entity_id."""
    if not entity_id:
        return []
    try:
        from api.db.known_facts import get_confident_facts
        # Heuristic: look for fact_keys containing the entity_id (e.g. kafka.broker.3)
        stem = entity_id.lower().replace("_", ".").replace("-", ".")
        patterns = [f"*{entity_id}*", f"*{stem}*"]
        collected: list[dict] = []
        seen_keys = set()
        for pat in patterns:
            try:
                rows = get_confident_facts(pattern=pat,
                                           min_confidence=min_confidence,
                                           max_rows=max_rows)
            except Exception:
                rows = []
            for r in rows or []:
                k = (r.get("fact_key"), r.get("source"))
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                collected.append(r)
                if len(collected) >= max_rows:
                    return collected
        return collected
    except Exception as e:
        log.debug("get_confident_facts_for_entity failed: %s", e)
        return []


def resolve_against_inventory(candidates: list, trace: list,
                               min_confidence: float = 0.7,
                               max_facts: int = 40) -> tuple[list, list]:
    """Resolve each candidate against infra_inventory, then pull
    confident facts.

    v2.35.5 fix: infra_inventory coverage is sparse — mostly proxmox_vms
    and vm_hosts collectors write to it. Kafka brokers, Swarm services,
    containers, etc. have zero inventory rows. Previously this function
    gated fact injection on `len(matches) == 1`, so zero-inventory-match
    entities never got facts injected even when confident facts existed
    in known_facts.

    New behaviour:
      - 1 inventory match   → canonical entity_id from inventory → fact lookup
      - 0 inventory matches → regex-extracted entity_id          → direct fact lookup
      - >1 inventory matches → ambiguous, skip fact lookup
    """
    resolved: list[dict] = []
    facts_to_inject: list[dict] = []
    for c in candidates:
        matches = lookup_inventory(c.entity_id, c.entity_type)
        trace.append(
            f"'{c.entity_id}' ({c.entity_type}): {len(matches)} inventory matches"
        )

        fact_lookup_id: str | None = None
        fact_source: str = "no_facts_found"
        if len(matches) == 1:
            m = matches[0]
            fact_lookup_id = m.get("entity_id") or c.entity_id
            fact_source = "inventory_match"
        elif len(matches) == 0:
            # v2.35.5 — fall back to direct lookup against the extracted id.
            # known_facts is the SOT; infra_inventory coverage is sparse.
            fact_lookup_id = c.entity_id
            fact_source = "direct_entity"
            trace.append(
                f"  (no inventory match — trying direct fact lookup on "
                f"'{c.entity_id}')"
            )
        else:
            # Ambiguous. Preserve v2.35.1 behaviour: do not inject.
            fact_source = "ambiguous_skip"
            trace.append(
                f"  ({len(matches)} inventory matches — ambiguous, "
                f"skipping fact injection)"
            )

        if fact_lookup_id:
            fact_rows = get_confident_facts_for_entity(
                fact_lookup_id,
                min_confidence=min_confidence,
                max_rows=max_facts,
            )
            if fact_rows:
                facts_to_inject.extend(fact_rows)
                trace.append(f"  → {fact_lookup_id}: {len(fact_rows)} facts")
            else:
                # Downgrade the metric label if we found no facts even after
                # attempting a lookup, so we can tell the two zero-fact
                # outcomes apart (no lookup vs lookup-but-empty).
                fact_source = "no_facts_found"

        _bump_fact_source(fact_source)
        resolved.append({"candidate": c, "matches": matches})

    facts_to_inject.sort(
        key=lambda r: r.get("confidence", 0.0), reverse=True
    )
    if len(facts_to_inject) > max_facts:
        facts_to_inject = facts_to_inject[:max_facts]
    return resolved, facts_to_inject


def _bump_fact_source(source: str) -> None:
    """Increment the preflight fact-source counter. Silent on import failure."""
    try:
        from api.metrics import PREFLIGHT_FACT_SOURCE_COUNTER
        PREFLIGHT_FACT_SOURCE_COUNTER.labels(source=source).inc()
    except Exception:
        pass


# ── Metric shims ──────────────────────────────────────────────────────

def _bump_resolution_outcome(outcome: str) -> None:
    try:
        from api.metrics import PREFLIGHT_RESOLUTIONS_COUNTER
        PREFLIGHT_RESOLUTIONS_COUNTER.labels(outcome=outcome).inc()
    except Exception:
        pass


def _observe_facts_injected(n: int) -> None:
    try:
        from api.metrics import PREFLIGHT_FACTS_INJECTED
        PREFLIGHT_FACTS_INJECTED.observe(n)
    except Exception:
        pass


def record_disambiguation_outcome(result: str) -> None:
    """Call from router endpoints when a clarification resolves."""
    try:
        from api.metrics import PREFLIGHT_DISAMBIGUATION_OUTCOME_COUNTER
        PREFLIGHT_DISAMBIGUATION_OUTCOME_COUNTER.labels(result=result).inc()
    except Exception:
        pass


# ── Entry point ───────────────────────────────────────────────────────

def preflight_resolve(task: str, agent_type: str,
                      settings: dict | None = None) -> PreflightResult:
    """Main entry point — sync. Runs tiers 1 → 2 → 3 until something
    useful is found, then resolves candidates against inventory and
    pulls confident facts for unambiguous matches.
    """
    s = settings or _get_preflight_settings()
    trace: list[str] = [f"task: {task[:80]}", f"agent_type: {agent_type}"]

    t1 = tier1_regex_extract(task)
    trace.append(f"tier1: {len(t1)} regex matches")

    t2 = tier2_keyword_db(task, trace)
    trace.append(f"tier2: {len(t2)} keyword-DB matches")

    candidates = t1 + t2
    tier_used = "tier1+2"

    if len(candidates) == 0 and len(task) >= 50:
        t3 = tier3_llm_fallback(task, trace, s)
        trace.append(f"tier3: {len(t3)} LLM candidates")
        candidates = t3
        tier_used = "tier3"

    resolved, preflight_facts = resolve_against_inventory(
        candidates, trace,
        min_confidence=float(s.get("factInjectionThreshold", 0.7)),
        max_facts=int(s.get("factInjectionMaxRows", 40)),
    )

    # Ambiguity: any candidate whose entity_type was loose (e.g. 'unknown',
    # 'generic_host') AND which resolved to more than one inventory match
    # is considered ambiguous. Also: multiple distinct top-level candidates
    # produced from the same loose keyword (e.g. "the broker we restarted"
    # with 3 recent restart actions).
    ambiguous = False
    loose_kw_count = sum(
        1 for blk in resolved
        if blk["candidate"].source == "keyword_db"
    )
    if loose_kw_count > 1:
        ambiguous = True
    for blk in resolved:
        if len(blk.get("matches") or []) > 1:
            ambiguous = True
            break

    # Outcome metric
    if ambiguous:
        _bump_resolution_outcome("ambiguous")
    elif len(candidates) == 0:
        _bump_resolution_outcome("zero_hit")
    elif tier_used == "tier3":
        _bump_resolution_outcome("llm_fallback")
    elif any(c.source == "regex" for c in candidates):
        _bump_resolution_outcome("regex")
    else:
        _bump_resolution_outcome("keyword_db")

    _observe_facts_injected(len(preflight_facts))

    return PreflightResult(
        task=task,
        agent_type=agent_type,
        candidates=resolved,
        ambiguous=ambiguous,
        preflight_facts=preflight_facts,
        trace=trace,
        tier_used=tier_used,
        clarifying_needed=ambiguous,
    )


# ── Prompt section ────────────────────────────────────────────────────

def format_preflight_facts_section(preflight: PreflightResult,
                                    settings: dict | None = None) -> str:
    """Return the PREFLIGHT FACTS + PREFLIGHT TRACE section for the
    system prompt. Empty string if preflightPanelMode == 'off'.
    """
    s = settings or _get_preflight_settings()
    mode = str(s.get("preflightPanelMode", "always_visible")).strip().lower()
    if mode == "off":
        return ""

    threshold = float(s.get("factInjectionThreshold", 0.7))
    max_rows = int(s.get("factInjectionMaxRows", 40))
    rows = list(preflight.preflight_facts or [])[:max_rows]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def _age_str(last_verified) -> str:
        if not last_verified:
            return "age: ?"
        try:
            if isinstance(last_verified, str):
                lv = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
            else:
                lv = last_verified
            if lv.tzinfo is None:
                lv = lv.replace(tzinfo=timezone.utc)
            sec = int((now - lv).total_seconds())
            if sec < 60:  return f"age: {sec}s"
            if sec < 3600: return f"age: {sec // 60}min"
            if sec < 86400: return f"age: {sec // 3600}h"
            return f"age: {sec // 86400}d"
        except Exception:
            return "age: ?"

    lines = []
    if rows:
        lines.append(
            f"═══ PREFLIGHT FACTS (confidence ≥ {threshold:.2f}, verified within refresh cadence) ═══"
        )
        # Column-align fact_key → value (= aligned when possible)
        key_width = min(48, max((len(r.get("fact_key", "")) for r in rows), default=0))
        for r in rows:
            fk = r.get("fact_key", "")
            val = r.get("fact_value")
            if isinstance(val, (dict, list)):
                val_s = json.dumps(val, default=str)
            else:
                val_s = json.dumps(val) if isinstance(val, str) else str(val)
            src = r.get("source", "?")
            age = _age_str(r.get("last_verified"))
            conf = float(r.get("confidence", 0.0))
            lines.append(
                f"{fk.ljust(key_width)} = {val_s}  "
                f"(source: {src}, {age}, conf: {conf:.2f})"
            )
        lines.append("")
        lines.append("These facts come from infrastructure collectors. Cite them in your")
        lines.append("EVIDENCE block. Do NOT call a tool to re-verify unless you suspect")
        lines.append("the fact is stale or you need a value not listed above.")
        lines.append("")

    # Trace — always shown when a trace exists
    if preflight.trace:
        lines.append("═══ PREFLIGHT TRACE ═══")
        for t in preflight.trace:
            lines.append(f"• {t}")
        lines.append("")

    return "\n".join(lines)
