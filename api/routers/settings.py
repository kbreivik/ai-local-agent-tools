"""GET/POST /api/settings — DB-backed settings with env-var seeding."""
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Body, HTTPException
from api.auth import get_current_user
from mcp_server.tools.skills.storage import get_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Registry: frontend key → {env_var, sensitive, default}
# "env_var" is used for seeding on first run only.
# "sensitive" = True means the GET response masks the value.
SETTINGS_KEYS: dict[str, dict] = {
    # Local AI
    "lmStudioUrl":           {"env": "LM_STUDIO_BASE_URL",      "sens": False, "default": ""},
    "lmStudioApiKey":        {"env": "LM_STUDIO_API_KEY",       "sens": True,  "default": ""},
    "modelName":             {"env": "LM_STUDIO_MODEL",         "sens": False, "default": ""},
    # External AI
    "externalProvider":      {"env": None,                      "sens": False, "default": "claude"},
    "externalApiKey":        {"env": "ANTHROPIC_API_KEY",       "sens": True,  "default": ""},
    "externalModel":         {"env": None,                      "sens": False, "default": "claude-sonnet-4-6"},
    # Escalation
    "autoEscalate":          {"env": None,                      "sens": False, "default": "both"},
    "requireConfirmation":   {"env": None,                      "sens": False, "default": True},
    # Coordinator
    "coordinatorPriorAttemptsEnabled": {"env": None,            "sens": False, "default": True},
    # Infrastructure — Docker / Messaging
    "dockerHost":            {"env": "DOCKER_HOST",             "sens": False, "default": ""},
    "kafkaBootstrapServers": {"env": "KAFKA_BOOTSTRAP_SERVERS", "sens": False, "default": ""},
    "elasticsearchUrl":      {"env": "ELASTIC_URL",             "sens": False, "default": ""},
    "kibanaUrl":             {"env": "KIBANA_URL",              "sens": False, "default": ""},
    "muninndbUrl":           {"env": "MUNINN_URL",              "sens": False, "default": ""},
    "swarmManagerIPs":       {"env": "",                        "sens": False, "default": ""},
    "swarmWorkerIPs":        {"env": "",                        "sens": False, "default": ""},
    "ghcrToken":             {"env": "GHCR_TOKEN",             "sens": True,  "default": ""},
    "agentDockerHost":       {"env": "AGENT01_DOCKER_HOST",    "sens": False, "default": ""},
    "agentHostIp":           {"env": "AGENT01_IP",             "sens": False, "default": ""},
    # Infrastructure — Proxmox
    "proxmoxHost":           {"env": "PROXMOX_HOST",            "sens": False, "default": ""},
    "proxmoxTokenId":        {"env": "PROXMOX_TOKEN_ID",        "sens": False, "default": ""},
    "proxmoxTokenSecret":    {"env": "PROXMOX_TOKEN_SECRET",    "sens": True,  "default": ""},
    "proxmoxUser":           {"env": "PROXMOX_USER",           "sens": False, "default": ""},
    "proxmoxNodes":          {"env": "PROXMOX_NODES",          "sens": False, "default": ""},
    # Infrastructure — FortiGate
    "fortigateHost":         {"env": "FORTIGATE_HOST",          "sens": False, "default": ""},
    "fortigateApiKey":       {"env": "FORTIGATE_API_KEY",       "sens": True,  "default": ""},
    # Infrastructure — TrueNAS
    "truenasHost":           {"env": "TRUENAS_HOST",            "sens": False, "default": ""},
    "truenasApiKey":         {"env": "TRUENAS_API_KEY",         "sens": True,  "default": ""},
    # Auto-update
    "autoUpdate":               {"env": None,                   "sens": False, "default": False},
    "autoUpdateInterval":       {"env": None,                   "sens": False, "default": 300},
    "ghcrTagCacheTTL":          {"env": None,                   "sens": False, "default": 600},
    # UI (stored server-side so they survive browser clears)
    "dashboardRefreshInterval": {"env": None,                   "sens": False, "default": 15000},
    # Data retention
    "opLogRetentionDays":       {"env": None,                   "sens": False, "default": 30},
    "opLogMaxLinesPerSession":  {"env": None,                   "sens": False, "default": 500},
    # Notifications
    "notificationWebhookUrl": {"env": None, "sens": False, "default": ""},
    "notifyOnRecovery":       {"env": None, "sens": False, "default": False},
    # Discovery
    "discoveryEnabled":       {"env": None, "sens": False, "default": "false"},
    "discoveryScopes":        {"env": None, "sens": False, "default": "[]"},
    # Rotation test
    "rotationTestMode":       {"env": None, "sens": False, "default": "adaptive"},
    "rotationTestDelayMs":    {"env": None, "sens": False, "default": "500"},
    "rotationMaxParallel":    {"env": None, "sens": False, "default": "10"},
    "rotationWindowsDelayMs": {"env": None, "sens": False, "default": "2000"},
    # Bookstack sync
    "bookstackSyncEnabled":       {"env": None, "sens": False, "default": False},
    "bookstackSyncIntervalHours": {"env": None, "sens": False, "default": 6},
    # Kafka overview cache TTL (seconds)
    "kafkaOverviewCacheTTL":      {"env": None, "sens": False, "default": 30},
    # Elasticsearch: sample schema on filter-miss (0 hits but window has data)
    "elasticSchemaDiscoveryOnMiss": {"env": None, "sens": False, "default": True},
    # --- Facts & Knowledge (v2.35.0) ---
    # Thresholds
    "factInjectionThreshold":            {"env": None, "sens": False, "default": 0.7,  "type": "float", "group": "Facts & Knowledge"},
    "factInjectionMaxRows":              {"env": None, "sens": False, "default": 40,   "type": "int",   "group": "Facts & Knowledge"},
    # Source weights
    "factSourceWeight_manual":                 {"env": None, "sens": False, "default": 1.0,  "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_proxmox_collector":      {"env": None, "sens": False, "default": 0.9,  "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_swarm_collector":        {"env": None, "sens": False, "default": 0.9,  "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_docker_agent_collector": {"env": None, "sens": False, "default": 0.85, "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_pbs_collector":          {"env": None, "sens": False, "default": 0.85, "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_kafka_collector":        {"env": None, "sens": False, "default": 0.8,  "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_fortiswitch_collector":  {"env": None, "sens": False, "default": 0.85, "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_agent_observation":      {"env": None, "sens": False, "default": 0.5,  "type": "float", "group": "Facts & Knowledge"},
    "factSourceWeight_rag_extraction":         {"env": None, "sens": False, "default": 0.4,  "type": "float", "group": "Facts & Knowledge"},
    # Decay
    "factHalfLifeHours_collector":       {"env": None, "sens": False, "default": 168,  "type": "int",   "group": "Facts & Knowledge"},
    "factHalfLifeHours_agent":           {"env": None, "sens": False, "default": 24,   "type": "int",   "group": "Facts & Knowledge"},
    "factHalfLifeHours_manual_phase1":   {"env": None, "sens": False, "default": 720,  "type": "int",   "group": "Facts & Knowledge"},
    "factHalfLifeHours_manual_phase2":   {"env": None, "sens": False, "default": 1440, "type": "int",   "group": "Facts & Knowledge"},
    "factHalfLifeHours_agent_volatile":  {"env": None, "sens": False, "default": 2,    "type": "int",   "group": "Facts & Knowledge"},
    "factVerifyCountCap":                {"env": None, "sens": False, "default": 10,   "type": "int",   "group": "Facts & Knowledge"},
    # Age rejection — settings registered now, enforced in v2.35.3
    "factAgeRejectionMode":              {"env": None, "sens": False, "default": "medium", "type": "str",   "group": "Facts & Knowledge"},
    "factAgeRejectionMaxAgeMin":         {"env": None, "sens": False, "default": 5,        "type": "int",   "group": "Facts & Knowledge"},
    "factAgeRejectionMinConfidence":     {"env": None, "sens": False, "default": 0.85,     "type": "float", "group": "Facts & Knowledge"},
    # Runbook injection — v2.45.26 default is "replace" (matches implemented runtime behaviour)
    "runbookInjectionMode":              {"env": None, "sens": False, "default": "replace", "type": "str", "group": "Facts & Knowledge"},
    "runbookClassifierMode":             {"env": None, "sens": False, "default": "keyword", "type": "str", "group": "Facts & Knowledge"},
    "runbookSemanticThreshold": {
        "type": "float",
        "default": 0.55,
        "group": "Facts & Knowledge",
        "label": "Runbook semantic similarity threshold",
        "description": "Cosine similarity threshold for semantic runbook matching (0.0-1.0). Lower = more permissive.",
    },
    # Preflight — settings registered now, consumed in v2.35.1
    "preflightPanelMode":                {"env": None, "sens": False, "default": "always_visible", "type": "str",  "group": "Facts & Knowledge"},
    "preflightDisambiguationTimeout":    {"env": None, "sens": False, "default": 300,              "type": "int",  "group": "Facts & Knowledge"},
    "preflightLLMFallbackEnabled":       {"env": None, "sens": False, "default": True,             "type": "bool", "group": "Facts & Knowledge"},
    "preflightLLMFallbackMaxTokens":     {"env": None, "sens": False, "default": 200,              "type": "int",  "group": "Facts & Knowledge"},

    # --- External AI Router (v2.36.0) ---
    # Master switch. off = no behaviour change from pre-v2.36 (default).
    #                manual = UI-only escalation button, no auto-rules.
    #                auto   = rules in Routing Triggers subsection fire automatically.
    "externalRoutingMode":                {"env": None, "sens": False, "default": "off",     "type": "str",   "group": "External AI Router"},
    "externalRoutingOutputMode":          {"env": None, "sens": False, "default": "replace", "type": "str",   "group": "External AI Router"},
    # Routing Triggers (rules) — all opt-in; master switch must be 'auto' or 'manual'.
    "routeOnConsecutiveFailures":         {"env": None, "sens": False, "default": 3,         "type": "int",   "group": "External AI Router"},
    "routeOnBudgetExhaustion":            {"env": None, "sens": False, "default": True,      "type": "bool",  "group": "External AI Router"},
    "routeOnGateFailure":                 {"env": None, "sens": False, "default": True,      "type": "bool",  "group": "External AI Router"},
    "routeOnPriorAttemptsGte":            {"env": None, "sens": False, "default": 0,         "type": "int",   "group": "External AI Router"},
    "routeOnComplexityKeywords":          {"env": None, "sens": False, "default": "",        "type": "str",   "group": "External AI Router"},
    "routeOnComplexityMinPriorAttempts":  {"env": None, "sens": False, "default": 2,         "type": "int",   "group": "External AI Router"},
    # Context handoff
    "externalContextLastNToolResults":    {"env": None, "sens": False, "default": 5,         "type": "int",   "group": "External AI Router"},
    # Limits
    "routeMaxExternalCallsPerOp":         {"env": None, "sens": False, "default": 3,         "type": "int",   "group": "External AI Router"},
    "externalConfirmTimeoutSeconds":      {"env": None, "sens": False, "default": 300,       "type": "int",   "group": "External AI Router"},

    # --- Agent Budgets (v2.36.5) ---
    # Per-agent-type tool call budget. When the agent makes N tool calls without
    # emitting a final synthesis, the loop forces synthesis via run_forced_synthesis
    # and the operation status becomes 'capped'. Defaults match the pre-v2.36.5
    # hardcoded values. Safe range 4..100. Set to 0 to restore the hardcoded default.
    # Type aliases: status→observe, research→investigate, action→execute.
    "agentToolBudget_observe":      {"env": None, "sens": False, "default": 8,  "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_investigate":  {"env": None, "sens": False, "default": 16, "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_execute":      {"env": None, "sens": False, "default": 14, "type": "int", "group": "Agent Budgets"},
    "agentToolBudget_build":        {"env": None, "sens": False, "default": 12, "type": "int", "group": "Agent Budgets"},

    # --- Agent Token Cap (v2.47.12) ---
    # Cumulative input + output tokens across an entire agent run. When
    # exceeded, the loop forces synthesis and operations.status becomes
    # 'capped'. Each subagent gets its own fresh counter (no shared cap).
    # Safe range 10_000..250_000. Set to 0 to restore the default (200_000).
    # Per-agent-type overrides (agentMaxTotalTokens_observe etc.) can be
    # added to this registry in a future version without code changes.
    "agentMaxTotalTokens": {
        "env": "AGENT_MAX_TOTAL_TOKENS", "sens": False,
        "default": 200000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Maximum cumulative tokens (prompt + completion, summed across "
            "all steps) per agent run. When exceeded, the loop forces "
            "synthesis and the operation is marked 'capped'. Subagents get "
            "their own fresh counter. Safe range 10000..250000."
        ),
    },

    # --- Per-agent-type Token Caps (v2.47.13) ---
    # Per-type overrides for the v2.47.12 global agentMaxTotalTokens.
    # Lookup at every cap check: per-type key → global → env → hardcoded.
    # Defaults calibrated to each type's tool budget and typical tool result
    # sizes. Tune individually in the GUI based on observed run patterns.
    "agentMaxTotalTokens_observe": {
        "env": None, "sens": False,
        "default": 80000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for observe (status) runs. Short tool chains, small "
            "results — 80000 is generous for typical status checks. "
            "Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_investigate": {
        "env": None, "sens": False,
        "default": 200000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for investigate (research) runs. Longest tool chains, "
            "biggest cumulative prompts — 200000 matches the global default. "
            "Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_execute": {
        "env": None, "sens": False,
        "default": 150000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for execute (action) runs. Moderate length plus "
            "post-action verify steps. Range 10000..250000."
        ),
    },
    "agentMaxTotalTokens_build": {
        "env": None, "sens": False,
        "default": 120000, "type": "int",
        "min": 10000, "max": 250000,
        "group": "Agent Budgets",
        "description": (
            "Token cap for build (skill creation) runs. Moderate verbosity "
            "from skill_create / skill_regenerate. Range 10000..250000."
        ),
    },

    # --- Render-and-caption prompt (v2.36.8) ---
    # Dark launch: tool is always registered & allowlisted; this flag only
    # controls whether the prompt section teaching the agent to use it is
    # surfaced. Flip ON after verifying on a test run.
    "renderToolPromptEnabled": {
        "env": None, "sens": False, "default": False, "type": "bool",
        "group": "Agent Budgets",
    },

    # --- Memory backend (v2.43.8/v2.43.9) ---
    "memoryEnabled": {
        "env": None, "sens": False, "default": True, "type": "bool",
        "group": "Agent Budgets",
        "description": (
            "When false, all MuninnDB/memory calls return empty results (NullMuninnClient). "
            "Useful for A/B testing agent quality without memory context."
        ),
    },
    "memoryBackend": {
        "env": None, "sens": False, "default": "muninndb", "type": "str",
        "group": "Agent Budgets",
        "description": (
            "Memory storage backend. 'muninndb' uses MuninnDB REST API. "
            "'postgres' uses pg_engrams table (tsvector + Hebbian access_count). "
            "Ignored when memoryEnabled=false."
        ),
    },

    # --- Appearance (v2.37.0) ---
    # Number of unique recent agent tasks to show in the RECENT section
    # below task templates. Deduplicated by exact task text — only the
    # most recent occurrence of each unique task shows. Range 1–50.
    "recentTasksCount": {
        "env": None, "sens": False, "default": 10, "type": "int",
        "min": 1, "max": 50,
        "group": "Appearance",
        "description": (
            "Number of recent agent tasks to show in the RECENT section "
            "below the task templates. Deduplicated by exact task text — "
            "only the most recent occurrence of each unique task shows. "
            "Range 1–50."
        ),
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(value: Any) -> str:
    """Return a masked version of a sensitive value."""
    s = str(value)
    return (s[:4] + "***") if len(s) > 4 else "***"


def seed_defaults() -> int:
    """Populate settings table from env vars if the table is empty.

    Called once from api/main.py lifespan on startup.
    Returns number of keys seeded (0 if table already had data).
    """
    backend = get_backend()
    # Check if already seeded: if any key exists, skip.
    if backend.get_setting("lmStudioUrl") is not None:
        return 0

    seeded = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        value = os.environ.get(env_var, "") if env_var else meta["default"]
        if value is not None and value != "":  # Only seed non-empty values
            backend.set_setting(key, value)
            seeded += 1

    logger.info("Settings: seeded %d keys from environment", seeded)
    return seeded


def sync_env_from_db() -> int:
    """Mirror DB settings into os.environ so collectors see user-saved values.

    Called on startup after seed_defaults(). DB is the source of truth after
    first save — this ensures settings saved via the UI survive process restarts
    without requiring env var changes in .env / Ansible.
    Returns number of keys synced.
    """
    backend = get_backend()
    synced = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        if not env_var:
            continue
        db_value = backend.get_setting(key)
        if db_value is not None and str(db_value).strip():
            from api.crypto import decrypt_value
            os.environ[env_var] = decrypt_value(str(db_value))
            synced += 1
    logger.info("Settings: synced %d keys from DB into os.environ", synced)
    return synced


@router.get("")
def get_settings(_: str = Depends(get_current_user)):
    """Return all settings with source badges, categories, and encryption status."""
    try:
        from api.settings_manager import list_settings
        settings = list_settings(SETTINGS_KEYS)
        # Also return flat dict for backward compat with existing GUI
        flat = {s["key"]: s["value"] for s in settings}
        return {
            "status": "ok",
            "data": {"settings": flat, "detailed": settings},
            "timestamp": _ts(),
            "message": "OK",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("")
def update_settings(
    body: dict[str, Any] = Body(...),
    _: str = Depends(get_current_user),
):
    """Persist settings to DB. Sensitive keys are auto-encrypted. Returns updated values (masked)."""
    try:
        from api.settings_manager import set_setting as _set, SENSITIVE_KEYS
        updated = {}
        for key, value in body.items():
            if key not in SETTINGS_KEYS:
                continue
            # Don't overwrite real values with masked placeholders or empty secrets
            if isinstance(value, str) and "***" in value:
                continue
            if key in SENSITIVE_KEYS and (value == "" or value is None):
                continue
            _set(key, value, registry=SETTINGS_KEYS)
            updated[key] = _mask(value) if (key in SENSITIVE_KEYS and value) else value
        return {"status": "ok", "data": {"updated": updated}, "timestamp": _ts(), "message": f"Updated {len(updated)} setting(s)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/seed")
def reseed_settings(_: str = Depends(get_current_user)):
    """Force re-seed settings from env vars (overwrites existing DB values)."""
    try:
        backend = get_backend()
        seeded = 0
        for key, meta in SETTINGS_KEYS.items():
            env_var = meta["env"]
            value = os.environ.get(env_var, "") if env_var else meta["default"]
            if value is not None and value != "":
                backend.set_setting(key, value)
                seeded += 1
        logger.info("Settings: force-reseeded %d keys", seeded)
        return {"status": "ok", "data": {"seeded": seeded}, "timestamp": _ts(), "message": f"Seeded {seeded} key(s)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── External AI: test connection ────────────────────────────────────────────
@router.post("/test-external-ai")
async def test_external_ai(
    body: dict[str, Any] = Body(...),
    _: str = Depends(get_current_user),
):
    """Round-trip a minimal request to the selected external AI provider.

    Body: {provider, api_key?, model}
    - api_key: optional. If empty/missing or contains '***' (masked from GET),
      falls back to the DB-saved externalApiKey.
    - provider: 'claude' | 'openai' | 'grok'
    - model:    provider-specific model id

    Returns:
      {ok: bool, stage: 'auth'|'request'|'parse'|'success',
       latency_ms: int, model: str, error?: str, input_tokens?: int,
       output_tokens?: int}
    """
    import time
    import httpx
    from api.settings_manager import get_setting

    provider = str(body.get("provider") or "").strip().lower()
    model    = str(body.get("model") or "").strip()
    api_key  = str(body.get("api_key") or "").strip()

    # Fallback to saved key when the submitted value is blank or masked
    if not api_key or "***" in api_key:
        api_key = str(get_setting("externalApiKey", SETTINGS_KEYS)["value"] or "").strip()

    if provider not in {"claude", "openai", "grok"}:
        return {"ok": False, "stage": "auth",
                "error": f"Unknown provider: {provider!r}"}
    if not api_key:
        return {"ok": False, "stage": "auth", "error": "No API key set"}
    if not model:
        return {"ok": False, "stage": "auth", "error": "No model set"}

    # Provider-specific request shape
    if provider == "claude":
        url     = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": api_key,
                   "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        payload = {"model": model, "max_tokens": 1,
                   "messages": [{"role": "user", "content": "ping"}]}
    elif provider == "openai":
        url     = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}
        payload = {"model": model, "max_tokens": 1,
                   "messages": [{"role": "user", "content": "ping"}]}
    else:  # grok (xAI, OpenAI-compatible)
        url     = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}
        payload = {"model": model, "max_tokens": 1,
                   "messages": [{"role": "user", "content": "ping"}]}

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return {"ok": False, "stage": "request", "error": "Timed out after 10s"}
    except httpx.HTTPError as e:
        return {"ok": False, "stage": "request", "error": f"Network error: {e!s}"}
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Non-2xx → extract provider error message
    if r.status_code >= 400:
        msg = f"HTTP {r.status_code}"
        try:
            err = r.json().get("error")
            if isinstance(err, dict):
                msg = err.get("message") or msg
            elif isinstance(err, str):
                msg = err
        except Exception:
            pass
        stage = "auth" if r.status_code in (401, 403) else "request"
        return {"ok": False, "stage": stage, "status": r.status_code,
                "latency_ms": latency_ms, "model": model, "error": msg}

    # 2xx — parse usage block if present (best-effort)
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "stage": "parse", "latency_ms": latency_ms,
                "model": model, "error": "Non-JSON response"}

    usage = data.get("usage") or {}
    # Claude: {input_tokens, output_tokens}. OpenAI/Grok: {prompt_tokens, completion_tokens}
    in_tok  = usage.get("input_tokens",  usage.get("prompt_tokens"))
    out_tok = usage.get("output_tokens", usage.get("completion_tokens"))

    return {
        "ok": True, "stage": "success",
        "latency_ms": latency_ms,
        "model": data.get("model") or model,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
    }
