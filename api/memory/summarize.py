"""
Pattern analysis over outcome engrams stored in MuninnDB.

Fetches engrams tagged 'outcome'/'feedback', parses content fields,
and returns a structured summary used by GET /api/memory/patterns.
"""
import re
from collections import Counter, defaultdict
from typing import Any

from api.memory.client import get_client


async def get_patterns() -> dict[str, Any]:
    """
    Fetch all outcome + feedback engrams, compute pattern summary.
    """
    client = get_client()

    # Fetch by concept prefix search
    outcome_engrams  = await client.search("outcome:",  limit=200)
    assoc_engrams    = await client.search("tools_for:", limit=200)
    feedback_engrams = await client.search("feedback:",  limit=200)

    outcomes = [e for e in outcome_engrams  if e.get("concept", "").startswith("outcome:")]
    feedbacks = [e for e in feedback_engrams if e.get("concept", "").startswith("feedback:")]

    if not outcomes:
        return {
            "total_runs": 0,
            "status_breakdown": {},
            "most_successful_sequences": [],
            "most_failed_sequences": [],
            "common_escalation_tasks": [],
            "avg_steps_per_agent_type": {},
            "top_tools": [],
            "tool_error_rates": {},
            "positive_signals": len([f for f in feedbacks if "positive" in f.get("concept", "")]),
            "negative_signals": len([f for f in feedbacks if "negative" in f.get("concept", "")]),
            "recommendations": ["No outcome data yet — run agent tasks to build history."],
        }

    parsed = [p for p in (_parse_outcome(e) for e in outcomes) if p]

    status_counts       = defaultdict(int)
    agent_steps         = defaultdict(list)
    tool_total          = defaultdict(int)
    tool_success        = defaultdict(int)
    tool_fail           = defaultdict(int)
    success_sequences   = []
    fail_sequences      = []
    escalation_tasks    = []

    for p in parsed:
        s = p["status"]
        status_counts[s] += 1
        agent_steps[p["agent_type"]].append(p["steps"])

        for tool in p["tools"]:
            tool_total[tool] += 1
            if s == "completed":
                tool_success[tool] += 1
            elif s in ("failed", "escalated"):
                tool_fail[tool] += 1

        seq = p["tools"][:6]
        if s == "completed":
            success_sequences.append(seq)
        elif s in ("failed", "escalated"):
            fail_sequences.append(seq)
            if p["task"]:
                escalation_tasks.append(p["task"])

    avg_steps = {
        agent: round(sum(steps) / len(steps), 1)
        for agent, steps in agent_steps.items()
        if steps
    }

    tool_error_rates = {
        tool: {
            "total": tool_total[tool],
            "error_rate": round(tool_fail.get(tool, 0) / tool_total[tool] * 100, 1),
        }
        for tool in tool_total
        if tool_total[tool] >= 2
    }

    top_tools = [
        {"tool": t, "count": c}
        for t, c in sorted(tool_total.items(), key=lambda x: -x[1])[:10]
    ]

    pos_signals = [f for f in feedbacks if "positive" in f.get("concept", "")]
    neg_signals = [f for f in feedbacks if "negative" in f.get("concept", "")]

    recs = _generate_recommendations(parsed, tool_success, tool_fail, tool_total, feedbacks)

    return {
        "total_runs": len(parsed),
        "status_breakdown": dict(status_counts),
        "most_successful_sequences": _top_sequences(success_sequences, 5),
        "most_failed_sequences": _top_sequences(fail_sequences, 5),
        "common_escalation_tasks": list(dict.fromkeys(escalation_tasks))[:5],
        "avg_steps_per_agent_type": avg_steps,
        "top_tools": top_tools,
        "tool_error_rates": tool_error_rates,
        "positive_signals": len(pos_signals),
        "negative_signals": len(neg_signals),
        "recommendations": recs,
    }


def _parse_outcome(engram: dict) -> dict | None:
    content = engram.get("content", "")
    concept = engram.get("concept", "")
    try:
        task_m   = re.search(r"Task:\s*(.+)",   content)
        status_m = re.search(r"Status:\s*(\w+)", content)
        steps_m  = re.search(r"Steps:\s*(\d+)",  content)
        tools_m  = re.search(r"Tools:\s*(.+)",   content)
        agent_m  = re.search(r"Agent:\s*(\w+)",  content)

        agent_type = agent_m.group(1).strip() if agent_m else concept.split(":")[1] if len(concept.split(":")) > 1 else "unknown"
        tools_raw  = tools_m.group(1).strip()  if tools_m  else ""
        tools      = [t.strip() for t in tools_raw.split(",") if t.strip()]

        return {
            "task":       task_m.group(1).strip()         if task_m   else "",
            "status":     status_m.group(1).strip()       if status_m else "unknown",
            "steps":      int(steps_m.group(1))           if steps_m  else 0,
            "tools":      tools,
            "agent_type": agent_type,
        }
    except Exception:
        return None


def _top_sequences(sequences: list[list[str]], n: int) -> list[dict]:
    counts = Counter(tuple(seq) for seq in sequences)
    return [
        {"sequence": list(seq), "count": cnt}
        for seq, cnt in counts.most_common(n)
    ]


def _generate_recommendations(
    parsed: list[dict],
    tool_success: dict,
    tool_fail: dict,
    tool_total: dict,
    feedbacks: list[dict],
) -> list[str]:
    recs = []

    # High success-rate tools
    for tool, sc in sorted(tool_success.items(), key=lambda x: -x[1]):
        total = tool_total.get(tool, 0)
        if total >= 3 and sc / total >= 0.9:
            recs.append(
                f"'{tool}' has {int(sc/total*100)}% success rate over {total} runs — "
                "include in standard workflows."
            )

    # High error-rate tools
    for tool, fc in sorted(tool_fail.items(), key=lambda x: -x[1]):
        total = tool_total.get(tool, 0)
        if total >= 2 and fc / total >= 0.5:
            recs.append(
                f"'{tool}' failed in {int(fc/total*100)}% of runs — "
                "add pre-checks or review parameters."
            )

    # Critical tools skipped in failed runs
    success_runs = [p for p in parsed if p["status"] == "completed"]
    failed_runs  = [p for p in parsed if p["status"] in ("failed", "escalated")]
    if success_runs and failed_runs:
        success_tools = {t for r in success_runs for t in r["tools"]}
        for tool in ["pre_upgrade_check", "pre_kafka_check", "checkpoint_save", "elastic_error_logs"]:
            if tool in success_tools:
                missing = sum(1 for r in failed_runs if tool not in r["tools"])
                if missing >= 2:
                    recs.append(
                        f"'{tool}' was absent in {missing}/{len(failed_runs)} failed runs "
                        "— skipping it correlates strongly with failure."
                    )

    # Many negative signals
    neg = [f for f in feedbacks if "negative" in f.get("concept", "")]
    if len(neg) >= 3:
        recs.append(
            f"{len(neg)} cancelled/escalated operations recorded — "
            "run a Status agent check before Action agent tasks."
        )

    return recs[:8] or ["Insufficient data — run more tasks to generate recommendations."]
