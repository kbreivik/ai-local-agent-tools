"""
Runbook classifier — select the best-matching runbook(s) for a task.

v1 (v2.35.4): keyword match.
  For each active runbook that applies to the current agent_type:
    score = count of triage_keywords found in task (case-insensitive,
             word-boundary match)
  Pick the single highest-score runbook with score > 0. Ties broken
  by priority (lower number wins).

Future versions (v2.35.5+):
  - Embedding similarity against runbook titles + keywords
  - LLM classifier for natural-language phrasing

Settings `runbookClassifierMode` gates which mode runs.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def select_runbook(task: str, agent_type: str, settings: dict | None = None) -> dict | None:
    """Return {runbook, score, matched_keywords} for the best runbook, or None."""
    s = settings or {}
    mode = s.get("runbookClassifierMode", "keyword") or "keyword"
    if mode == "keyword":
        return _keyword_select(task, agent_type)
    if mode == "semantic":
        result = _semantic_select(
            task, agent_type,
            threshold=float(s.get("runbookSemanticThreshold", 0.55)),
        )
        # Fall back to keyword if embedding unavailable
        if result is None:
            result = _keyword_select(task, agent_type)
        return result
    if mode == "llm":
        return _llm_select(task, agent_type)
    return None


def _keyword_select(task: str, agent_type: str) -> dict | None:
    from api.db.runbooks import list_active_runbooks_for_agent_type

    try:
        candidates = list_active_runbooks_for_agent_type(agent_type)
    except Exception as e:
        log.debug("runbook_classifier: list query failed: %s", e)
        return None

    if not candidates:
        return None

    task_lower = (task or "").lower()
    if not task_lower:
        return None

    scored: list[tuple[int, int, dict, list[str]]] = []
    for rb in candidates:
        score = 0
        matched: list[str] = []
        for kw in (rb.get("triage_keywords") or []):
            kw_lc = str(kw).lower().strip()
            if not kw_lc:
                continue
            # word-boundary match on a keyword phrase — works for
            # single tokens ('kafka') and multi-word phrases ('consumer lag')
            if re.search(rf"\b{re.escape(kw_lc)}\b", task_lower):
                score += 1
                matched.append(kw)
        if score > 0:
            scored.append((score, int(rb.get("priority", 100)), rb, matched))

    if not scored:
        return None

    # Highest score first, then lowest priority number
    scored.sort(key=lambda x: (-x[0], x[1]))
    s, _prio, rb, matched = scored[0]
    return {
        "runbook":          rb,
        "score":            s,
        "matched_keywords": matched,
    }


# Module-level embedding cache for runbooks (60s TTL)
_runbook_embed_cache: dict[str, list[float]] = {}
_runbook_embed_cache_ts: float = 0.0
_RUNBOOK_EMBED_CACHE_TTL = 60.0


def _embed(text: str) -> list[float] | None:
    """Embed text using the RAG model (bge-small-en-v1.5). Returns None on failure."""
    try:
        from api.rag.doc_search import embed
        return embed(text)
    except Exception as _e:
        log.debug("runbook_classifier._embed failed: %s", _e)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _semantic_select(task: str, agent_type: str,
                     threshold: float = 0.55) -> dict | None:
    """Embedding-based runbook selection using bge-small-en-v1.5.

    Embeds each runbook as '<title>: <keywords joined>' and scores against
    the task embedding. Returns the highest-scoring runbook above threshold,
    filtered by agent_type. Falls back to None if embedding unavailable.
    """
    import time as _t
    global _runbook_embed_cache, _runbook_embed_cache_ts

    task_vec = _embed(task[:512])
    if task_vec is None:
        return None  # embedding not available — caller falls back to keyword

    try:
        from api.db.runbooks import list_active_runbooks_for_agent_type
        candidates = list_active_runbooks_for_agent_type(agent_type)
    except Exception as e:
        log.debug("runbook_classifier._semantic_select: list query failed: %s", e)
        return None

    if not candidates:
        return None

    # Rebuild cache if stale
    now = _t.monotonic()
    if now - _runbook_embed_cache_ts > _RUNBOOK_EMBED_CACHE_TTL:
        _runbook_embed_cache = {}
        _runbook_embed_cache_ts = now

    scored = []
    for rb in candidates:
        rb_id = str(rb.get("id") or rb.get("title", ""))
        if rb_id not in _runbook_embed_cache:
            title = rb.get("title") or ""
            kws = " ".join(rb.get("triage_keywords") or [])
            rb_text = f"{title}: {kws}"[:512]
            vec = _embed(rb_text)
            if vec is None:
                continue
            _runbook_embed_cache[rb_id] = vec

        rb_vec = _runbook_embed_cache.get(rb_id)
        if rb_vec is None:
            continue

        sim = _cosine(task_vec, rb_vec)
        if sim >= threshold:
            scored.append((sim, int(rb.get("priority", 100)), rb))

    if not scored:
        return None

    scored.sort(key=lambda x: (-x[0], x[1]))
    sim, _prio, rb = scored[0]
    return {
        "runbook":          rb,
        "score":            round(sim, 4),
        "matched_keywords": [],   # semantic — no discrete keyword list
    }


def _llm_select(task: str, agent_type: str) -> dict | None:
    # Stub for v2.35.5 — LLM classifier
    return None


__all__ = ["select_runbook"]
