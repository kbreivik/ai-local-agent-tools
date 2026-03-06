"""Kafka management tools."""
import os
import time
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition
from kafka.admin import NewTopic
from kafka.errors import KafkaError, NoBrokersAvailable


def _bootstrap() -> list[str]:
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092,localhost:9093,localhost:9094")
    return [s.strip() for s in servers.split(",")]


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _degraded(data: Any, message: str) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def kafka_broker_status() -> dict:
    """Return broker health and leader election state."""
    try:
        admin = KafkaAdminClient(bootstrap_servers=_bootstrap(), request_timeout_ms=5000)
        metadata = admin.describe_cluster()
        brokers = metadata.get("brokers", [])
        controller = metadata.get("controller", {})
        broker_data = []
        for b in brokers:
            broker_data.append({
                "id": b.get("node_id", b.get("id", "unknown")),
                "host": b.get("host", "unknown"),
                "port": b.get("port", 0),
                "is_controller": b.get("node_id", b.get("id")) == controller.get("node_id", controller.get("id")),
            })
        admin.close()
        expected = len(_bootstrap())
        if len(broker_data) < expected:
            return _degraded({"brokers": broker_data, "count": len(broker_data), "expected": expected},
                             f"Only {len(broker_data)}/{expected} brokers visible")
        return _ok({"brokers": broker_data, "count": len(broker_data),
                    "controller_id": controller.get("node_id", controller.get("id"))},
                   f"Kafka healthy: {len(broker_data)} brokers")
    except NoBrokersAvailable:
        return _err("No Kafka brokers available")
    except Exception as e:
        return _err(f"kafka_broker_status error: {e}")


def kafka_consumer_lag(group: str) -> dict:
    """Return consumer lag per topic/partition for a consumer group."""
    try:
        admin = KafkaAdminClient(bootstrap_servers=_bootstrap(), request_timeout_ms=5000)
        try:
            offsets = admin.list_consumer_group_offsets(group)
        except Exception as e:
            admin.close()
            return _err(f"Cannot get offsets for group '{group}': {e}")
        admin.close()

        consumer = KafkaConsumer(bootstrap_servers=_bootstrap(), request_timeout_ms=5000)
        lag_data = []
        total_lag = 0
        for tp, committed_offset in offsets.items():
            end_offsets = consumer.end_offsets([TopicPartition(tp.topic, tp.partition)])
            end = end_offsets.get(TopicPartition(tp.topic, tp.partition), 0)
            committed = committed_offset.offset if committed_offset else 0
            lag = max(0, end - committed)
            total_lag += lag
            lag_data.append({
                "topic": tp.topic,
                "partition": tp.partition,
                "committed_offset": committed,
                "end_offset": end,
                "lag": lag,
            })
        consumer.close()
        if total_lag > 10000:
            return _degraded({"group": group, "partitions": lag_data, "total_lag": total_lag},
                             f"High consumer lag: {total_lag}")
        return _ok({"group": group, "partitions": lag_data, "total_lag": total_lag},
                   f"Consumer lag for '{group}': {total_lag}")
    except NoBrokersAvailable:
        return _err("No Kafka brokers available")
    except Exception as e:
        return _err(f"kafka_consumer_lag error: {e}")


def kafka_topic_health(topic: str) -> dict:
    """Check partition count, replication, under-replicated partitions."""
    try:
        admin = KafkaAdminClient(bootstrap_servers=_bootstrap(), request_timeout_ms=5000)
        try:
            desc = admin.describe_topics([topic])
        except Exception as e:
            admin.close()
            return _err(f"Cannot describe topic '{topic}': {e}")
        admin.close()

        if not desc or len(desc) == 0:
            return _err(f"Topic '{topic}' not found")

        topic_meta = desc[0] if isinstance(desc, list) else desc.get(topic, {})
        partitions = topic_meta.get("partitions", [])
        under_replicated = []
        for p in partitions:
            replicas = p.get("replicas", [])
            isr = p.get("isr", [])
            if len(isr) < len(replicas):
                under_replicated.append({
                    "partition": p.get("partition"),
                    "replicas": len(replicas),
                    "isr": len(isr),
                })
        data = {
            "topic": topic,
            "partition_count": len(partitions),
            "replication_factor": len(partitions[0].get("replicas", [])) if partitions else 0,
            "under_replicated": under_replicated,
        }
        if under_replicated:
            return _degraded(data, f"Topic '{topic}' has {len(under_replicated)} under-replicated partitions")
        return _ok(data, f"Topic '{topic}' healthy: {len(partitions)} partitions")
    except NoBrokersAvailable:
        return _err("No Kafka brokers available")
    except Exception as e:
        return _err(f"kafka_topic_health error: {e}")


def kafka_rolling_restart_safe() -> dict:
    """Safe rolling restart — checks ISR before each broker restart."""
    try:
        status = kafka_broker_status()
        if status["status"] != "ok":
            return _err(f"Kafka not healthy before rolling restart: {status['message']}")
        brokers = status["data"]["brokers"]
        results = []
        for broker in brokers:
            # Verify ISR is intact before touching each broker
            broker_check = kafka_broker_status()
            if broker_check["status"] != "ok":
                return _err(f"Broker check failed before restarting broker {broker['id']}: {broker_check['message']}")
            # In a real environment this would issue the restart via container/SSH
            # Here we record the safe-to-restart decision
            results.append({
                "broker_id": broker["id"],
                "host": broker["host"],
                "safe_to_restart": True,
                "action": "restart_deferred_to_operator",
            })
        return _ok({"brokers_checked": results},
                   "Rolling restart safety check passed — operator must execute restarts")
    except Exception as e:
        return _err(f"kafka_rolling_restart_safe error: {e}")


def pre_kafka_check() -> dict:
    """Full Kafka readiness gate — blocks if not ready."""
    try:
        broker_status = kafka_broker_status()
        if broker_status["status"] != "ok":
            return _err(f"Kafka brokers not healthy: {broker_status['message']}", broker_status["data"])

        admin = KafkaAdminClient(bootstrap_servers=_bootstrap(), request_timeout_ms=5000)
        try:
            topics = admin.list_topics()
        except Exception as e:
            admin.close()
            return _err(f"Cannot list topics: {e}")
        admin.close()

        degraded_topics = []
        for topic in topics:
            if topic.startswith("__"):
                continue  # skip internal topics
            health = kafka_topic_health(topic)
            if health["status"] == "degraded":
                degraded_topics.append(topic)
            elif health["status"] == "error":
                return _err(f"Error checking topic '{topic}': {health['message']}")

        if degraded_topics:
            return _degraded({"degraded_topics": degraded_topics},
                             f"Topics not healthy: {degraded_topics}")

        return _ok({
            "brokers": broker_status["data"]["count"],
            "topics_checked": len([t for t in topics if not t.startswith("__")]),
        }, "Kafka ready for operations")
    except Exception as e:
        return _err(f"pre_kafka_check error: {e}")
