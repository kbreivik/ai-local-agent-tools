"""
Local docs RAG ingest — writes operational runbooks into MuninnDB on startup.

Runbooks cover: Docker Swarm, Kafka, Elasticsearch, Filebeat.
Only stores engrams that don't already exist (concept dedup via search).
Run once on startup; idempotent.
"""
import logging

from api.memory.client import get_client
from api.memory.schemas import doc_engram

log = logging.getLogger(__name__)

# ── Runbook content ───────────────────────────────────────────────────────────

RUNBOOKS: list[tuple[str, str, str, str]] = [
    # (topic, subtopic, source, content)
    (
        "docker_swarm",
        "node_failure",
        "runbook",
        "Docker Swarm node failure recovery: "
        "1. Check node state: 'docker node ls'. "
        "2. If node is 'down', SSH to it and restart Docker: 'systemctl restart docker'. "
        "3. If unrecoverable, drain it: 'docker node update --availability drain <node>'. "
        "4. Remove from swarm: 'docker node rm <node>'. "
        "5. Re-join: run 'docker swarm join --token <token> <manager-ip>:2377' on the node. "
        "Quorum note: with 3 managers, 1 failure is tolerated. With 2 remaining, no scheduling changes until recovered.",
    ),
    (
        "docker_swarm",
        "service_degraded",
        "runbook",
        "Docker Swarm service not at desired replicas: "
        "1. Inspect service: 'docker service ps <service> --no-trunc'. "
        "2. Check failure reason in the STATUS column. "
        "3. View logs: 'docker service logs <service> --tail 50'. "
        "4. Force redeploy: 'docker service update --force <service>'. "
        "5. If node constraint mismatch, adjust placement or drain conflicting node. "
        "6. Scale up: 'docker service scale <service>=N'. "
        "Common causes: OOM kill, image pull failure, port conflict, volume mount error.",
    ),
    (
        "kafka",
        "consumer_lag",
        "runbook",
        "Kafka consumer lag remediation: "
        "1. Identify lagging group: 'kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group <group>'. "
        "2. Check consumer instances are running and healthy. "
        "3. If consumers are slow: profile the processing logic, check GC pauses, network latency. "
        "4. Scale consumers (up to partition count for the topic). "
        "5. If producer is spiking: check upstream data rate, consider backpressure. "
        "6. Emergency: reset offset forward to skip stuck messages: "
        "'kafka-consumer-groups.sh --reset-offsets --to-latest --group <group> --topic <topic> --execute'.",
    ),
    (
        "kafka",
        "broker_down",
        "runbook",
        "Kafka broker down recovery: "
        "1. Check broker logs in the Swarm service: 'docker service logs kafka-stack_kafka1'. "
        "2. Verify ZooKeeper/KRaft controller is healthy. "
        "3. Restart broker service: 'docker service update --force kafka-stack_kafka1'. "
        "4. Watch ISR recovery: 'kafka-topics.sh --describe --under-replicated-partitions'. "
        "5. Under-replicated partitions recover automatically once broker rejoins. "
        "6. If persistent: check disk space (df -h), Java heap (default 1GB), network ports (9092-9094). "
        "Controller failover is automatic in KRaft mode.",
    ),
    (
        "kafka",
        "under_replicated_partitions",
        "runbook",
        "Kafka under-replicated partitions (URP): "
        "1. List URPs: 'kafka-topics.sh --bootstrap-server localhost:9092 --describe --under-replicated-partitions'. "
        "2. Identify which broker is lagging (ISR shrinkage). "
        "3. Check that broker: disk I/O, network, memory, Java GC. "
        "4. If broker is behind: wait for catch-up (may take minutes for large topics). "
        "5. If persistent: check log.retention.bytes, increase replica.fetch.max.bytes. "
        "6. Manual leader reassign if broker is permanently degraded.",
    ),
    (
        "elasticsearch",
        "cluster_red",
        "runbook",
        "Elasticsearch cluster RED status recovery: "
        "1. Check cluster health: GET /_cluster/health?pretty. "
        "2. Find unassigned shards: GET /_cat/shards?v&h=index,shard,prirep,state,node. "
        "3. Check allocation explain: GET /_cluster/allocation/explain?pretty. "
        "4. Common causes: node left cluster (check ES logs), disk full (>85% watermark). "
        "5. Fix disk: delete old indices, increase watermark: "
        "PUT /_cluster/settings {\"transient\":{\"cluster.routing.allocation.disk.watermark.high\":\"95%\"}}. "
        "6. Force shard reroute: POST /_cluster/reroute?retry_failed=true. "
        "7. As last resort: delete problematic index if data is in Kafka (re-ingest from source).",
    ),
    (
        "filebeat",
        "not_ingesting",
        "runbook",
        "Filebeat not ingesting logs to Elasticsearch: "
        "1. Check Filebeat service logs: 'docker service logs filebeat-stack_filebeat'. "
        "2. Verify Elasticsearch output config: host, port, credentials. "
        "3. Check Elasticsearch is accepting writes (not read-only due to disk). "
        "4. Verify index template exists: GET /_index_template/filebeat-*. "
        "5. Restart Filebeat: 'docker service update --force filebeat-stack_filebeat'. "
        "6. Check Filebeat registry file — if corrupt, delete and restart to re-ingest. "
        "7. Confirm log paths in filebeat.yml match actual file locations on host.",
    ),
    (
        "hp1_agent",
        "architecture",
        "internal",
        "HP1 AI Agent architecture overview: "
        "FastAPI backend (port 8000) with SQLite/Postgres persistence. "
        "Background collectors poll Docker Swarm (port 2377 socket), Kafka (9092-9094), Elasticsearch every 30-60s. "
        "Snapshots stored in status_snapshots table. Alerts fired on health transitions. "
        "MuninnDB cognitive memory on port 9475 (socat proxy). "
        "GUI: Vite + React 18 + Tailwind, port 5173 in dev. "
        "WebSocket /ws/output streams agent output. "
        "Agent loop: LM Studio (Qwen3-Coder-30B) via OpenAI-compatible API on port 1234. "
        "Elasticsearch log access via /api/elastic/* — search, errors, pattern, correlate.",
    ),
    (
        "kafka",
        "rolling_restart",
        "runbook",
        "Kafka rolling restart procedure: "
        "1. Check elastic_kafka_logs() for ISR warnings — must be zero before proceeding. "
        "2. Run elastic_error_logs(service='kafka') — must be zero errors. "
        "3. Verify all topics fully replicated: under_replicated_partitions=0. "
        "4. checkpoint_save('pre_kafka_restart'). "
        "5. Restart one broker at a time: docker service update --force kafka-stack_kafka1. "
        "6. Wait for broker to rejoin: watch ISR recovery in elastic_kafka_logs(). "
        "7. Confirm under_replicated_partitions=0 before next broker restart. "
        "8. post_upgrade_verify('kafka') after all brokers restarted.",
    ),
    (
        "docker_swarm",
        "service_upgrade_rollback",
        "runbook",
        "Service upgrade and rollback procedure: "
        "PRE: pre_upgrade_check(service) — all 6 steps must pass (swarm, kafka, elastic errors, log pattern, memory, checkpoint). "
        "UPGRADE: docker service update --image <new-image> <service>. "
        "POST: post_upgrade_verify(service, operation_id) — replica count + no new errors + log correlation. "
        "ROLLBACK if post_upgrade_verify fails: "
        "docker service rollback <service> (uses built-in rollback to previous image). "
        "Then: audit_log('rollback', reason) + escalate(). "
        "Memory: upgrade results stored as engrams — future upgrades surface past failures.",
    ),
    (
        "elasticsearch",
        "reindex",
        "runbook",
        "Elasticsearch reindex procedure: "
        "1. Check source index: GET /<source>/_count. "
        "2. Create destination index with correct mapping. "
        "3. Start reindex: POST /_reindex {source: {index: <src>}, dest: {index: <dst>}}. "
        "4. Monitor: GET /_tasks?actions=*reindex — check completed/total. "
        "5. Verify doc count matches: GET /<dst>/_count. "
        "6. Switch aliases: POST /_aliases with remove old + add new. "
        "7. Delete old index after alias switch confirmed. "
        "Note: Reindex does NOT copy index settings/mappings — create destination first.",
    ),
    (
        "filebeat",
        "troubleshoot",
        "runbook",
        "Filebeat troubleshooting: "
        "STALE (no new docs > 10min): "
        "1. Check Filebeat container: docker ps | grep filebeat. "
        "2. View logs: docker logs filebeat --tail 50. "
        "3. Verify Elasticsearch connectivity: curl -sf $ELASTIC_URL/_cluster/health. "
        "4. Restart: docker service update --force filebeat-stack_filebeat. "
        "MISSING LOGS: "
        "1. Verify Docker socket mount: docker exec filebeat ls /var/run/docker.sock. "
        "2. Check index pattern: GET hp1-logs-*/_count. "
        "3. Verify filebeat.yml inputs include correct log paths. "
        "HIGH LAG / SLOW INGEST: "
        "1. Check Elasticsearch disk space: GET /_cat/allocation?v. "
        "2. Check shard count: many shards = slow. "
        "3. Increase bulk_max_size in filebeat.yml. "
        "4. Check refresh_interval — increase to 30s if write throughput is priority.",
    ),
]


async def ingest_runbooks() -> int:
    """
    Store all runbooks as engrams. Checks for existing engrams by concept first.
    Returns count of newly stored engrams.
    """
    client = get_client()
    stored = 0

    for topic, subtopic, source, content in RUNBOOKS:
        try:
            concept, full_content, tags = doc_engram(topic, content, source, subtopic)

            # Check if exact concept already stored (avoid duplicates on restart)
            existing = await client.search(concept, limit=5)
            if any(e.get("concept") == concept for e in existing):
                continue

            eid = await client.store(concept, full_content, tags)
            if eid:
                stored += 1
                log.debug("Ingested runbook: %s", concept)
        except Exception as e:
            log.warning("Runbook ingest failed (%s/%s): %s", topic, subtopic, e)

    log.info("Memory ingest complete: %d new runbook engrams stored", stored)
    return stored
