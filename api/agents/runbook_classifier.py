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
    settings = settings or {}
    mode = settings.get("runbookClassifierMode", "keyword") or "keyword"
    if mode == "keyword":
        return _keyword_select(task, agent_type)
    if mode == "semantic":
        return _semantic_select(task, agent_type)
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


def _semantic_select(task: str, agent_type: str) -> dict | None:
    # Stub for v2.35.5 — embedding-based
    return None


def _llm_select(task: str, agent_type: str) -> dict | None:
    # Stub for v2.35.5 — LLM classifier
    return None


__all__ = ["select_runbook"]
