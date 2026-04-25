"""
ElasticCollector — polls Elasticsearch every ELASTIC_POLL_INTERVAL seconds.

If ELASTIC_URL is not set → returns health="unconfigured" immediately (not an error).
Uses httpx async HTTP for non-blocking calls.

Health maps from ES cluster status:
  green  → healthy
  yellow → degraded
  red    → critical
  error  → cannot reach ES
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class ElasticCollector(BaseCollector):
    component = "elasticsearch"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("ELASTIC_POLL_INTERVAL", "60"))
        self.url = os.environ.get("ELASTIC_URL", "").rstrip("/")
        self.filebeat_pattern = os.environ.get("FILEBEAT_INDEX_PATTERN", "filebeat-*")

    async def poll(self) -> dict:
        if not self.url:
            return {
                "health": "unconfigured",
                "message": "ELASTIC_URL not set — Elasticsearch monitoring disabled",
                "cluster_health": None,
                "nodes": 0,
                "shards": {},
                "filebeat": {"status": "unconfigured"},
            }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Cluster health
                r = await client.get(f"{self.url}/_cluster/health")
                r.raise_for_status()
                health_data = r.json()

                cluster_status = health_data.get("status", "red")  # green/yellow/red

                # Filebeat index check
                filebeat_status = "inactive"
                try:
                    r2 = await client.get(
                        f"{self.url}/{self.filebeat_pattern}/_stats/docs",
                        timeout=5.0,
                    )
                    if r2.status_code == 200:
                        fb = r2.json()
                        doc_count = (
                            fb.get("_all", {})
                            .get("primaries", {})
                            .get("docs", {})
                            .get("count", 0)
                        )
                        filebeat_status = "active" if doc_count >= 0 else "inactive"
                except Exception:
                    pass

                # Map ES status to our health vocabulary
                health_map = {"green": "healthy", "yellow": "degraded", "red": "critical"}
                health = health_map.get(cluster_status, "error")

                # Single-node mode: yellow is expected (replicas can't be placed on same node)
                # Suppress degraded → healthy when configured as single-node
                if health == "degraded" and cluster_status == "yellow":
                    try:
                        from api.settings_manager import get_setting
                        single_node_val = get_setting("elasticsearchSingleNode").get("value", "false")
                        single_node = str(single_node_val).lower() in ("true", "1", "yes")
                        data_nodes = health_data.get("number_of_data_nodes", 0)
                        if single_node or data_nodes == 1:
                            health = "healthy"
                            cluster_status = "yellow_single_node"  # preserve for display
                    except Exception:
                        pass

            # Run log-based alert checks after successful poll (non-blocking)
            try:
                from api.elastic_alerter import run_elastic_alerts
                asyncio.create_task(run_elastic_alerts())
            except Exception:
                pass

            # v2.45.23 — write to known_facts_current so agent FACTS injection
            # can surface ES cluster state alongside proxmox/swarm/pbs facts.
            try:
                from api.db.known_facts import batch_upsert_facts
                cluster_name = health_data.get("cluster_name") or "elasticsearch"
                facts = [
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.status",
                        "source":   "elastic_collector",
                        "value":    cluster_status,
                        "metadata": {"poll_url": self.url},
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.health",
                        "source":   "elastic_collector",
                        "value":    health,
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.nodes_total",
                        "source":   "elastic_collector",
                        "value":    int(health_data.get("number_of_nodes", 0)),
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.nodes_data",
                        "source":   "elastic_collector",
                        "value":    int(health_data.get("number_of_data_nodes", 0)),
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.shards_active",
                        "source":   "elastic_collector",
                        "value":    int(health_data.get("active_shards", 0)),
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.shards_unassigned",
                        "source":   "elastic_collector",
                        "value":    int(health_data.get("unassigned_shards", 0)),
                    },
                    {
                        "fact_key": f"prod.elastic.cluster.{cluster_name}.filebeat_status",
                        "source":   "elastic_collector",
                        "value":    filebeat_status,
                        "metadata": {"index_pattern": self.filebeat_pattern},
                    },
                ]
                batch_upsert_facts(facts, actor="elastic_collector")
            except Exception as _fe:
                log.debug("elastic fact write failed: %s", _fe)

            return {
                "health": health,
                "message": (
                    f"Cluster '{health_data.get('cluster_name', '?')}': "
                    f"{cluster_status}, "
                    f"{health_data.get('number_of_nodes', 0)} nodes"
                ),
                "cluster_health": cluster_status,
                "cluster_name": health_data.get("cluster_name"),
                "nodes": health_data.get("number_of_nodes", 0),
                "data_nodes": health_data.get("number_of_data_nodes", 0),
                "shards": {
                    "active": health_data.get("active_shards", 0),
                    "primary": health_data.get("active_primary_shards", 0),
                    "unassigned": health_data.get("unassigned_shards", 0),
                    "initializing": health_data.get("initializing_shards", 0),
                    "relocating": health_data.get("relocating_shards", 0),
                },
                "filebeat": {"status": filebeat_status},
            }

        except Exception as e:
            log.warning("ElasticCollector error: %s", e)
            return {
                "health": "error",
                "error": str(e),
                "message": f"Cannot reach Elasticsearch at {self.url}: {e}",
                "cluster_health": None,
                "nodes": 0,
                "shards": {},
                "filebeat": {"status": "unknown"},
            }
