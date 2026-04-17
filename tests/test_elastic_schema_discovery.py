"""Tests for v2.34.6 elastic schema discovery on filter miss.

When elastic_search_logs (or elastic_log_pattern) returns 0 hits but the
time window has data, the response is enriched with:
  - sample_docs (up to 3 real docs, no filters)
  - available_fields (top 20 flattened fields + example)
  - suggested_filters ({service, host, level} heuristics)

Gated on the elasticSchemaDiscoveryOnMiss setting (default True).
"""
from unittest.mock import patch


# ─── helpers ──────────────────────────────────────────────────────────────

def _mk_post_responder(
    main_total: int,
    window_total: int,
    sample_hits: list | None = None,
):
    """Build a _post side-effect that mimics ES for search + window + sample calls.

    Heuristic matching on body shape:
      - size == 0                 → window count probe
      - query.bool.filter only    → sample probe
      - everything else           → main search
    """
    default_samples = [
        {"_source": {
            "@timestamp": "2026-04-17T15:00:00Z",
            "service": {"name": "logstash"},
            "log": {"level": "info"},
            "host": {"name": "worker-01"},
            "message": "pipeline started",
        }},
        {"_source": {
            "@timestamp": "2026-04-17T14:59:00Z",
            "service": {"name": "elasticsearch"},
            "log": {"level": "warn"},
            "host": {"name": "worker-02"},
            "message": "slow query",
        }},
    ]
    samples = sample_hits if sample_hits is not None else default_samples

    def responder(path, body):
        size = body.get("size", 10)
        q = body.get("query", {})
        bool_q = q.get("bool", {}) if isinstance(q, dict) else {}
        is_sample = (
            "filter" in bool_q
            and "must" not in bool_q
            and size and size >= 2
        )
        if size == 0:
            return {"hits": {"total": {"value": window_total, "relation": "eq"}}}
        if is_sample:
            return {"hits": {"hits": samples, "total": {"value": len(samples)}}}
        # main search
        return {
            "hits": {
                "hits": [],
                "total": {"value": main_total, "relation": "eq"},
            }
        }
    return responder


# ─── helper unit tests ────────────────────────────────────────────────────

def test_compact_doc_truncates_long_strings():
    from mcp_server.tools.elastic import _compact_doc
    src = {"message": "x" * 500}
    out = _compact_doc(src, max_string_len=160)
    assert len(out["message"]) <= 161  # 160 + ellipsis
    assert out["message"].endswith("…")


def test_flatten_dict_joins_nested_keys():
    from mcp_server.tools.elastic import _flatten_dict
    out = _flatten_dict({"service": {"name": "logstash"}, "level": "info"})
    assert "service.name" in out
    assert out["service.name"] == "logstash"
    assert out["level"] == "info"


def test_suggest_filter_fields_identifies_service_name():
    from mcp_server.tools.elastic import _suggest_filter_fields
    available = {
        "service.name": {"count": 2, "example": "logstash"},
        "host.name": {"count": 2, "example": "worker-01"},
        "log.level": {"count": 2, "example": "info"},
        "message": {"count": 2, "example": "..."},
    }
    suggestions = _suggest_filter_fields(available)
    categories = {s["category"] for s in suggestions}
    assert "service" in categories
    assert "host" in categories
    assert "level" in categories
    svc = [s for s in suggestions if s["category"] == "service"][0]
    assert svc["field"] == "service.name"
    assert svc["example"] == "logstash"


def test_suggest_filter_fields_identifies_container_name_for_docker_shippers():
    """Filebeat/Docker shipper pattern: container.name, no service.name."""
    from mcp_server.tools.elastic import _suggest_filter_fields
    available = {
        "container.name": {"count": 3, "example": "kafka_broker-1"},
        "host.name": {"count": 3, "example": "worker-01"},
    }
    suggestions = _suggest_filter_fields(available)
    svc = [s for s in suggestions if s["category"] == "service"]
    assert svc and svc[0]["field"] == "container.name"


def test_suggest_filter_fields_empty_when_no_match():
    from mcp_server.tools.elastic import _suggest_filter_fields
    assert _suggest_filter_fields({"random": {"count": 1, "example": "x"}}) == []


# ─── setting gate ─────────────────────────────────────────────────────────

def test_schema_discovery_enabled_defaults_true_on_missing_setting():
    from mcp_server.tools.elastic import _schema_discovery_enabled
    # Simulate backend returning None (setting never written).
    with patch("mcp_server.tools.skills.storage.get_backend") as gb:
        gb.return_value.get_setting.return_value = None
        assert _schema_discovery_enabled() is True


def test_schema_discovery_disabled_when_setting_false():
    from mcp_server.tools.elastic import _schema_discovery_enabled
    with patch("mcp_server.tools.skills.storage.get_backend") as gb:
        gb.return_value.get_setting.return_value = "false"
        assert _schema_discovery_enabled() is False


def test_schema_discovery_enabled_handles_backend_exception():
    from mcp_server.tools.elastic import _schema_discovery_enabled
    with patch("mcp_server.tools.skills.storage.get_backend",
               side_effect=RuntimeError("db down")):
        assert _schema_discovery_enabled() is True  # safe default


# ─── integration: elastic_search_logs ─────────────────────────────────────

def test_enrichment_fires_on_zero_hit_with_window(monkeypatch):
    """0 hits + nonzero window → sample_docs + available_fields + suggested_filters."""
    monkeypatch.setenv("ELASTIC_URL", "http://fake:9200")
    responder = _mk_post_responder(main_total=0, window_total=102)
    with patch("mcp_server.tools.elastic._post", side_effect=responder), \
         patch("mcp_server.tools.elastic._schema_discovery_enabled", return_value=True):
        from mcp_server.tools.elastic import elastic_search_logs
        result = elastic_search_logs(service="nonexistent", minutes_ago=60)

    assert result["status"] == "ok"
    data = result["data"]
    assert data["total"] == 0
    assert data["total_in_window"] == 102
    assert "sample_docs" in data
    assert len(data["sample_docs"]) >= 1
    assert "available_fields" in data
    assert "service.name" in data["available_fields"]
    assert any(s["category"] == "service" for s in data["suggested_filters"])


def test_no_enrichment_when_window_is_empty(monkeypatch):
    """0 hits AND 0 in window → no sample_docs (window has no data)."""
    monkeypatch.setenv("ELASTIC_URL", "http://fake:9200")
    responder = _mk_post_responder(main_total=0, window_total=0)
    with patch("mcp_server.tools.elastic._post", side_effect=responder), \
         patch("mcp_server.tools.elastic._schema_discovery_enabled", return_value=True):
        from mcp_server.tools.elastic import elastic_search_logs
        result = elastic_search_logs(service="logstash")

    assert result["status"] == "ok"
    data = result["data"]
    assert "sample_docs" not in data
    assert "available_fields" not in data


def test_no_enrichment_when_results_nonzero(monkeypatch):
    """Nonzero total → no enrichment even if window also populated."""
    monkeypatch.setenv("ELASTIC_URL", "http://fake:9200")
    responder = _mk_post_responder(main_total=5, window_total=100)
    with patch("mcp_server.tools.elastic._post", side_effect=responder), \
         patch("mcp_server.tools.elastic._schema_discovery_enabled", return_value=True):
        from mcp_server.tools.elastic import elastic_search_logs
        result = elastic_search_logs(service="logstash")

    data = result["data"]
    assert "sample_docs" not in data


def test_enrichment_disabled_by_setting(monkeypatch):
    """elasticSchemaDiscoveryOnMiss=False suppresses enrichment."""
    monkeypatch.setenv("ELASTIC_URL", "http://fake:9200")
    responder = _mk_post_responder(main_total=0, window_total=99)
    with patch("mcp_server.tools.elastic._post", side_effect=responder), \
         patch("mcp_server.tools.elastic._schema_discovery_enabled", return_value=False):
        from mcp_server.tools.elastic import elastic_search_logs
        result = elastic_search_logs(service="logstash")

    data = result["data"]
    assert "sample_docs" not in data
    assert "available_fields" not in data


def test_suggested_filters_identify_container_name_shipper(monkeypatch):
    """Docker/filebeat shipper: container.name instead of service.name."""
    monkeypatch.setenv("ELASTIC_URL", "http://fake:9200")
    docker_samples = [
        {"_source": {
            "@timestamp": "2026-04-17T15:00:00Z",
            "container": {"name": "logstash"},
            "host": {"name": "worker-01"},
            "message": "ok",
        }},
        {"_source": {
            "@timestamp": "2026-04-17T14:59:00Z",
            "container": {"name": "elasticsearch"},
            "host": {"name": "worker-02"},
            "message": "ok",
        }},
    ]
    responder = _mk_post_responder(
        main_total=0, window_total=50, sample_hits=docker_samples,
    )
    with patch("mcp_server.tools.elastic._post", side_effect=responder), \
         patch("mcp_server.tools.elastic._schema_discovery_enabled", return_value=True):
        from mcp_server.tools.elastic import elastic_search_logs
        result = elastic_search_logs(service="logstash")

    data = result["data"]
    suggestions = data.get("suggested_filters", [])
    svc = [s for s in suggestions if s["category"] == "service"]
    assert svc, "Expected a service-category suggestion"
    assert svc[0]["field"] == "container.name"
