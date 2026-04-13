"""
KafkaCollector — polls Kafka every KAFKA_POLL_INTERVAL seconds.

Collects: broker list, controller id, topics with partition/replication info,
under-replicated partition count, consumer group lag.

Health:
  healthy  — all brokers up, no under-replicated partitions, lag < threshold
  degraded — 1 broker down OR under-replicated partitions exist OR high lag
  critical — majority brokers down
  error    — cannot reach any broker
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector
from api.constants import DEFAULT_KAFKA_BOOTSTRAP, DEFAULT_KAFKA_LAG_THRESHOLD

log = logging.getLogger(__name__)


class KafkaCollector(BaseCollector):
    component = "kafka_cluster"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("KAFKA_POLL_INTERVAL", "30"))
        self.lag_threshold = int(os.environ.get("KAFKA_LAG_THRESHOLD", str(DEFAULT_KAFKA_LAG_THRESHOLD)))

    async def poll(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_sync)

    def _collect_sync(self) -> dict:
        from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition
        from kafka.errors import NoBrokersAvailable

        bootstrap = [
            s.strip()
            for s in os.environ.get("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_KAFKA_BOOTSTRAP).split(",")
            if s.strip()
        ]
        expected = len(bootstrap)

        try:
            admin = KafkaAdminClient(
                bootstrap_servers=bootstrap,
                request_timeout_ms=8000,
                connections_max_idle_ms=10000,
            )
        except NoBrokersAvailable:
            return {
                "health": "error",
                "error": "No brokers available",
                "message": "Cannot reach Kafka bootstrap servers",
                "brokers": [], "topics": [], "consumer_lag": {},
                "broker_count": 0, "expected_brokers": expected,
                "under_replicated_partitions": 0,
            }
        except Exception as e:
            return {
                "health": "error",
                "error": str(e),
                "message": f"Kafka connection error: {e}",
                "brokers": [], "topics": [], "consumer_lag": {},
                "broker_count": 0, "expected_brokers": expected,
                "under_replicated_partitions": 0,
            }

        try:
            # ── Brokers ────────────────────────────────────────────────────────
            metadata = admin.describe_cluster()
            brokers_raw = metadata.get("brokers", [])
            controller = metadata.get("controller", {})
            # KRaft clusters return controller differently from ZK-based clusters.
            # Try multiple known field paths before falling back to -1.
            controller_id = (
                controller.get("node_id")
                or controller.get("id")
                or metadata.get("controller_id")
                or -1
            )
            # If controller_id is -1 but we have brokers, this is a KRaft detection gap
            # in kafka-python — not a real missing controller. Mark as unknown, not -1.
            if controller_id == -1 and len(brokers_raw) > 0:
                controller_id = None

            broker_data = []
            for b in brokers_raw:
                bid = b.get("node_id", b.get("id", -1))
                broker_data.append({
                    "id": bid,
                    "host": b.get("host", "unknown"),
                    "port": b.get("port", 0),
                    "is_controller": controller_id is not None and bid == controller_id,
                    "status": "up",
                })

            # ── Topics ─────────────────────────────────────────────────────────
            all_topics = admin.list_topics()
            user_topics = [t for t in all_topics if not t.startswith("__")]

            under_replicated_total = 0
            topic_data = []
            for topic in user_topics[:50]:  # cap at 50 to avoid timeout
                try:
                    desc = admin.describe_topics([topic])
                    if not desc:
                        continue
                    topic_meta = desc[0] if isinstance(desc, list) else {}
                    partitions = topic_meta.get("partitions", [])
                    under_rep_partitions = []
                    for p in partitions:
                        isr_count = len(p.get("isr", []))
                        replica_count = len(p.get("replicas", []))
                        if isr_count < replica_count:
                            under_rep_partitions.append({
                                "partition": p.get("partition", p.get("id", -1)),
                                "leader": p.get("leader", {}).get("node_id", -1) if isinstance(p.get("leader"), dict) else p.get("leader", -1),
                                "replicas": [r.get("node_id", r) if isinstance(r, dict) else r for r in p.get("replicas", [])],
                                "isr": [r.get("node_id", r) if isinstance(r, dict) else r for r in p.get("isr", [])],
                                "missing": replica_count - isr_count,
                            })
                    under_rep = len(under_rep_partitions)
                    under_replicated_total += under_rep
                    rf = len(partitions[0].get("replicas", [])) if partitions else 0
                    topic_data.append({
                        "name": topic,
                        "partition_count": len(partitions),
                        "replication_factor": rf,
                        "under_replicated": under_rep,
                        "under_replicated_partitions": under_rep_partitions,
                    })
                except Exception:
                    pass

            # ── Consumer group lag ─────────────────────────────────────────────
            group_lag: dict = {}
            try:
                groups = admin.list_consumer_groups()
                consumer = KafkaConsumer(
                    bootstrap_servers=bootstrap,
                    request_timeout_ms=5000,
                )
                for group_info in groups[:20]:
                    gid = (
                        group_info[0]
                        if isinstance(group_info, tuple)
                        else group_info.get("group_id", "")
                    )
                    if not gid or gid.startswith("_"):
                        continue
                    try:
                        offsets = admin.list_consumer_group_offsets(gid)
                        lag_entries = []
                        total_lag = 0
                        for tp, committed in offsets.items():
                            ends = consumer.end_offsets(
                                [TopicPartition(tp.topic, tp.partition)]
                            )
                            end = ends.get(TopicPartition(tp.topic, tp.partition), 0)
                            committed_val = committed.offset if committed else 0
                            lag = max(0, end - committed_val)
                            total_lag += lag
                            lag_entries.append({
                                "topic": tp.topic,
                                "partition": tp.partition,
                                "lag": lag,
                            })
                        group_lag[gid] = {
                            "total_lag": total_lag,
                            "partitions": lag_entries,
                        }
                    except Exception:
                        pass
                consumer.close()
            except Exception as e:
                log.debug("KafkaCollector: could not fetch consumer groups: %s", e)

            admin.close()

            # ── Health ─────────────────────────────────────────────────────────
            under_rep_threshold = int(os.environ.get("KAFKA_UNDER_REPLICATED_THRESHOLD", "0"))
            alive = len(broker_data)
            if alive == 0:
                health = "critical"
                message = "No brokers visible"
            elif alive < (expected + 1) // 2:  # less than majority
                health = "critical"
                message = f"Majority brokers down: {alive}/{expected}"
            elif alive < expected:
                health = "degraded"
                message = f"{alive}/{expected} brokers up"
            elif under_replicated_total > under_rep_threshold:
                health = "degraded"
                message = (
                    f"{alive}/{expected} brokers up, "
                    f"{under_replicated_total} under-replicated partitions"
                    + (f" (threshold: {under_rep_threshold})" if under_rep_threshold > 0 else "")
                )
            else:
                max_lag = max(
                    (v["total_lag"] for v in group_lag.values()), default=0
                )
                if max_lag > self.lag_threshold:
                    health = "degraded"
                    message = f"High consumer lag: {max_lag} (threshold: {self.lag_threshold})"
                else:
                    health = "healthy"
                    message = (
                        f"{alive} brokers healthy, {len(user_topics)} topics"
                        + (f", max lag {max_lag}" if max_lag else "")
                    )

            # ── Metric samples (time-series) ──────────────────────────────────
            try:
                from api.db.metric_samples import write_samples
                kafka_metrics: dict = {
                    "brokers.alive": float(alive),
                    "brokers.expected": float(expected),
                    "partitions.under_replicated": float(under_replicated_total),
                }
                # Total consumer lag across all groups
                total_lag = sum(v.get("total_lag", 0) for v in group_lag.values())
                kafka_metrics["consumer.lag.total"] = float(total_lag)
                write_samples("kafka_cluster", kafka_metrics)
            except Exception as _me:
                log.debug("kafka metric_samples write failed: %s", _me)

            return {
                "health": health,
                "message": message,
                "brokers": broker_data,
                "controller_id": controller_id,
                "controller_detected": controller_id is not None and controller_id != -1,
                "broker_count": alive,
                "expected_brokers": expected,
                "topics": topic_data,
                "topic_count": len(user_topics),
                "under_replicated_partitions": under_replicated_total,
                "consumer_lag": group_lag,
            }

        except Exception as e:
            try:
                admin.close()
            except Exception:
                pass
            log.warning("KafkaCollector._collect_sync error: %s", e)
            return {
                "health": "error",
                "error": str(e),
                "message": f"Kafka collection error: {e}",
                "brokers": [], "topics": [], "consumer_lag": {},
                "broker_count": 0, "expected_brokers": expected,
                "under_replicated_partitions": 0,
            }
