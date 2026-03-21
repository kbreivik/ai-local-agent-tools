# Claude Code: Self-Improving Skill System for HP1-AI-Agent

## Context

This is an existing Python MCP server (`HP1-AI-Agent`) that manages homelab infrastructure via FastMCP.
The server lives in `mcp_server/server.py` and tool modules live in `mcp_server/tools/`.
Every tool returns `{"status": "ok"|"error"|"degraded"|"escalated", "data": ..., "timestamp": ..., "message": ...}`.
All tool functions are **synchronous** (not async). The project uses Python 3.13, FastMCP, Pydantic v2, httpx, paramiko.
Config comes from env vars with fallback to `data/agent_settings.json`.
The project already has a local LLM (LM Studio with Qwen3-Coder-30B on localhost:1234) and an ingest system
(MuninnDB + `ingest_url`/`ingest_pdf` tools) for storing documentation locally.

**DO NOT** change any existing tool files or the existing tool registrations in `server.py`.
**DO** add the new skill system alongside the existing tools, following the same patterns exactly.

---

## Goal

Add a **self-improving skill system** that lets the agent dynamically create new MCP tools at runtime.
The system **MUST work in airgapped environments** with no internet access. Three generation modes:

1. **Local LLM** (primary, airgapped) — uses LM Studio / OpenAI-compatible API on localhost
2. **Sneakernet / Export-Import** — exports a ready-to-paste prompt + ingested docs; operator
   copies it to an internet-connected machine, pastes into any LLM, brings the result back
3. **Cloud API** (optional, when internet available) — Anthropic API as a convenience

The agent should also be able to use **locally ingested documentation** (vendor API docs, man pages,
runbooks already stored in MuninnDB via the existing ingest tools) as context when generating skills.

---

## Architecture — Where Things Go

```
mcp_server/
├── server.py                    # EXISTING — add skill meta-tool registrations at the bottom
├── tools/
│   ├── swarm.py                 # EXISTING — do not touch
│   ├── kafka.py                 # EXISTING — do not touch
│   ├── orchestration.py         # EXISTING — do not touch
│   ├── elastic.py               # EXISTING — do not touch
│   ├── docker_engine.py         # EXISTING — do not touch
│   ├── ingest.py                # EXISTING — do not touch
│   ├── network.py               # EXISTING — do not touch
│   └── skills/                  # NEW — the skill system
│       ├── __init__.py
│       ├── registry.py          # SQLite: skills + service_catalog + breaking_changes tables
│       ├── generator.py         # Multi-backend skill code generation
│       ├── prompt_builder.py    # Builds the generation prompt (shared by all backends)
│       ├── validator.py         # AST validation of generated code
│       ├── knowledge_base.py    # Compat checking, version tracking, changelog analysis
│       ├── doc_retrieval.py     # Multi-strategy doc retrieval for skill generation
│       ├── loader.py            # Hot-load skill modules as MCP tools
│       ├── meta_tools.py        # The meta-tools exposed to the agent
│       └── modules/             # Generated + manual skill .py files
│           ├── __init__.py
│           ├── _template.py     # Template showing the skill module contract
│           ├── proxmox_vm_status.py       # Starter skill
│           ├── fortigate_system_status.py # Starter skill
│           └── http_health_check.py       # Starter skill
data/
├── skills.db                    # SQLite: skill registry + service catalog + breaking changes
├── skill_exports/               # Exported prompts AND knowledge requests for sneakernet
│   └── {name}_{timestamp}.md    # Self-contained prompt/request files
├── skill_imports/               # Drop zone — paste LLM output here as .py files
├── agent_settings.json          # EXISTING — add skill generation config section
```

---

## Skill Module Contract

Every file in `mcp_server/tools/skills/modules/` must follow this exact pattern.
This is critical — the generator, loader, and meta-tools all depend on this contract.

```python
"""<One-line description of what this skill does.>"""
import httpx
from datetime import datetime, timezone


# ── Skill metadata ─────────────────────────────────────────────────────────────
SKILL_META = {
    "name": "service_action_name",          # snake_case, globally unique
    "description": "What this tool does and when to call it. Be specific.",
    "category": "monitoring",               # monitoring | networking | storage | compute | general
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "parameters": {                         # JSON Schema for tool inputs
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target host IP or hostname"},
        },
        "required": ["host"],
    },
    "auth_type": "api_key",                 # none | api_key | token | basic
    "config_keys": ["PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET"],
    "compat": {                             # Compatibility tracking — what this skill was built for
        "service": "proxmox",              # Service identifier (matches service_catalog)
        "api_version_built_for": "8.2",    # API/firmware version used when writing this skill
        "min_version": "8.0",              # Oldest version this skill is known to work with
        "max_version": "",                 # Empty = no known upper bound yet
        "version_endpoint": "/api2/json/version",   # API call to detect running version
        "version_field": "data.version",   # Dot-path to extract version string from response
    },
}


# ── Response helpers (match existing project convention) ───────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


# ── Main execute function ──────────────────────────────────────────────────────
def execute(**kwargs) -> dict:
    """
    Run this skill. Receives kwargs matching the parameters schema.
    MUST return a dict with {status, data, timestamp, message}.
    The returned data dict SHOULD include a "detected_version" field when the
    target service exposes its version — this feeds the compatibility tracker.
    """
    host = kwargs.get("host", "")
    if not host:
        return _err("host is required")
    try:
        # ... do the work ...
        return _ok({"host": host, "result": "...", "detected_version": "8.2.1"}, "Success message")
    except Exception as e:
        return _err(f"skill_name error: {e}")


# ── Optional: compatibility check ─────────────────────────────────────────────
def check_compat(**kwargs) -> dict:
    """
    OPTIONAL. Probe the target service for its version and check against compat bounds.
    If not implemented, the loader skips compat checking for this skill.
    Returns: _ok({"compatible": True/False, "detected_version": "...", "reason": "..."})
    """
    # Default: return unknown if not implemented
    return _ok({"compatible": None, "detected_version": None}, "Compat check not implemented")
```

**Key contract rules:**
- `SKILL_META` dict required at module level — must include `compat` section
- `execute(**kwargs) -> dict` is the entry point — sync, not async
- `execute` SHOULD include `"detected_version"` in return data when the service exposes it
- `check_compat(**kwargs) -> dict` is OPTIONAL — if present, the loader calls it for health checks
- Returns use `_ok/_err/_degraded` matching the rest of the project
- HTTP calls use `httpx` (sync) with explicit timeouts
- SSH calls use `paramiko` following the pattern in `docker_engine.py`
- No imports of subprocess, os.system, eval, exec, __import__, importlib
- `config_keys` lists env vars the skill needs
- `compat.service` must match a `service_catalog` entry (or one will be auto-created)

---

## Components to Build

### 1. `mcp_server/tools/skills/registry.py` — Skill Registry

SQLite database at `data/skills.db`. Standard library `sqlite3` (sync).

**Table: `skills`**

```sql
CREATE TABLE IF NOT EXISTS skills (
    name           TEXT PRIMARY KEY,
    description    TEXT NOT NULL,
    category       TEXT DEFAULT 'general',
    version        TEXT DEFAULT '1.0.0',
    file_path      TEXT NOT NULL,
    auth_type      TEXT DEFAULT 'none',
    config_keys    TEXT DEFAULT '[]',
    parameters     TEXT DEFAULT '{}',
    annotations    TEXT DEFAULT '{}',
    enabled        INTEGER DEFAULT 1,
    auto_generated INTEGER DEFAULT 0,
    generation_mode TEXT DEFAULT 'manual',  -- manual | local_llm | cloud_api | sneakernet
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    call_count     INTEGER DEFAULT 0,
    last_error     TEXT,
    last_called_at TEXT
);
```

**Functions needed:**

```python
def init_db() -> None
def register_skill(meta: dict, file_path: str, auto_generated: bool = False, generation_mode: str = "manual") -> dict
def search_skills(query: str, category: str = "") -> list[dict]
def list_skills(category: str = "", enabled_only: bool = True) -> list[dict]
def get_skill(name: str) -> dict | None
def increment_call(name: str) -> None
def record_error(name: str, error: str) -> None
def disable_skill(name: str) -> dict
def enable_skill(name: str) -> dict
def delete_skill(name: str) -> dict
def list_pending_imports() -> list[dict]   # Check data/skill_imports/ for new .py files
```

Database path: derive project root same way as `docker_engine.py`:
`os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "skills.db")`

### 2. `mcp_server/tools/skills/prompt_builder.py` — Prompt Construction

This module builds the LLM prompt used by ALL generation backends (local, cloud, export).
Separating it ensures the same quality prompt whether used by Qwen3 locally, pasted into
Claude on another machine, or sent to the Anthropic API.

**Functions:**

```python
def build_generation_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list[str] = None,     # Ingested documentation snippets from MuninnDB
    existing_skills: list[str] = None,  # Names of existing skills to avoid duplicates
) -> str:
    """
    Build the full LLM prompt for skill generation.
    Includes: the skill contract template, the request, any relevant docs, and constraints.
    """

def build_export_document(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list[str] = None,
    existing_skills: list[str] = None,
) -> str:
    """
    Build a self-contained markdown document for the sneakernet workflow.
    Includes everything an operator needs: the prompt, instructions for which
    LLM to paste it into, how to save the result, and where to put it.
    """
```

**The generation prompt must include:**

1. The complete `_template.py` content as the contract specification
2. The description of what's needed
3. Category, api_base, auth_type hints
4. Any relevant documentation from MuninnDB (if context_docs provided)
5. List of existing skill names (to avoid naming collisions)
6. Hard constraints:
   - Output ONLY valid Python — no markdown fences, no explanation text before or after
   - The `name` field in SKILL_META must be snake_case, descriptive, unique
   - Use httpx for HTTP calls with explicit timeouts (default 10s)
   - Use paramiko for SSH calls following this pattern: [include SSH snippet from docker_engine.py]
   - Return `_ok/_err/_degraded` dicts exactly as shown in template
   - Include the `_ts`, `_ok`, `_err`, `_degraded` helper functions in every skill
   - NEVER import subprocess, os.system, eval, exec, __import__, importlib, shutil
   - Set `readOnlyHint: True` by default unless the skill explicitly modifies state
   - Handle missing config gracefully — return `_err("CONFIG_KEY not set. Configure via Settings or env var.")`

**The export document must include:**

1. A header: `# Skill Generation Request — HP1-AI-Agent`
2. Instructions: "Paste everything below the --- line into an LLM (Claude, ChatGPT, local model). Copy ONLY the Python code from the response. Save it as `{suggested_name}.py` and place it in `data/skill_imports/` on the agent host."
3. The full generation prompt (from `build_generation_prompt`)
4. A footer: "After placing the .py file in `data/skill_imports/`, run `skill_import()` on the agent or restart the server."

### 3. `mcp_server/tools/skills/validator.py` — Code Validation

Validates generated Python code before it's saved to disk. Used by all generation paths.

```python
def validate_skill_code(code: str) -> dict:
    """
    Validate generated skill code. Returns:
    {"valid": True, "name": str, "meta": dict} on success
    {"valid": False, "error": str} on failure
    """
```

**Validation steps:**
1. `ast.parse(code)` — syntax check
2. Walk AST to find `SKILL_META` assignment — must exist
3. Walk AST to find `execute` FunctionDef — must exist
4. Check for banned imports by walking all `Import` and `ImportFrom` nodes:
   - Banned modules: `subprocess`, `shutil`, `importlib`, `ctypes`, `multiprocessing`
   - Banned names in any import: `system`, `popen`, `exec`, `eval`, `__import__`, `compile`
5. Check for banned function calls by walking `Call` nodes:
   - `os.system`, `os.popen`, `eval(`, `exec(`, `compile(`
   - `open(` with mode `'w'`, `'a'`, `'x'` (generated skills should not write files)
6. Try to extract `name` from SKILL_META using `ast.literal_eval` on the dict — must be snake_case
7. Verify `name` doesn't collide with existing built-in tool names (swarm_status, kafka_broker_status, etc.)

### 4. `mcp_server/tools/skills/generator.py` — Multi-Backend Generation

Three backends, selected by config or explicit parameter.

**Config** (in `data/agent_settings.json` under `"skill_generation"` key, or env vars):

```json
{
  "skill_generation": {
    "backend": "local",
    "local_llm": {
      "base_url": "http://localhost:1234/v1",
      "model": "qwen3-coder-30b-a3b-instruct",
      "api_key": ""
    },
    "cloud_api": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-20250514",
      "api_key": ""
    }
  }
}
```

Env var overrides: `SKILL_GEN_BACKEND` (local|cloud|export), `LM_STUDIO_API_KEY`,
`LM_STUDIO_BASE_URL`, `ANTHROPIC_API_KEY`.

**Functions:**

```python
def generate_skill(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list[str] = None,
    backend: str = "",                  # Override config: "local", "cloud", "export"
) -> dict:
    """
    Generate a skill using the configured backend.
    Returns _ok with {"code": str, "name": str, "meta": dict, "backend_used": str}
    or _err with reason.
    """

def _generate_local(prompt: str) -> str:
    """Call LM Studio / OpenAI-compatible local API. Returns raw code string."""

def _generate_cloud(prompt: str) -> str:
    """Call Anthropic API. Returns raw code string."""

def _generate_export(prompt: str, description: str) -> dict:
    """
    Save the export document to data/skill_exports/{name}_{timestamp}.md.
    Returns _ok with the file path and instructions — does NOT return code.
    The operator handles the rest manually.
    """

def _get_backend_config() -> dict:
    """Load config from agent_settings.json with env var overrides."""

def _fetch_relevant_docs(description: str) -> list[str]:
    """
    Query MuninnDB for documentation relevant to the skill being generated.
    Calls the existing /api/memory/activate endpoint with relevant keywords.
    Returns list of content strings to inject into the prompt as context.
    Falls back to empty list if MuninnDB is unavailable.
    """
```

**`_generate_local` implementation:**
- Uses `httpx` to POST to `{base_url}/chat/completions` (OpenAI-compatible format)
- Same request shape the agent_loop already uses for LM Studio
- Model from config, temperature=0.2 for deterministic output
- System message contains the generation prompt
- User message: "Generate the skill now. Output only Python code."
- Extract content from `response.choices[0].message.content`
- Strip any markdown fences if present (```python ... ```)

**`_generate_cloud` implementation:**
- Uses `anthropic.Anthropic()` sync client
- `messages.create(model=..., max_tokens=4096, messages=[...])`
- Same prompt as local, just different transport
- Only attempted if `ANTHROPIC_API_KEY` is set

**`_generate_export` implementation:**
- Calls `prompt_builder.build_export_document(...)` to build the full markdown document
- Writes it to `data/skill_exports/{suggested_name}_{timestamp}.md`
- Returns `_ok({"export_path": path, "instructions": "..."})` — the agent relays this to the user
- The agent should tell the user: "I've exported a skill generation prompt. Take the file at {path}
  to a machine with internet/LLM access, follow the instructions inside, and place the result in
  data/skill_imports/"

**`_fetch_relevant_docs` — REPLACED by `doc_retrieval.py` module:**

This logic is complex enough to warrant its own module. Instead of a function inside
`generator.py`, create `mcp_server/tools/skills/doc_retrieval.py` using the reference
implementation provided alongside this prompt.

The module provides two public functions:
- `fetch_relevant_docs(description, category, api_base, token_budget)` → structured result
- `format_docs_for_prompt(fetch_result)` → string ready to inject into the LLM prompt

**What it does differently from a naive keyword search:**

1. **Smart keyword extraction** — recognizes ~80 known service names (fortigate, proxmox,
   truenas, etc.), tech keywords (rest, ssh, vlan, ha), API path patterns (`/api/v2/...`),
   and version numbers. Single description → structured `{services, tech, endpoints, versions, raw_terms}`.

2. **Multi-query MuninnDB strategy** — fires 4 cue batches at `/api/memory/activate`:
   - Service-specific: `["fortigate api", "fortigate documentation", "fortigate rest api"]`
   - Endpoint-specific: `["/api/v2/monitor/system/status"]` (highest signal)
   - Task-level combinations: `["fortigate rest", "fortigate ha"]`
   - Broad term groups: `["system status health"]`
   Deduplicates by concept name, keeps highest activation score per engram.

3. **Document type classification** — each engram is classified by its tags and concept name
   into: `api_reference` (priority 1), `config_guide` (2), `changelog` (3), `tutorial` (4),
   `general` (5). API references are what the LLM needs most for skill generation.

4. **Tiered token budgeting** — distributes the token budget (default 3000) by doc type:
   - 45% for API references
   - 20% for config guides
   - 20% for changelogs (important for breaking change context)
   - 10% for tutorials
   - 5% for general
   Truncates at paragraph/sentence boundaries, not mid-word.

5. **Service catalog enrichment** — pulls detected version, API docs version, and unresolved
   breaking changes from the SQLite service catalog. Injected as structured context so the
   LLM knows what version to target and what pitfalls to avoid.

6. **Existing skill awareness** — finds skills already registered for the same service.
   Prevents the generator from creating duplicates and lets it maintain naming consistency.

7. **Local file fallback** — when MuninnDB is unreachable, scans `data/docs/` for files
   whose names match the service keywords. Returns raw content snippets with the same
   budget/truncation logic.

8. **Prompt formatting** — `format_docs_for_prompt()` renders everything into a structured
   string with sections: `## Target Service`, `## Known Breaking Changes`,
   `## Reference Documentation`, `## Existing Skills`. Breaking changes get a bold
   "IMPORTANT: The generated skill MUST account for these" notice.

The generator calls it like:
```python
from mcp_server.tools.skills.doc_retrieval import fetch_relevant_docs, format_docs_for_prompt

result = fetch_relevant_docs(description, category, api_base, token_budget=3000)
docs_context = format_docs_for_prompt(result)
# docs_context is injected into the generation prompt via prompt_builder
```

### 5. `mcp_server/tools/skills/loader.py` — Dynamic Tool Loading

**Functions:**

```python
def load_all_skills(mcp_server: FastMCP) -> dict
def load_single_skill(mcp_server: FastMCP, name: str) -> dict
def scan_imports(mcp_server: FastMCP) -> dict     # Check data/skill_imports/ for new files
```

**`load_all_skills`:** Scan `modules/` dir, load each valid .py, register as MCP tool.

**`load_single_skill`:** Load one skill by filename after generation.

**`scan_imports`:** Check `data/skill_imports/` for .py files (the sneakernet drop zone):
1. For each `.py` file in `data/skill_imports/`:
   - Read and validate with `validator.validate_skill_code()`
   - If valid: move file to `mcp_server/tools/skills/modules/{name}.py`
   - Register as MCP tool via `load_single_skill`
   - Register in SQLite with `generation_mode="sneakernet"`
   - Audit log the import
   - Delete from `skill_imports/` (or move to `skill_imports/processed/`)
2. Return summary of what was imported

**Tool registration pattern:**

```python
def _make_tool_handler(module, skill_name: str):
    def handler(**kwargs) -> dict:
        try:
            registry.increment_call(skill_name)
            return module.execute(**kwargs)
        except Exception as e:
            registry.record_error(skill_name, str(e))
            return {"status": "error", "data": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": f"Skill '{skill_name}' error: {e}"}
    handler.__name__ = skill_name
    handler.__doc__ = module.SKILL_META["description"]
    return handler

# Register:
mcp_server.tool(name=skill_name)(handler)
```

### 6. `mcp_server/tools/skills/meta_tools.py` — Agent-Facing Tools

```python
def skill_search(query: str, category: str = "") -> dict:
    """Search for existing skills by name or description keyword.
    Call this FIRST when you need a capability you don't have built-in."""

def skill_list(category: str = "", enabled_only: bool = True) -> dict:
    """List all registered skills. Categories: monitoring, networking, storage, compute, general."""

def skill_info(name: str) -> dict:
    """Detailed info: description, parameters, call count, last error, config requirements, generation mode."""

def skill_create(
    mcp_server,
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:
    """Generate a new skill. Uses configured backend (default: local LLM).
    Set backend='export' to generate a prompt file for offline/sneakernet use.
    Call skill_search FIRST to avoid duplicates."""

def skill_import(mcp_server) -> dict:
    """Scan data/skill_imports/ for .py files dropped in by the operator (sneakernet workflow).
    Validates, loads, and registers any valid skill files found.
    Call this after the operator places generated code in the imports folder."""

def skill_disable(name: str) -> dict:
    """Disable a broken skill. Stays on disk but won't be called."""

def skill_enable(name: str) -> dict:
    """Re-enable a disabled skill."""

def skill_export_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
) -> dict:
    """Generate and save a skill creation prompt for offline use.
    Use when no local LLM is available or when you want a human to review
    the prompt before generation. Saves to data/skill_exports/.
    Tell the operator to take the file to a machine with LLM access."""

def skill_generation_config() -> dict:
    """Show current skill generation configuration: which backend, model, endpoints.
    Useful for debugging why generation is failing."""
```

**`skill_create` flow:**
1. Call `generator._fetch_relevant_docs(description)` — get MuninnDB context
2. Call `generator.generate_skill(description, category, api_base, auth_type, context_docs, backend)`
3. If backend was "export" — return the export path and instructions, done
4. If generation returned code:
   a. Validate with `validator.validate_skill_code(code)`
   b. If invalid — return `_err` with validation reason
   c. Save to `mcp_server/tools/skills/modules/{name}.py`
   d. Call `loader.load_single_skill(mcp_server, name)`
   e. Call `orchestration.audit_log("skill_create", {...})`
   f. Return `_ok({"name": name, "description": ..., "backend_used": ...})`

### 7. Registration in `server.py` — Skill Tools

Append to `server.py` after ingest tools, before `if __name__ == "__main__":`:

```python
# ── Skill system ──────────────────────────────────────────────────────────────

from mcp_server.tools.skills import meta_tools as skill_tools
from mcp_server.tools.skills import loader as skill_loader
from mcp_server.tools.skills import registry as skill_registry

skill_registry.init_db()
_skill_load_result = skill_loader.load_all_skills(mcp)
# Also pick up any files in the imports drop zone on startup
_skill_import_result = skill_loader.scan_imports(mcp)

@mcp.tool()
def skill_search(query: str, category: str = "") -> dict:
    """Search for dynamic skills by keyword. Call this when you need a capability
    not in the built-in tools (swarm, kafka, elastic, docker_engine, etc.)."""
    return skill_tools.skill_search(query, category)

@mcp.tool()
def skill_list(category: str = "", enabled_only: bool = True) -> dict:
    """List all dynamic skills. Categories: monitoring, networking, storage, compute, general."""
    return skill_tools.skill_list(category, enabled_only)

@mcp.tool()
def skill_info(name: str) -> dict:
    """Get details about a dynamic skill: parameters, call count, errors, generation mode."""
    return skill_tools.skill_info(name)

@mcp.tool()
def skill_create(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:
    """Generate a new tool when no existing skill fits. Call skill_search FIRST.
    backend='local' (default) uses LM Studio. backend='cloud' uses Anthropic API.
    backend='export' saves a prompt file for offline generation (airgapped workflow).
    The description should name the service, API, and what data to return."""
    return skill_tools.skill_create(mcp, description, category, api_base, auth_type, backend)

@mcp.tool()
def skill_import() -> dict:
    """Scan data/skill_imports/ for .py skill files (sneakernet/offline workflow).
    Validates and loads any valid skills found. Call after operator drops files there."""
    return skill_tools.skill_import(mcp)

@mcp.tool()
def skill_export_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
) -> dict:
    """Save a self-contained skill generation prompt to data/skill_exports/.
    Use for airgapped environments. The export file contains full instructions
    for the operator to generate the skill on another machine."""
    return skill_tools.skill_export_prompt(description, category, api_base, auth_type)

@mcp.tool()
def skill_disable(name: str) -> dict:
    """Disable a broken dynamic skill."""
    return skill_tools.skill_disable(name)

@mcp.tool()
def skill_enable(name: str) -> dict:
    """Re-enable a disabled dynamic skill."""
    return skill_tools.skill_enable(name)

@mcp.tool()
def skill_generation_config() -> dict:
    """Show current skill generation config: backend, model, LM Studio URL."""
    return skill_tools.skill_generation_config()
```

### 8. Additional Tables in `registry.py` — Service Catalog & Breaking Changes

These tables live in the same `data/skills.db` database, created by `init_db()`.

**Table: `service_catalog`** — tracks every service the agent knows about

```sql
CREATE TABLE IF NOT EXISTS service_catalog (
    service_id         TEXT PRIMARY KEY,  -- "fortigate", "proxmox", "truenas", "docker"
    display_name       TEXT NOT NULL,     -- "FortiGate Firewall"
    service_type       TEXT DEFAULT '',   -- "firewall", "hypervisor", "nas", "switch", "container"
    detected_version   TEXT DEFAULT '',   -- Last version seen from a live skill call
    known_latest       TEXT DEFAULT '',   -- Latest version from ingested docs/changelogs
    version_source     TEXT DEFAULT '',   -- How we know: "skill_probe", "manual", "changelog_ingest"
    api_docs_ingested  INTEGER DEFAULT 0, -- 1 if vendor docs have been ingested into MuninnDB
    api_docs_version   TEXT DEFAULT '',   -- Version the ingested docs cover (e.g., "7.4.4")
    changelog_ingested INTEGER DEFAULT 0, -- 1 if changelog/release notes have been ingested
    last_checked       TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    notes              TEXT DEFAULT ''
);
```

**Table: `breaking_changes`** — known incompatibilities between versions

```sql
CREATE TABLE IF NOT EXISTS breaking_changes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id          TEXT NOT NULL,     -- FK to service_catalog
    from_version        TEXT DEFAULT '',   -- Version range start (empty = all prior)
    to_version          TEXT NOT NULL,     -- Version that introduced the break
    severity            TEXT DEFAULT 'warning',  -- info | warning | breaking
    description         TEXT NOT NULL,     -- Human-readable: "Endpoint /api/v2/foo removed"
    affected_endpoints  TEXT DEFAULT '[]', -- JSON array of affected API paths/commands
    affected_skills     TEXT DEFAULT '[]', -- JSON array of skill names potentially affected
    remediation         TEXT DEFAULT '',   -- "Use /api/v2/bar instead" or "Regenerate skill"
    source              TEXT DEFAULT '',   -- "changelog", "manual", "error_detection", "llm_analysis"
    muninndb_ref        TEXT DEFAULT '',   -- Engram ID linking to the source document
    created_at          TEXT NOT NULL,
    resolved            INTEGER DEFAULT 0  -- 1 if skills have been updated for this change
);
```

**Table: `skill_compat_log`** — history of compatibility checks

```sql
CREATE TABLE IF NOT EXISTS skill_compat_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name       TEXT NOT NULL,
    service_id       TEXT NOT NULL,
    detected_version TEXT,
    built_for_version TEXT,
    compatible       INTEGER,            -- 1=yes, 0=no, NULL=unknown
    check_method     TEXT DEFAULT '',     -- "version_probe", "error_pattern", "manual"
    details          TEXT DEFAULT '',
    checked_at       TEXT NOT NULL
);
```

**Additional registry functions:**

```python
# Service catalog
def upsert_service(service_id: str, display_name: str, service_type: str = "", **kwargs) -> dict
def get_service(service_id: str) -> dict | None
def list_services() -> list[dict]
def update_service_version(service_id: str, version: str, source: str = "skill_probe") -> dict

# Breaking changes
def add_breaking_change(service_id: str, to_version: str, description: str, **kwargs) -> dict
def get_breaking_changes(service_id: str, from_version: str = "", to_version: str = "") -> list[dict]
def get_unresolved_breaking_changes() -> list[dict]
def resolve_breaking_change(change_id: int) -> dict

# Compat log
def log_compat_check(skill_name: str, service_id: str, detected_version: str, compatible: bool | None, **kwargs) -> None
def get_compat_history(skill_name: str, limit: int = 10) -> list[dict]
```

### 9. `mcp_server/tools/skills/knowledge_base.py` — Knowledge & Compatibility Layer

This is NOT a tool module — it's internal logic used by the loader, meta-tools, and the
compatibility checking system. It ties together the service catalog, breaking changes,
MuninnDB documentation, and skill compatibility.

```python
def detect_version_from_skill_result(skill_name: str, result: dict) -> str | None:
    """
    After a skill executes, extract the detected_version from its result.
    Updates the service_catalog with the detected version.
    Called automatically by the loader's tool wrapper after every skill execution.
    """

def check_skill_compatibility(skill_name: str) -> dict:
    """
    Check if a skill is compatible with the currently detected service version.
    
    Steps:
    1. Load skill's SKILL_META.compat section
    2. Get detected_version from service_catalog (from last skill execution)
    3. If skill has check_compat() function, call it
    4. Compare detected version against min_version/max_version bounds
    5. Check breaking_changes table for any unresolved changes between
       compat.api_version_built_for and detected_version
    6. Log the result to skill_compat_log
    7. Return: {compatible, detected_version, built_for, warnings, breaking_changes}
    """

def check_all_skills_compatibility() -> dict:
    """Run check_skill_compatibility for all enabled skills. Return summary."""

def analyze_skill_errors_for_compat(skill_name: str, error: str) -> dict | None:
    """
    Called when a skill returns _err(). Looks for patterns that suggest
    version incompatibility:
    - HTTP 404 (endpoint removed)
    - HTTP 400 with "unknown parameter" or "deprecated"
    - Connection refused on expected port (service moved)
    - JSON decode errors (response format changed)
    - SSH command not found (CLI changed between versions)
    
    If a pattern matches, auto-creates a breaking_change entry with
    source="error_detection" and returns it. Returns None if error
    looks unrelated to compatibility.
    """

def parse_changelog_for_breaking_changes(
    service_id: str,
    content: str,
    from_version: str = "",
    to_version: str = "",
) -> dict:
    """
    Parse changelog/release notes text to extract breaking changes.
    
    Uses the local LLM (or returns a structured prompt for sneakernet)
    to analyze the content and extract:
    - Removed/changed API endpoints
    - Deprecated CLI commands
    - Changed default behaviors
    - New required parameters
    - Authentication changes
    
    Stores results in the breaking_changes table.
    Also cross-references affected_endpoints with existing skills to
    populate the affected_skills field.
    
    For airgapped without local LLM: returns the content + prompt as an
    exportable document (same as skill_export but for changelog analysis).
    """

def get_skill_health_summary() -> dict:
    """
    High-level dashboard data:
    - Total skills, enabled/disabled count
    - Skills by compat status: compatible / warning / incompatible / unknown
    - Services with version mismatches
    - Unresolved breaking changes
    - Skills that haven't been compat-checked in >30 days
    - Skills with high error rates (last_error set, call_count > 0)
    """

def recommend_skill_updates(service_id: str = "") -> dict:
    """
    Based on breaking_changes and compat checks, return a prioritized list
    of skills that need regeneration or manual updates.
    For each skill, includes:
    - Why it needs updating (which breaking change, which error pattern)
    - The old version it was built for vs current version
    - Relevant documentation snippets from MuninnDB
    - Whether it can be auto-regenerated or needs manual review
    """
```

### 10. Updated Loader — Version Tracking on Every Call

The tool wrapper in `loader.py` must be updated to feed the knowledge base:

```python
def _make_tool_handler(module, skill_name: str):
    def handler(**kwargs) -> dict:
        try:
            registry.increment_call(skill_name)
            result = module.execute(**kwargs)
            
            # ── Feed version detection ──
            # If the skill result includes a detected_version, update service catalog
            if result.get("status") == "ok" and result.get("data"):
                detected = result["data"].get("detected_version")
                if detected and hasattr(module, "SKILL_META"):
                    compat = module.SKILL_META.get("compat", {})
                    service_id = compat.get("service")
                    if service_id:
                        knowledge_base.detect_version_from_skill_result(skill_name, result)
            
            # ── Detect compat-related errors ──
            if result.get("status") == "error":
                registry.record_error(skill_name, result.get("message", ""))
                compat_issue = knowledge_base.analyze_skill_errors_for_compat(
                    skill_name, result.get("message", ""))
                if compat_issue:
                    result["data"] = result.get("data") or {}
                    result["data"]["compat_warning"] = compat_issue
                    result["message"] += (
                        f" [COMPAT WARNING: This may be caused by a version change in "
                        f"{compat_issue.get('service_id', 'the service')}. "
                        f"Run skill_compat_check('{skill_name}') for details.]"
                    )
            
            return result
        except Exception as e:
            registry.record_error(skill_name, str(e))
            return {"status": "error", "data": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": f"Skill '{skill_name}' error: {e}"}
    handler.__name__ = skill_name
    handler.__doc__ = module.SKILL_META["description"]
    return handler
```

### 11. Knowledge Meta-Tools — Added to `meta_tools.py`

These tools let the agent (and operator) manage service knowledge:

```python
# ── Service catalog tools ─────────────────────────────────────────────────────

def service_catalog_list() -> dict:
    """List all known services with their detected versions and doc status.
    Shows which services have API docs ingested, changelog coverage, and
    version mismatches between skill expectations and reality."""

def service_catalog_update(
    service_id: str,
    detected_version: str = "",
    known_latest: str = "",
    notes: str = "",
) -> dict:
    """Manually update a service's version info. Use after firmware upgrades
    or when you know the running version. This helps the compat checker
    flag skills that may need updating."""

# ── Compatibility tools ───────────────────────────────────────────────────────

def skill_compat_check(name: str) -> dict:
    """Check if a specific skill is compatible with the detected service version.
    Compares SKILL_META.compat bounds against reality. Reports any known
    breaking changes between the built-for version and detected version.
    Calls the skill's check_compat() function if it has one."""

def skill_compat_check_all() -> dict:
    """Run compat check on all enabled skills. Returns summary:
    which are compatible, which have warnings, which are broken.
    Use after firmware upgrades or periodically for health checks."""

def skill_health_summary() -> dict:
    """Dashboard view: all skills with compat status, error rates,
    stale checks, and recommended actions. Call this for a full picture
    of skill system health."""

# ── Knowledge gathering tools ─────────────────────────────────────────────────

def knowledge_ingest_changelog(
    service_id: str,
    content: str = "",
    from_version: str = "",
    to_version: str = "",
) -> dict:
    """Parse changelog/release notes to extract breaking changes.
    Provide content directly (paste from clipboard) or leave empty to use
    the most recently ingested document for this service from MuninnDB.
    
    Extracts: removed endpoints, changed parameters, deprecated commands,
    auth changes. Cross-references with existing skills to flag affected ones.
    
    In airgapped mode with no local LLM: returns an export prompt the
    operator can take to an external LLM for analysis."""

def knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """Generate a knowledge gathering request for the sneakernet workflow.
    
    request_type options:
    - 'changelog': "We need the changelog for {service} from v{current} to v{latest}"
    - 'api_docs': "We need the REST API reference for {service} v{version}"  
    - 'upgrade_guide': "We need the upgrade guide from v{current} to v{target}"
    
    Saves a .md file to data/skill_exports/ with:
    - What document to find (with URLs if known for common vendors)
    - Why it's needed (which skills are affected)
    - How to bring it back (ingest_pdf or paste into data/skill_imports/)
    
    Common vendor doc URLs are hardcoded for:
    - Fortinet (docs.fortinet.com)
    - Proxmox (pve.proxmox.com/wiki)
    - TrueNAS (truenas.com/docs)
    - Docker (docs.docker.com)
    """

def skill_recommend_updates(service_id: str = "") -> dict:
    """Based on breaking changes and compat results, return prioritized list
    of skills needing regeneration. For each: what broke, relevant docs,
    and whether auto-regeneration is possible or manual review needed."""

def skill_regenerate(name: str, backend: str = "") -> dict:
    """Regenerate an existing skill using current knowledge.
    Reads the original SKILL_META + any new breaking change info + updated
    docs from MuninnDB, then runs skill_create with enriched context.
    The old skill file is backed up to modules/{name}.py.bak before overwriting.
    Updates the compat.api_version_built_for to the current detected version."""
```

### 12. Registration in `server.py` — Knowledge Tools

Add alongside the other skill tools in the registration block:

```python
# ── Knowledge & compatibility tools ───────────────────────────────────────────

@mcp.tool()
def service_catalog_list() -> dict:
    """List all known infrastructure services with detected versions and doc coverage."""
    return skill_tools.service_catalog_list()

@mcp.tool()
def service_catalog_update(service_id: str, detected_version: str = "", known_latest: str = "", notes: str = "") -> dict:
    """Update a service's version info. Use after firmware upgrades."""
    return skill_tools.service_catalog_update(service_id, detected_version, known_latest, notes)

@mcp.tool()
def skill_compat_check(name: str) -> dict:
    """Check if a skill is compatible with the current service version."""
    return skill_tools.skill_compat_check(name)

@mcp.tool()
def skill_compat_check_all() -> dict:
    """Compat check all enabled skills. Use after any infrastructure upgrade."""
    return skill_tools.skill_compat_check_all()

@mcp.tool()
def skill_health_summary() -> dict:
    """Full skill system health: compat status, error rates, stale checks, actions needed."""
    return skill_tools.skill_health_summary()

@mcp.tool()
def knowledge_ingest_changelog(service_id: str, content: str = "", from_version: str = "", to_version: str = "") -> dict:
    """Parse changelog/release notes to find breaking changes affecting skills."""
    return skill_tools.knowledge_ingest_changelog(service_id, content, from_version, to_version)

@mcp.tool()
def knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """Export a 'go fetch this document' request for airgapped environments.
    Tells the operator exactly which docs to get and where to find them."""
    return skill_tools.knowledge_export_request(service_id, request_type)

@mcp.tool()
def skill_recommend_updates(service_id: str = "") -> dict:
    """List skills that need updating based on breaking changes and version drift."""
    return skill_tools.skill_recommend_updates(service_id)

@mcp.tool()
def skill_regenerate(name: str, backend: str = "") -> dict:
    """Regenerate a skill with current docs and version info. Backs up the old version."""
    return skill_tools.skill_regenerate(mcp, name, backend)
```

---

## Breaking Changes — Detection Methods

The system detects breaking changes through FOUR channels. None require internet.

### Channel 1: Error Pattern Detection (automatic, passive)
Every time a skill returns `_err()`, the loader's wrapper calls
`knowledge_base.analyze_skill_errors_for_compat()`. Pattern matching:

| Error Pattern | Likely Cause | Auto-Action |
|---|---|---|
| HTTP 404 | Endpoint removed/moved | Create breaking_change, flag skill |
| HTTP 400 + "deprecated" | Parameter deprecated | Create breaking_change, warn |
| HTTP 400 + "unknown parameter" | Parameter removed in new version | Create breaking_change, flag skill |
| HTTP 401/403 after working | Auth scheme changed | Create breaking_change, flag skill |
| JSON decode error | Response format changed | Create breaking_change, flag skill |
| SSH "command not found" | CLI changed between versions | Create breaking_change, flag skill |
| Connection refused | Service port changed | Warn, don't auto-flag |

### Channel 2: Version Drift Detection (automatic, passive)
Every time a skill executes successfully and returns `detected_version` in its data:
1. Update `service_catalog.detected_version`
2. Compare against `SKILL_META.compat.api_version_built_for`
3. If major version differs → flag as `warning`
4. If detected > max_version → flag as `potentially_incompatible`
5. Log to `skill_compat_log`

### Channel 3: Changelog Ingestion (manual, operator-triggered)
Operator ingests release notes / changelogs via:
- `ingest_pdf("fortigate-7.6-release-notes.pdf")` (existing tool)
- `ingest_url("https://docs.fortinet.com/...")` (existing tool, if internet available)
- Then: `knowledge_ingest_changelog("fortigate", from_version="7.4", to_version="7.6")`
- The knowledge base extracts breaking changes from MuninnDB engrams using the local LLM
- Or exports a prompt for sneakernet changelog analysis

### Channel 4: Manual / Operator Entry
Operator tells the agent directly:
- `service_catalog_update("fortigate", detected_version="7.6.0")`
- Or via the GUI settings

---

## Information Gathering — Airgapped Workflow

The key insight: **information gathering is a sneakernet loop, just like skill generation.**
The agent knows what it NEEDS but can't GET it. So it exports structured requests.

### Scenario: FortiGate firmware upgrade 7.4 → 7.6

```
1. Operator tells agent: "I'm upgrading the FortiGate from 7.4.4 to 7.6.0"

2. Agent calls: service_catalog_update("fortigate", detected_version="7.4.4", known_latest="7.6.0")

3. Agent calls: skill_compat_check_all()
   → "2 skills built for FortiGate 7.4.x: fortigate_system_status, fortigate_ha_status"

4. Agent calls: knowledge_export_request("fortigate", request_type="changelog")
   → Saves data/skill_exports/fortigate_knowledge_request_20260318.md:

   ┌──────────────────────────────────────────────────────────────────────┐
   │ # Knowledge Request — FortiGate Changelog                          │
   │                                                                     │
   │ ## What We Need                                                     │
   │ Release notes / changelog for FortiOS 7.4.4 → 7.6.0               │
   │ Focus on: REST API changes, deprecated endpoints, new parameters    │
   │                                                                     │
   │ ## Where to Find It                                                 │
   │ - https://docs.fortinet.com/document/fortigate/7.6.0/             │
   │   fortios-release-notes/                                            │
   │ - Fortinet support portal → FortiOS 7.6 Release Notes PDF          │
   │                                                                     │
   │ ## Why We Need It                                                   │
   │ These skills may be affected:                                       │
   │ - fortigate_system_status (uses /api/v2/monitor/system/status)     │
   │ - fortigate_ha_status (uses /api/v2/monitor/system/ha-peer)        │
   │                                                                     │
   │ ## How to Bring It Back                                             │
   │ Option A: Download the PDF, copy to agent host,                    │
   │           run: ingest_pdf("fortios-7.6-release-notes.pdf")         │
   │ Option B: Copy the relevant changelog text into a .txt file,       │
   │           place in data/docs/, run: ingest_pdf("changelog.txt")    │
   │ Then tell the agent: "Analyze the FortiGate changelog"             │
   └──────────────────────────────────────────────────────────────────────┘

5. Operator fetches docs on internet machine, transfers back, ingests

6. Agent calls: knowledge_ingest_changelog("fortigate", from_version="7.4", to_version="7.6")
   → Local LLM analyzes ingested docs, extracts:
     - "/api/v2/monitor/system/ha-peer renamed to /api/v2/monitor/system/ha/peer"
     - "New required header: X-CSRF-Token on all POST requests"
   → Stores in breaking_changes table
   → Cross-references: fortigate_ha_status uses affected endpoint

7. Agent calls: skill_recommend_updates("fortigate")
   → "fortigate_ha_status: NEEDS UPDATE — endpoint renamed. Can auto-regenerate."
   → "fortigate_system_status: COMPATIBLE — no breaking changes found."

8. Agent calls: skill_regenerate("fortigate_ha_status")
   → Regenerates using updated docs + breaking change context
   → Old version backed up to modules/fortigate_ha_status.py.bak
   → New version targets 7.6.0
```

### Scenario: New service discovered, no docs available

```
1. Agent: "I need to monitor the Synology NAS but I have no tools or docs for it"

2. Agent calls: skill_search("synology") → no results
   Agent calls: service_catalog_list() → no synology entry

3. Agent calls: knowledge_export_request("synology", request_type="api_docs")
   → Saves request file:
   "We need: Synology DSM API documentation (REST API reference).
    Likely URL: https://global.synologydownload.com/download/Document/Software/DeveloperGuide/
    Focus on: system info, storage pool status, disk health endpoints.
    How to bring back: download PDF or HTML, transfer to agent, ingest."

4. Operator fetches docs, ingests them

5. Agent calls: skill_create(
       description="Check Synology NAS storage pool health via DSM REST API",
       category="storage",
       api_base="https://{host}:5001/webapi",
       auth_type="token"
   )
   → Generator pulls ingested Synology docs from MuninnDB as context
   → Local LLM generates the skill with correct API calls
```

---

## Known Vendor Documentation URLs

Hardcode these in `knowledge_export_request()` for common homelab services.
The export file includes them so the operator knows exactly where to go.

```python
VENDOR_DOCS = {
    "fortigate": {
        "changelog": "https://docs.fortinet.com/document/fortigate/{version}/fortios-release-notes/",
        "api_docs": "https://fndn.fortinet.net/index.php?/fortiapi/",
        "upgrade_guide": "https://docs.fortinet.com/document/fortigate/{version}/upgrade-guide/",
    },
    "fortiswitch": {
        "changelog": "https://docs.fortinet.com/document/fortiswitch/{version}/fortiswitchos-release-notes/",
        "api_docs": "https://docs.fortinet.com/document/fortiswitch/{version}/administration-guide/",
    },
    "proxmox": {
        "changelog": "https://pve.proxmox.com/wiki/Roadmap",
        "api_docs": "https://pve.proxmox.com/pve-docs/api-viewer/",
        "upgrade_guide": "https://pve.proxmox.com/wiki/Upgrade_from_{from_version}_to_{to_version}",
    },
    "truenas": {
        "api_docs": "https://www.truenas.com/docs/api/scale_rest_api.html",
        "changelog": "https://www.truenas.com/docs/scale/scalereleasenotes/",
    },
    "docker": {
        "changelog": "https://docs.docker.com/engine/release-notes/",
        "api_docs": "https://docs.docker.com/engine/api/v{version}/",
    },
    "elasticsearch": {
        "changelog": "https://www.elastic.co/guide/en/elasticsearch/reference/current/release-notes.html",
        "api_docs": "https://www.elastic.co/guide/en/elasticsearch/reference/current/rest-apis.html",
    },
}
```

This is the critical airgapped flow. It must be simple enough for an operator
who doesn't know Python.

### Step 1: Agent needs a new capability
```
Agent: "I need to check TrueNAS pool health but I don't have a tool for that."
Agent calls: skill_search("truenas") → no results
Agent calls: skill_create(description="Check TrueNAS pool health via REST API...", backend="export")
```

### Step 2: Export file created
```
Agent returns: "I've created a skill generation prompt at data/skill_exports/truenas_pool_health_20260318.md.
Take this file to a machine with internet access and follow the instructions inside."
```

### Step 3: Export file contents (what the operator sees)
```markdown
# Skill Generation Request — HP1-AI-Agent
Generated: 2026-03-18T14:30:00Z

## Instructions
1. Copy everything below the "---" line
2. Paste it into an LLM (Claude, ChatGPT, or any capable model)
3. Copy ONLY the Python code from the response (no markdown, no explanation)
4. Save it as a .py file (any name is fine)
5. Place the .py file in data/skill_imports/ on the agent host
6. The agent will pick it up automatically on next startup,
   or call skill_import() to load it immediately

## Reference Documentation
If you have access to the TrueNAS API documentation, providing it alongside
this prompt will significantly improve the generated skill quality.
Key docs: https://www.truenas.com/docs/api/scale_rest_api.html

---

<the full generation prompt with template, constraints, and any MuninnDB context>
```

### Step 4: Operator pastes into LLM, gets code, saves to `data/skill_imports/truenas_pool_health.py`

### Step 5: Agent loads it
```
Agent calls: skill_import()
→ "Imported 1 skill: truenas_pool_health (validated, loaded, ready to use)"
Agent calls: truenas_pool_health(host="192.168.1.50")
→ {status: "ok", data: {pools: [...]}, ...}
```

---

## Documentation-Assisted Generation

This is handled by `doc_retrieval.py` (reference implementation provided as a separate file).
When generating skills via any backend, `generator.py` calls:

```python
from mcp_server.tools.skills.doc_retrieval import fetch_relevant_docs, format_docs_for_prompt

result = fetch_relevant_docs(description, category, api_base, token_budget=3000)
docs_context = format_docs_for_prompt(result)
# docs_context string is passed to prompt_builder.build_generation_prompt(context_docs=docs_context)
```

The doc_retrieval module does multi-strategy MuninnDB querying, doc-type classification,
tiered token budgeting, service catalog enrichment, and local file fallback — all described
in detail in the `_fetch_relevant_docs` section above and in the reference implementation.

**The recommended workflow for airgapped environments is:**
1. On internet-connected machine: download vendor API docs (HTML/PDF)
2. Transfer to agent host (USB, network share, etc.)
3. Ingest: `ingest_url("file:///path/to/doc")` or `ingest_pdf("truenas-api-ref.pdf")`
4. Now `skill_create` has access to those docs even without internet
5. The local LLM generates better skills because it has the actual API reference
6. Breaking changes from changelogs are also surfaced as warnings in the generation prompt

---

## Starter Skills to Create

### `proxmox_vm_status.py`
- Uses `proxmoxer` library (already in requirements.txt)
- Config keys: `PROXMOX_HOST`, `PROXMOX_USER`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET`
- Also reads from `agent_settings.json` under `"proxmox"` key (same pattern as docker_engine.py)
- Connects: `ProxmoxAPI(host, user=user, token_name=token_id, token_value=token_secret, verify_ssl=False)`
- Params: `node` (required, str) — the Proxmox node name
- Returns: list of VMs with vmid, name, status, cpu, mem, uptime
- **Include `detected_version`** in return data — get from `proxmox.version.get()`
- `_degraded` if any VM is stopped, `_ok` if all running
- **compat section**: `service: "proxmox"`, `api_version_built_for: "8.2"`, `version_endpoint: "/api2/json/version"`, `version_field: "data.version"`
- **Implement `check_compat()`**: calls `/api2/json/version`, compares against bounds

### `fortigate_system_status.py`
- Uses httpx to call FortiGate REST API
- Config keys: `FORTIGATE_HOST`, `FORTIGATE_API_KEY`
- Endpoint: `GET https://{host}/api/v2/monitor/system/status?access_token={api_key}`
- `verify=False` for self-signed certs
- Returns: hostname, serial, firmware, uptime, HA status
- **Include `detected_version`** in return data — extract from `results.version` in response
- `_degraded` if HA is not synced or firmware is old
- **compat section**: `service: "fortigate"`, `api_version_built_for: "7.4"`, `version_endpoint: "/api/v2/monitor/system/status"`, `version_field: "results.version"`
- **Implement `check_compat()`**: calls status endpoint, extracts firmware version

### `http_health_check.py`
- Simple HTTP GET to any URL with timing
- Params: `url` (required), `timeout` (optional, default 10)
- Returns: status_code, response_time_ms, content_length
- `_ok` for 2xx, `_degraded` for 3xx/4xx, `_err` for 5xx or timeout
- No config keys needed
- **compat section**: `service: "generic"`, `api_version_built_for: ""` (version-agnostic)
- No `check_compat()` needed — works with any HTTP service

---

## Settings Schema Addition

Add to the `agent_settings.json` schema (alongside existing `docker_engine` key):

```json
{
  "docker_engine": { "...existing..." },
  "skill_generation": {
    "backend": "local",
    "local_llm": {
      "base_url": "http://localhost:1234/v1",
      "model": "",
      "api_key": ""
    },
    "cloud_api": {
      "provider": "anthropic",
      "model": "claude-sonnet-4-20250514",
      "api_key": ""
    }
  },
  "proxmox": {
    "host": "",
    "user": "root@pam",
    "token_id": "",
    "token_secret": ""
  },
  "fortigate": {
    "host": "",
    "api_key": ""
  }
}
```

The `local_llm.model` field can be left empty — the generator should then call
`GET {base_url}/models` and pick the first loaded model (same behavior as the existing agent loop).

---

## Requirements Addition

Add to `requirements.txt`:
```
anthropic>=0.50.0
```

This is optional — the system works without it when using local LLM or export mode.
The `generator.py` should catch `ImportError` on `import anthropic` and return a clear error
if cloud backend is requested but the package isn't installed.

---

## Implementation Order

1. `mcp_server/tools/skills/__init__.py` (empty)
2. `mcp_server/tools/skills/modules/__init__.py` (empty)
3. `mcp_server/tools/skills/modules/_template.py` — the contract template (with compat section)
4. `mcp_server/tools/skills/validator.py` — code validation (no dependencies on other new files)
5. `mcp_server/tools/skills/registry.py` — all 3 tables (skills, service_catalog, breaking_changes, skill_compat_log)
   Test: `python -c "from mcp_server.tools.skills.registry import init_db; init_db()"`
6. `mcp_server/tools/skills/knowledge_base.py` — compat checking, version tracking, changelog parsing
7. `mcp_server/tools/skills/doc_retrieval.py` — use the reference implementation provided (doc_retrieval.py)
8. `mcp_server/tools/skills/prompt_builder.py` — prompt construction (calls doc_retrieval for context)
9. `mcp_server/tools/skills/generator.py` — multi-backend generation
10. `mcp_server/tools/skills/loader.py` — dynamic loading + imports scan + version-tracking wrapper
11. `mcp_server/tools/skills/meta_tools.py` — ALL meta-tools (skill + knowledge + compat)
12. Three starter skills in `modules/` (with compat sections filled in)
13. Append all tool registrations to `server.py` (skill tools + knowledge tools)
14. Create `data/skill_exports/` and `data/skill_imports/` directories (with `.gitkeep`)
15. Test: `python mcp_server/server.py` starts clean with starter skills + service catalog seeded

---

## Testing Checklist

### Skill System Basics
1. `python -c "from mcp_server.tools.skills.registry import init_db; init_db(); print('DB OK')"` — creates all tables
2. `python mcp_server/server.py` — starts without errors, logs 3 starter skills loaded
3. `skill_list()` returns the 3 starter skills with compat metadata
4. `skill_search("proxmox")` finds `proxmox_vm_status`
5. `skill_info("proxmox_vm_status")` shows parameters, config_keys, compat section, call_count=0
6. `skill_generation_config()` shows current backend and LM Studio URL

### Generation & Import
7. **Local LLM test**: `skill_create("Check ping latency to a host", backend="local")` generates valid code
8. **Export test**: `skill_create("Check TrueNAS pool health", backend="export")` creates .md in `data/skill_exports/`
9. **Export file** has clear instructions and (if available) vendor doc URLs
10. **Import test**: place valid skill .py in `data/skill_imports/`, call `skill_import()` → loads it
11. **Validation test**: .py with `import subprocess` in imports → rejected with clear error
12. `skill_disable / skill_enable` cycle works

### Knowledge & Compatibility
13. `service_catalog_list()` shows services seeded from starter skills (proxmox, fortigate)
14. `service_catalog_update("fortigate", detected_version="7.6.0")` updates the catalog
15. `skill_compat_check("fortigate_system_status")` detects version drift (built for 7.4, now 7.6)
16. `skill_compat_check_all()` returns summary for all skills
17. `skill_health_summary()` returns dashboard data with compat status
18. `knowledge_export_request("fortigate", "changelog")` creates .md with correct Fortinet doc URLs
19. **Error-based detection**: a skill returning HTTP 404 → auto-creates a breaking_change entry
20. `skill_recommend_updates("fortigate")` lists affected skills after a breaking change is added
21. `skill_regenerate("fortigate_system_status")` backs up old file and creates new version

### Integration
22. All operations produce `audit_log` entries in `logs/audit.log`
23. No existing tests break: `python -m pytest tests/ -v --tb=short`
24. **Cloud test** (optional): `skill_create("...", backend="cloud")` works with ANTHROPIC_API_KEY

---

## Critical Constraints

- **Airgapped-first** — the system must be fully functional with zero internet. Local LLM is the primary backend. Cloud API is optional convenience. Knowledge gathering uses the sneakernet export/import pattern.
- **Match existing patterns exactly** — `_ok/_err/_degraded`, sync functions, env var + settings.json config
- **No changes to existing files** except appending to `server.py`
- **No async** — entire project is synchronous
- **No eval/exec** — use `importlib.util` for loading generated skill modules
- **Audit everything** — skill_create, skill_import, skill_disable, compat checks, breaking changes → `orchestration.audit_log()`
- **Generated skills default to readOnlyHint: True**
- **Generated skills MUST include a compat section** in SKILL_META — the generator prompt enforces this
- **Skills SHOULD return `detected_version`** in their data when the target service exposes a version — this feeds the compat tracker passively
- **Fail gracefully** — missing API key, offline LLM, no MuninnDB → clear `_err()` messages, never crash
- **Human-readable** — generated skills, export files, and knowledge requests should be clean enough for a homelab operator to read and act on
- **No new dependencies** beyond optional `anthropic` — use httpx, paramiko, sqlite3 (all already available)
- **Sneakernet must be dead simple** — export files contain everything needed (what to fetch, where to find it, how to bring it back)
- **Version tracking is passive** — the system learns service versions from normal skill execution, not from dedicated polling. No cron jobs, no background threads.
- **Breaking change detection is defensive** — when uncertain, warn rather than auto-disable. The agent or operator decides what to do.
