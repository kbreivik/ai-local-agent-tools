"""Fabrication detector — v2.34.14.

Scans final_answer text for tool-call-shaped citations that don't match the
operation's actual tool_calls log. Rejects on fabrication score >= threshold.

The signal: confident fabrications structure their evidence as plausibly-named
tool calls with invented parameters (sub-agent bf3a71ea is the canonical case
— emitted a 10-line EVIDENCE block after making zero real tool calls).
Legitimate answers either call tools for real or say "no data available" —
they don't cite uncalled tools.
"""
import re
from typing import Iterable

# Match tool-call-shape strings: `identifier(args...)` at bullet start or
# in an evidence block.
_TOOL_CITE_RE = re.compile(
    r"(?:^|\n)\s*(?:[-\u2022*]|\d+\.)\s*`?([a-z][a-z0-9_]{2,40})\(",
    re.MULTILINE,
)

# Tools mentioned in prose ("I called X", "X returned Y") — count separately
# with lower weight.
# v2.35.11: require IMMEDIATE `(` after identifier — no whitespace.
# Tool calls are always `name(args)`. A space before `(` means
# parenthetical prose, not a citation.
_PROSE_CITE_RE = re.compile(
    r"\b([a-z][a-z0-9_]{2,40})\(",
)

# Ignore these — common English words or code patterns that look like calls.
_CITE_DENYLIST = frozenset({
    "print", "log", "return", "type", "int", "str", "list", "dict",
    "any", "all", "len", "min", "max", "sum", "map", "filter",
    "open", "close", "read", "write", "run", "get", "set", "add",
    "e.g", "i.e",
    # v2.35.11: common English words observed in synthesis prose
    "see", "via", "with", "using", "for", "from", "and", "or", "but",
    "unavailable", "available", "reachable", "failed", "running",
    "blocked", "registered", "scheduled", "confirmed", "lab", "tool",
    "call", "time", "step", "note", "tip", "hint",
    "docker", "swarm",  # tools start with `docker_` or `swarm_` not bare
})


def extract_cited_tools(text: str) -> list[str]:
    """Extract tool names cited in final_answer text."""
    evidence_cites = _TOOL_CITE_RE.findall(text or "")
    prose_cites = _PROSE_CITE_RE.findall(text or "")
    all_cites = set(evidence_cites) | set(prose_cites)
    return [c for c in all_cites if c not in _CITE_DENYLIST]


def score_fabrication(
    final_answer: str,
    actual_tool_names: Iterable[str],
) -> dict:
    """Return fabrication score + evidence.

    score = fraction of cited tools that were never actually called.
    score = 0.0 -> no fabrication evidence
    score = 1.0 -> every cited tool is invented
    """
    cited = extract_cited_tools(final_answer)
    actual = set(actual_tool_names or [])
    fabricated = [t for t in cited if t not in actual]
    score = (len(fabricated) / len(cited)) if cited else 0.0
    return {
        "score": score,
        "cited": cited,
        "actual": sorted(actual),
        "fabricated": fabricated,
    }


def is_fabrication(
    final_answer: str,
    actual_tool_names: Iterable[str],
    min_cites: int = 3,
    score_threshold: float = 0.5,
) -> tuple[bool, dict]:
    """Return (is_fabrication, scoring_detail).

    Fires when:
      - at least `min_cites` tool-call citations found
      - AND at least `score_threshold` of those aren't in actual_tool_names

    The min_cites threshold avoids false positives on short answers that
    just mention a couple of tool names in passing.
    """
    detail = score_fabrication(final_answer, actual_tool_names)
    fired = (
        len(detail["cited"]) >= min_cites
        and detail["score"] >= score_threshold
    )
    return fired, detail
