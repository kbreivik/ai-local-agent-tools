"""Skill spec generator — produces SKILL_SPEC before code generation.

Phase 1 of spec-first skill creation:
  description → LLM → SKILL_SPEC → validate → (pass to code generator)

SKILL_SPEC is a small structured dict that captures the API contract:
endpoints, auth, expected fields, error conditions. The LLM generates this
from the description. The spec is then validated against the live service
BEFORE code generation — so the code generator has verified facts, not guesses.
"""
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SKILL_SPEC_SCHEMA = {
    "name":        str,    # snake_case tool name
    "service":     str,    # platform (fortigate, truenas, unifi, etc.)
    "description": str,    # one-sentence description
    "endpoints": [         # list of API endpoints the skill calls
        {
            "method":           str,   # GET, POST, etc.
            "path":             str,   # /api/v2/monitor/system/status
            "auth":             str,   # apikey_query | bearer | basic | pve_token | none
            "expected_status":  int,   # 200
            "response_fields": [str],  # ["serial", "version", "status"]
        }
    ],
    "parameters": dict,    # JSONSchema parameters block
    "health_rules": {
        "ok":      str,    # condition for green
        "degraded": str,   # condition for amber
        "error":   str,    # condition for red
    },
    "config_keys": [str],  # env var names needed (e.g. ["FORTIGATE_HOST", "FORTIGATE_API_KEY"])
}


def generate_spec_prompt(description: str, service: str, sample_response: str = "") -> str:
    """Build the LLM prompt for spec generation."""
    schema_str = json.dumps(SKILL_SPEC_SCHEMA, indent=2, default=str)
    return f"""Generate a SKILL_SPEC JSON object for this infrastructure monitoring skill.

Service: {service}
Description: {description}
{f'Sample API response: {sample_response[:500]}' if sample_response else ''}

Output ONLY valid JSON matching this schema (no prose, no markdown):
{schema_str}

Rules:
- name: snake_case, descriptive (e.g. fortigate_ha_status)
- endpoints: list every API call the skill makes
- response_fields: the actual field names from the API response
- auth: one of apikey_query, bearer, basic, pve_token, apikey_header, none
- health_rules: concrete conditions, not vague ("status == 'active'" not "status is ok")
- config_keys: what the skill reads from the connection credentials dict

Output only the JSON object. Nothing else."""


def generate_spec(
    description: str,
    service: str,
    lm_client,
    model: str,
    sample_response: str = "",
) -> dict:
    """Call the LLM to generate a SKILL_SPEC. Returns parsed dict or raises."""
    prompt = generate_spec_prompt(description, service, sample_response)
    response = lm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt + "\n/no_think"}],
        tools=None,
        temperature=0.1,
        max_tokens=800,
    )
    text = response.choices[0].message.content or ""
    # Strip markdown fences
    text = text.strip().strip("```json").strip("```").strip()
    spec = json.loads(text)
    # Basic validation
    for required in ("name", "service", "endpoints", "parameters"):
        if required not in spec:
            raise ValueError(f"SKILL_SPEC missing required field: {required!r}")
    return spec
