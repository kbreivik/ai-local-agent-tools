"""
kafka_topic_inspect — read-only structured view of Kafka cluster state.

Returns broker/topic/partition/ISR data in one call so the investigate agent
can reason about replication without chaining multiple kafka_exec calls.

Data shape (inside `data`):
  {
    "brokers": [{"id": int, "host": str, "port": int, "rack": str|None,
                 "is_controller": bool}],
    "topics":  [{
      "name": str,
      "partitions": [{
        "id": int, "leader": int, "replicas": [int], "isr": [int],
        "under_replicated": bool
      }],
    }],
    "summary": {
      "broker_count": int, "topic_count": int,
      "total_partitions": int, "under_replicated_partitions": int,
      "controller_id": int|None
    }
  }

Size caps: first 50 topics / first 200 partitions per topic when called without
a `topic` filter. Internal topics (__consumer_offsets, __transaction_state)
are skipped in the default listing.
"""
import os
from datetime import datetime, timezone
from typing import Any, Optional

from kafka import KafkaAdminClient
from kafka.errors import NoBrokersAvailable

from api.constants import DEFAULT_KAFKA_BOOTSTRAP


_TOPIC_CAP = 50
_PARTITION_CAP = 200


def _bootstrap() -> list[str]:
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_KAFKA_BOOTSTRAP)
    return [s.strip() for s in servers.split(",")]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _degraded(data: Any, message: str) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def kafka_topic_inspect(topic: Optional[str] = None) -> dict:
    """Return structured broker/topic/partition/ISR state in one call.

    topic: when provided, only describe that single topic (no cap).
           when omitted, list up to first 50 non-internal topics.
    """
    try:
        admin = KafkaAdminClient(
            bootstrap_servers=_bootstrap(),
            client_id="hp1-agent-topic-inspect",
            request_timeout_ms=10000,
        )
    except NoBrokersAvailable:
        return _err("No Kafka brokers available")
    except Exception as e:
        return _err(f"kafka_topic_inspect connect error: {e}")

    try:
        cluster = admin.describe_cluster()
        raw_brokers = cluster.get("brokers", [])
        controller = cluster.get("controller", {}) or {}
        controller_id = controller.get("node_id", controller.get("id"))

        brokers = []
        for b in raw_brokers:
            bid = b.get("node_id", b.get("id"))
            brokers.append({
                "id": bid,
                "host": b.get("host", "unknown"),
                "port": b.get("port", 0),
                "rack": b.get("rack"),
                "is_controller": bid == controller_id,
            })

        if topic:
            topic_names = [topic]
        else:
            all_topics = [t for t in admin.list_topics() if not t.startswith("__")]
            topic_names = sorted(all_topics)[:_TOPIC_CAP]

        descs = admin.describe_topics(topic_names) if topic_names else []

        topics_out: list[dict] = []
        total_partitions = 0
        under_replicated = 0

        for d in descs:
            # kafka-python returns dicts with "topic" key; partitions list with
            # "partition", "leader", "replicas", "isr" keys.
            tname = d.get("topic") or d.get("name") or ""
            parts_raw = d.get("partitions", [])
            parts_out = []
            cap = None if topic else _PARTITION_CAP
            for p in parts_raw:
                replicas = list(p.get("replicas", []))
                isr = list(p.get("isr", []))
                ur = sorted(isr) != sorted(replicas)
                pid = p.get("partition", p.get("partition_id", 0))
                parts_out.append({
                    "id": pid,
                    "leader": p.get("leader"),
                    "replicas": replicas,
                    "isr": isr,
                    "under_replicated": ur,
                })
                total_partitions += 1
                if ur:
                    under_replicated += 1
            if cap is not None:
                parts_out = parts_out[:cap]
            topics_out.append({"name": tname, "partitions": parts_out})

        data = {
            "brokers": brokers,
            "topics": topics_out,
            "summary": {
                "broker_count": len(brokers),
                "topic_count": len(topics_out),
                "total_partitions": total_partitions,
                "under_replicated_partitions": under_replicated,
                "controller_id": controller_id,
            },
        }

        if under_replicated > 0:
            return _degraded(
                data,
                f"{under_replicated} under-replicated partition(s) across "
                f"{len(topics_out)} topic(s)",
            )
        if controller_id is None:
            return _degraded(data, "No controller elected — cluster not healthy")

        return _ok(
            data,
            f"{len(brokers)} broker(s), {len(topics_out)} topic(s), "
            f"{total_partitions} partition(s), all in-sync",
        )
    except Exception as e:
        return _err(f"kafka_topic_inspect error: {e}")
    finally:
        try:
            admin.close()
        except Exception:
            pass
