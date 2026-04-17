# CC PROMPT — v2.33.0 — kafka_topic_inspect MCP tool

## What this does
Adds a single read-only MCP tool `kafka_topic_inspect(topic: str | None = None)` that
returns structured broker/topic/partition/ISR data in one call, so the investigate
agent can reason about replication without chaining 4-5 `kafka_exec` calls.

Version bump: 2.32.6 → 2.33.0

## Change 1 — mcp_server/tools/kafka_inspect.py — new file

Create a new tool module. Use `kafka-python` (already in requirements) — if not,
fall back to `confluent-kafka` or add `kafka-python>=2.0` to `requirements.txt`.

```python
"""
kafka_topic_inspect — read-only structured view of Kafka cluster state.

Returns:
  {
    "brokers": [{"id": int, "host": str, "port": int, "rack": str|None}],
    "topics":  [{
      "name": str,
      "partitions": [{
        "id": int, "leader": int, "replicas": [int], "isr": [int],
        "under_replicated": bool
      }],
    }],
    "summary": {
      "broker_count": int, "topic_count": int,
      "total_partitions": int, "under_replicated_partitions": int
    }
  }

Size caps: first 50 topics / first 200 partitions per call. `topic` param
filters to a single topic (no cap in that case).
"""
from typing import Optional
from api.connections import get_connection_for_platform
from api.decrypt import decrypt  # or wherever Fernet helper lives
from kafka import KafkaAdminClient
from kafka.admin import ConfigResource, ConfigResourceType

def kafka_topic_inspect(topic: Optional[str] = None) -> dict:
    conn = get_connection_for_platform("kafka")
    if not conn:
        return {"error": "no kafka connection configured"}
    bootstrap = f"{conn['host']}:{conn['port']}"
    admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=10000)
    try:
        cluster = admin.describe_cluster()
        brokers = [
            {"id": b.nodeId, "host": b.host, "port": b.port, "rack": b.rack}
            for b in cluster.get("brokers", [])
        ]
        topic_names = [topic] if topic else list(admin.list_topics())[:50]
        descs = admin.describe_topics(topic_names)
        topics_out, total_p, unreplicated = [], 0, 0
        for d in descs:
            parts = []
            for p in d["partitions"]:
                ur = sorted(p["isr"]) != sorted(p["replicas"])
                parts.append({
                    "id": p["partition"],
                    "leader": p["leader"],
                    "replicas": p["replicas"],
                    "isr": p["isr"],
                    "under_replicated": ur,
                })
                total_p += 1
                if ur: unreplicated += 1
            topics_out.append({"name": d["topic"], "partitions": parts[:200]})
        return {
            "brokers": brokers,
            "topics": topics_out,
            "summary": {
                "broker_count": len(brokers),
                "topic_count": len(topics_out),
                "total_partitions": total_p,
                "under_replicated_partitions": unreplicated,
            },
        }
    finally:
        admin.close()
```

## Change 2 — mcp_server/tools/__init__.py — register

Add the tool to the exported registry where other kafka tools register:

```python
from .kafka_inspect import kafka_topic_inspect
# ... in TOOLS dict / @mcp.tool() registration, add:
mcp.tool()(kafka_topic_inspect)
```

Follow the same registration pattern as `kafka_broker_status` / `kafka_consumer_lag`
in `mcp_server/tools/kafka.py` (or wherever those are already registered).

## Change 3 — api/agents/router.py — allowlists + triage prompt

Add `kafka_topic_inspect` to both `OBSERVE_AGENT_TOOLS` and `INVESTIGATE_AGENT_TOOLS`
frozensets. Do NOT add to `EXECUTE_AGENT_TOOLS` — it's read-only and execute agents
shouldn't be distracted.

In the investigation prompt (RESEARCH_PROMPT or KAFKA section), prepend to the
Kafka triage guidance:

```
═══ KAFKA TRIAGE ORDER ═══
1. kafka_topic_inspect (no args, or topic=X for focused) — FIRST call for any
   kafka issue. Returns structured broker/partition/ISR state in one call.
2. kafka_consumer_lag — ONLY after step 1, if lag is suspected.
3. service_placement(kafka_broker-N) — map broker id to Swarm node.
4. kafka_exec — last resort for deep-dives beyond what the above provide.
```

## Change 4 — requirements.txt

Ensure `kafka-python>=2.0.2` is listed. If it already is (we have collectors),
do nothing.

## Version bump
Update `VERSION` file: 2.32.6 → 2.33.0

## Commit
```
git add -A
git commit -m "feat(tools): v2.33.0 kafka_topic_inspect — structured cluster state in one call"
git push origin main
```

## How to test after push
1. Redeploy:
   `docker compose -f /opt/hp1-agent/docker/docker-compose.yml --env-file /opt/hp1-agent/docker/.env up -d hp1_agent`
2. In the agent panel, run observe: "kafka hp1-logs state" — expect 1-2 tool calls.
3. Check the tool manifest call — `kafka_topic_inspect` should appear first in
   the investigate agent's preferred order for any kafka prompt.
