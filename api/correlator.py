"""
Log Correlation Engine — ties PostgreSQL operations with Elasticsearch logs.

correlate(operation_id) → CorrelationResult
  Fetches operation from DB, queries Elastic for same time window,
  matches errors to tool_call timestamps, returns structured analysis.

store_correlation(result) → None
  Stores correlation summary as MuninnDB engram.
  Links operation ↔ error events so future similar patterns are surfaced.
"""
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_ELASTIC_URL = lambda: os.environ.get("ELASTIC_URL", "").rstrip("/")
_INDEX = lambda: os.environ.get("ELASTIC_INDEX_PATTERN", "hp1-logs-*")
_WINDOW_S = lambda: int(os.environ.get("CORRELATION_WINDOW_SECONDS", "300"))


@dataclass
class ToolCallLog:
    tool: str
    timestamp: str
    status: str
    correlated_logs: list[dict] = field(default_factory=list)


@dataclass
class CorrelationResult:
    operation_id: str
    operation_label: str
    started_at: str
    completed_at: str
    status: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    all_logs: list[dict] = field(default_factory=list)
    error_summary: str = ""
    anomalies: list[str] = field(default_factory=list)
    engrams_activated: list[str] = field(default_factory=list)
    total_log_count: int = 0
    error_count: int = 0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _es_post(path: str, body: dict) -> dict:
    url = _ELASTIC_URL()
    if not url:
        return {}
    try:
        r = httpx.post(f"{url}{path}", json=body, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.debug("ES POST %s failed: %s", path, e)
        return {}


def _extract_hits(resp: dict) -> list[dict]:
    hits = resp.get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src = h.get("_source", {})
        results.append({
            "id": h.get("_id"),
            "timestamp": src.get("@timestamp"),
            "message": src.get("message", ""),
            "level": src.get("log", {}).get("level") or src.get("log.level", "info"),
            "hostname": src.get("host", {}).get("name", ""),
            "container": src.get("container", {}).get("name", ""),
            "service": (
                src.get("docker", {}).get("container", {}).get("labels", {})
                   .get("com.docker.swarm.service.name", "")
            ),
        })
    return results


async def _fetch_operation(operation_id: str) -> dict:
    """Fetch operation record from our own API."""
    from api.db.base import get_engine
    from api.db import queries as q
    try:
        async with get_engine().connect() as conn:
            return await q.get_operation(conn, operation_id)
    except Exception as e:
        log.debug("Failed to fetch operation %s: %s", operation_id, e)
        return {}


async def _fetch_tool_calls(operation_id: str) -> list[dict]:
    """Fetch tool calls for an operation."""
    from api.db.base import get_engine
    from api.db import queries as q
    try:
        async with get_engine().connect() as conn:
            return await q.get_tool_calls_for_operation(conn, operation_id)
    except Exception as e:
        log.debug("Failed to fetch tool calls for %s: %s", operation_id, e)
        return []


def _query_logs(since: str, until: str, size: int = 500) -> list[dict]:
    """Query Elasticsearch for logs in time window."""
    body = {
        "query": {"bool": {"must": [
            {"range": {"@timestamp": {"gte": since, "lte": until}}}
        ]}},
        "sort": [{"@timestamp": {"order": "asc"}}],
        "size": size,
        "_source": ["@timestamp", "message", "log.level", "host.name",
                    "container.name", "hp1_node_role",
                    "docker.container.labels.com.docker.swarm.service.name"],
    }
    resp = _es_post(f"/{_index()}/_search", body)
    return _extract_hits(resp), resp.get("hits", {}).get("total", {}).get("value", 0)


def _correlate_to_tool_calls(tool_calls: list[dict], all_logs: list[dict]) -> list[ToolCallLog]:
    """Match log entries to nearby tool call timestamps (within 30s window)."""
    results = []
    for tc in tool_calls:
        try:
            tc_ts = datetime.fromisoformat(tc["timestamp"].replace("Z", "+00:00"))
        except Exception:
            tc_ts = None

        corr_logs = []
        if tc_ts:
            for lg in all_logs:
                try:
                    lg_ts = datetime.fromisoformat(lg["timestamp"].replace("Z", "+00:00"))
                    delta = abs((lg_ts - tc_ts).total_seconds())
                    if delta <= 30:
                        corr_logs.append(lg)
                except Exception:
                    pass

        results.append(ToolCallLog(
            tool=tc.get("tool_name", ""),
            timestamp=tc.get("timestamp", ""),
            status=tc.get("status", ""),
            correlated_logs=corr_logs[:10],  # cap per tool call
        ))
    return results


async def _activate_memory(context: list[str]) -> list[str]:
    """Retrieve relevant memory engrams for context."""
    try:
        from api.memory.client import get_client
        client = get_client()
        activations = await client.activate(context, max_results=5)
        return [a.get("concept", "") for a in activations]
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def correlate(
    operation_id: str,
    window_seconds: Optional[int] = None,
) -> CorrelationResult:
    """
    Correlate a PostgreSQL operation with Elasticsearch logs.

    1. Fetch operation record (timestamps, label, status)
    2. Fetch tool_calls for the operation
    3. Query Elastic for logs in operation time window (+/- buffer)
    4. Match log lines to tool call timestamps
    5. Detect anomalies
    6. Activate memory context
    """
    window_s = window_seconds or _WINDOW_S()
    result = CorrelationResult(
        operation_id=operation_id,
        operation_label="",
        started_at="",
        completed_at="",
        status="",
    )

    # Fetch operation
    op = await _fetch_operation(operation_id)
    if not op:
        result.error_summary = f"Operation {operation_id} not found"
        return result

    result.operation_label = op.get("label", "")
    result.started_at = op.get("started_at", "")
    result.completed_at = op.get("completed_at") or datetime.now(timezone.utc).isoformat()
    result.status = op.get("status", "")

    # Fetch tool calls
    tool_calls_raw = await _fetch_tool_calls(operation_id)

    # Query Elasticsearch
    if not _ELASTIC_URL():
        result.error_summary = "Elasticsearch not configured"
        result.tool_calls = [
            ToolCallLog(tool=tc.get("tool_name", ""), timestamp=tc.get("timestamp", ""),
                        status=tc.get("status", ""))
            for tc in tool_calls_raw
        ]
        return result

    try:
        start_dt = datetime.fromisoformat(result.started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(result.completed_at.replace("Z", "+00:00"))
    except Exception:
        result.error_summary = "Cannot parse operation timestamps"
        return result

    since = (start_dt - timedelta(seconds=30)).isoformat()
    until = (end_dt + timedelta(seconds=window_s)).isoformat()

    all_logs, total = _query_logs(since, until)
    result.all_logs = all_logs
    result.total_log_count = total

    errors = [lg for lg in all_logs if lg.get("level", "").lower() in
              ("error", "critical", "fatal", "err")]
    result.error_count = len(errors)

    # Correlate logs to tool calls
    result.tool_calls = _correlate_to_tool_calls(tool_calls_raw, all_logs)

    # Anomaly detection
    if errors:
        services = list(set(e.get("service", "unknown") for e in errors if e.get("service")))
        result.anomalies = [f"Errors in: {', '.join(services[:5])}"] if services else [f"{len(errors)} errors detected"]
        result.error_summary = "; ".join(e["message"][:100] for e in errors[:3])

    # Memory context
    context = [result.operation_label, "infrastructure error", "upgrade failure"]
    result.engrams_activated = await _activate_memory(context)

    return result


async def store_correlation(result: CorrelationResult) -> None:
    """
    Store correlation summary as MuninnDB engram.
    High-confidence if anomalies detected.
    """
    try:
        from api.memory.client import get_client
        client = get_client()

        concept = f"correlation:{result.operation_id[:8]}"
        content = (
            f"Operation '{result.operation_label}' ({result.status}) "
            f"correlated with {result.total_log_count} log events, "
            f"{result.error_count} errors. "
            + (f"Anomalies: {'; '.join(result.anomalies)}. " if result.anomalies else "")
            + (f"Error summary: {result.error_summary}" if result.error_summary else "")
        )
        tags = ["correlation", result.status]
        if result.anomalies:
            tags.append("anomaly")

        await client.store(concept, content, tags)
        log.debug("Stored correlation engram: %s", concept)
    except Exception as e:
        log.debug("Failed to store correlation: %s", e)
