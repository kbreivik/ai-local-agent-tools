# Improvements to HP1 Skill System — From Article Analysis

## The 4 Patterns and What They Mean for HP1

### 1. Rule Maker Pattern (Tessl) → Skills should be SPECS before CODE

**Problem in current design:** `skill_create` goes straight from a description to Python code.
The LLM hallucinates endpoints, invents parameters, guesses auth flows. You don't know
what's wrong until the skill runs and fails.

**Fix: Two-phase generation — spec first, code second.**

Instead of `description → LLM → code`, do `description → LLM → spec → validate spec → LLM → code`.

The spec is the deterministic artifact. It can be reviewed, tested against a live service
(does the endpoint exist? does the auth work?), and THEN used to generate code deterministically.

```python
# NEW: Skill spec format — generated BEFORE code, validated BEFORE code generation
SKILL_SPEC = {
    "name": "fortigate_ha_status",
    "service": "fortigate",
    "description": "Check FortiGate HA peer status",
    "endpoints": [
        {
            "method": "GET",
            "path": "/api/v2/monitor/system/ha-peer",
            "auth": "query_param:access_token",
            "expected_status": 200,
            "response_fields": ["serial-no", "hostname", "priority", "ha-state"],
        }
    ],
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
    "config_keys": ["FORTIGATE_HOST", "FORTIGATE_API_KEY"],
    "health_rules": {
        "ok": "all peers ha-state == 'in-sync'",
        "degraded": "any peer ha-state != 'in-sync'",
        "error": "connection failed or HTTP != 200",
    },
}
```

**Why this works:** The spec is machine-checkable BEFORE touching an LLM again:
- Does `/api/v2/monitor/system/ha-peer` return 200? → `httpx.get()` to verify
- Does the response contain `serial-no`, `hostname`, etc.? → Parse actual response
- Does `FORTIGATE_HOST` resolve? → DNS/connection check

Once the spec is validated against reality, code generation from a validated spec is nearly
deterministic — there's almost nothing left to hallucinate.

**New flow:**
```
skill_create(description)
  → LLM generates SKILL_SPEC (structured, small)
  → validate_spec_against_live_service(spec)  # actually probe the endpoint
  → if valid: generate_code_from_spec(spec)    # deterministic template fill
  → if invalid: return what failed + suggest fixes
```

### 2. Two-Layer Model (McKinsey) → Deterministic Orchestration + Bounded Execution

**Problem:** The agent decides on its own when to search for skills, when to create them,
what order to do things. With 40+ tools, it gets confused, skips steps, hallucinates tool names.

**Fix: Phase-gated workflows with evaluation at each step.**

Apply this to the two workflows that matter most:

#### A. Environment Discovery Workflow (deterministic)

When the agent is told "here are my servers" or "scan my network", it shouldn't freelance.
It should follow a rigid pipeline:

```
Phase 1: ENUMERATE
  Input:  List of hosts/IPs + credentials (from settings or user)
  Action: For each host, try: SSH connect, HTTPS probe, HTTP probe, SNMP probe
  Output: Reachable hosts with connection method and open ports
  Gate:   At least 1 host reachable → proceed. Zero → error with diagnostics.

Phase 2: IDENTIFY
  Input:  Reachable hosts from Phase 1
  Action: For each host:
          - SSH: run `uname -a`, `cat /etc/os-release`, `docker version`, etc.
          - HTTPS: try known API paths (/api/v2/monitor/system/status = FortiGate,
            /api2/json/version = Proxmox, /api/v2.0/system = TrueNAS, etc.)
          - HTTP: check response headers, title tags, known fingerprints
  Output: Service identification per host: {host, service_type, version, api_base}
  Gate:   All hosts identified or marked "unknown" → proceed.

Phase 3: CATALOG
  Input:  Identified services
  Action: Upsert into service_catalog table. Check for existing skills.
  Output: Services with/without skill coverage
  Gate:   Always proceed.

Phase 4: RECOMMEND
  Input:  Uncovered services
  Action: For each uncovered service, generate a skill_create recommendation
          with specific description, category, api_base, auth_type.
          If docs are ingested, include relevant context.
  Output: Prioritized list of skills to create
  Gate:   Return list to agent/user for approval before creating anything.
```

This is a deterministic workflow. The agent doesn't decide what phase comes next.
The workflow engine does.

**Implementation:** Add `mcp_server/tools/skills/discovery.py` with:

```python
def discover_environment(hosts: list[dict]) -> dict:
    """
    Run the 4-phase environment discovery pipeline.
    Each host dict: {"address": "192.168.1.1", "credentials": "ssh_key|api_key|..."}
    Returns: full catalog + skill recommendations.
    """

def probe_host(address: str, port: int = None) -> dict:
    """Phase 1: Check connectivity and identify open services."""

def identify_service(address: str, connection_info: dict) -> dict:
    """Phase 2: Fingerprint the service. Returns service_type + version."""

def recommend_skills(uncovered_services: list[dict]) -> dict:
    """Phase 4: Generate skill creation recommendations."""
```

**The agent calls ONE tool: `discover_environment([...])`.** The phases execute
deterministically inside that function. No LLM decisions between phases.

#### B. Skill Creation Workflow (phase-gated)

```
Phase 1: SEARCH     → skill_search() — does a skill already exist?
Phase 2: CONTEXT    → doc_retrieval.fetch_relevant_docs() — get documentation
Phase 3: SPEC       → LLM generates SKILL_SPEC (bounded, structured)
Phase 4: VALIDATE   → probe live service endpoints from spec
Phase 5: GENERATE   → code from validated spec (near-deterministic)
Phase 6: AST_CHECK  → validator.validate_skill_code()
Phase 7: DRY_RUN    → execute skill against live service, check response shape
Phase 8: REGISTER   → load into MCP + SQLite

Each phase has a gate. Fail at any gate → return specific error + what to fix.
Max 2 LLM calls total (spec generation + code generation).
```

### 3. Progressive Disclosure (Cloudflare/Anthropic) → Don't Dump 50 Tools Into Context

**Problem:** As you add dynamic skills, you could have 30-50+ tools. The LLM sees all of
them in every request. Performance and accuracy degrade.

**Fix: Tool tiering with lazy loading.**

```
Tier 1 (always loaded):  Core tools — swarm_status, kafka_broker_status, etc. (~15 tools)
Tier 2 (always loaded):  Meta tools — skill_search, skill_create, discover_environment (~5 tools)
Tier 3 (loaded on demand): Dynamic skills — loaded only when skill_search returns them
```

**How Tier 3 works:**
- Agent calls `skill_search("fortigate")` → returns skill names + descriptions
- Agent decides it needs `fortigate_ha_status`
- Agent calls `skill_execute(name="fortigate_ha_status", params={...})`
- The `skill_execute` tool is the ONLY dynamic skill tool registered in MCP
- It dispatches to the right skill module internally

This means you register ONE generic tool for all dynamic skills, not one per skill:

```python
@mcp.tool()
def skill_execute(name: str, **kwargs) -> dict:
    """Execute a dynamic skill by name. Call skill_search first to find available skills.
    Pass parameters as keyword arguments matching the skill's parameter schema."""
    return skill_tools.skill_execute(name, **kwargs)
```

**Benefits:**
- LLM sees 20 tools, not 50+
- Skill descriptions are only loaded when searched for
- Adding 100 new skills doesn't slow anything down
- Matches the Anthropic "filesystem browse" pattern — discover then use

### 4. Evaluation Gates (McKinsey) → Critic + Deterministic Checks at Every Step

**Problem in current design:** Generated skills are only AST-validated. A syntactically valid
skill can still:
- Call an endpoint that doesn't exist
- Parse the response wrong
- Return the wrong status (ok when should be degraded)
- Miss error handling for common failure modes

**Fix: Three-layer validation.**

```
Layer 1: DETERMINISTIC (fast, no LLM)
  - AST syntax check
  - Banned imports check
  - SKILL_META contract check (all required fields present)
  - Response shape check (returns {status, data, timestamp, message})
  - Config keys check (are required env vars set?)

Layer 2: LIVE PROBE (medium, no LLM)
  - If service is reachable: call the actual endpoint from the spec
  - Check: does the response status match expectations?
  - Check: do the expected response fields exist?
  - Check: does the skill's execute() return valid {status, data, ...}?
  - Timeout test: does it handle unreachable host gracefully?

Layer 3: CRITIC (slow, uses LLM — only when local LLM available)
  - Feed the generated code + the skill spec + the actual API response to the LLM
  - Ask: "Does this code correctly implement the spec? List any issues."
  - Structured output: [{"issue": "...", "severity": "error|warning", "fix": "..."}]
  - Only block on severity=error. Warnings are logged but don't prevent registration.
```

**Layer 2 is the key differentiator.** It's what makes skills deterministic — you're testing
against reality, not against what the LLM thinks the API looks like.

### 5. Service Fingerprinting (new module, enables self-discovery)

The user wants: "give it servers, it figures out what they run."

```python
# Known service fingerprints — what to look for on each host
SERVICE_FINGERPRINTS = {
    "proxmox": {
        "https_paths": ["/api2/json/version"],
        "response_contains": ["repoid", "version"],
        "default_port": 8006,
    },
    "fortigate": {
        "https_paths": ["/api/v2/monitor/system/status"],
        "response_contains": ["serial", "version"],
        "default_port": 443,
        "verify_ssl": False,
    },
    "truenas": {
        "https_paths": ["/api/v2.0/system/version"],
        "response_contains": ["TrueNAS"],
        "default_port": 443,
    },
    "synology": {
        "https_paths": ["/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query"],
        "response_contains": ["SYNO."],
        "default_port": 5001,
    },
    "unifi": {
        "https_paths": ["/api/s/default/stat/health"],
        "response_contains": ["subsystem"],
        "default_port": 8443,
    },
    "opnsense": {
        "https_paths": ["/api/core/firmware/status"],
        "response_contains": ["product_version"],
        "default_port": 443,
    },
    "docker": {
        "http_paths": ["/version"],
        "response_contains": ["ApiVersion"],
        "default_port": 2375,
        "ssh_command": "docker version --format '{{.Server.Version}}'",
    },
    "elasticsearch": {
        "http_paths": ["/"],
        "response_contains": ["cluster_name", "tagline"],
        "default_port": 9200,
    },
    "pihole": {
        "http_paths": ["/admin/api.php?summary"],
        "response_contains": ["domains_being_blocked"],
        "default_port": 80,
    },
    "grafana": {
        "http_paths": ["/api/health"],
        "response_contains": ["database"],
        "default_port": 3000,
    },
    "portainer": {
        "https_paths": ["/api/status"],
        "response_contains": ["Version"],
        "default_port": 9443,
    },
}
```

The discovery pipeline uses this to fingerprint services without ANY LLM calls.
It's pure deterministic pattern matching. The LLM is only used AFTER discovery,
to recommend what skills to create.

---

## Summary: What to Add to the Prompt

### New modules:
1. `discovery.py` — 4-phase environment discovery pipeline
2. `fingerprints.py` — service fingerprint database
3. `spec_generator.py` — generates SKILL_SPEC before code (Rule Maker pattern)
4. `live_validator.py` — probes actual service endpoints to validate specs + skills

### Changes to existing modules:
- `generator.py` → two-phase: spec first, code from validated spec
- `validator.py` → add Layer 2 (live probe) and Layer 3 (critic) 
- `meta_tools.py` → add `discover_environment()`, `skill_execute()`, `validate_skill_live()`
- `loader.py` → register ONE `skill_execute` dispatcher instead of N tools per skill

### New tools for server.py:
```python
@mcp.tool()
def discover_environment(hosts: list[dict]) -> dict:
    """Scan hosts and auto-identify services. Each host: {address, port?, credential_key?}.
    Returns: identified services, existing skill coverage, and recommendations."""

@mcp.tool()
def skill_execute(name: str, **kwargs) -> dict:
    """Execute a dynamic skill by name. Call skill_search first to discover available skills."""

@mcp.tool()
def validate_skill_live(name: str) -> dict:
    """Test a skill against its actual service. Probes endpoints, checks response shape,
    verifies error handling. Use after skill_create or after service upgrades."""
```

### Key principle changes:
1. **Spec → Code, not Description → Code** (Rule Maker)
2. **Deterministic orchestration, bounded agent execution** (McKinsey)
3. **Progressive disclosure — one dispatcher, not N tools** (Cloudflare/Anthropic)
4. **Three-layer validation: deterministic + live probe + optional critic** (McKinsey)
5. **Environment discovery is a pipeline, not a conversation** (all articles)
