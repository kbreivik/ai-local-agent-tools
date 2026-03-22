"""Build LLM prompts for skill generation."""
import os
from datetime import datetime, timezone


_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "modules", "_template.py")


def _read_template() -> str:
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_generation_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    existing_skills: list = None,
    spec: dict = None,
) -> str:
    """Build the full prompt for LLM-based skill generation."""
    import json as _json
    template = _read_template()

    sections = []

    # Section 1: Contract
    sections.append("## Skill Contract (follow this exactly)\n")
    sections.append("```python")
    sections.append(template)
    sections.append("```\n")

    # Section 2: What to Build
    sections.append("## What to Build\n")
    sections.append(f"- **Description**: {description}")
    sections.append(f"- **Category**: {category}")
    if api_base:
        sections.append(f"- **API Base URL**: {api_base}")
    sections.append(f"- **Auth type**: {auth_type}\n")

    # Section 2a: Service-specific auth patterns
    _desc_lower = description.lower()
    _svc_lower = (category or "").lower()
    if "proxmox" in _desc_lower or "proxmox" in _svc_lower:
        sections.append("## Proxmox Auth Pattern (mandatory)\n")
        sections.append(
            "PROXMOX_TOKEN_ID env var has format 'user@realm!tokenname' — you MUST split on '!' "
            "to separate user from token_name before calling ProxmoxAPI().\n"
        )
        sections.append("```python")
        sections.append("token_id = os.environ.get(\"PROXMOX_TOKEN_ID\", \"\")")
        sections.append("if \"!\" in token_id:")
        sections.append("    user, token_name = token_id.split(\"!\", 1)")
        sections.append("else:")
        sections.append("    user = os.environ.get(\"PROXMOX_USER\", \"root@pam\")")
        sections.append("    token_name = token_id")
        sections.append("prox = ProxmoxAPI(host, user=user, token_name=token_name,")
        sections.append("                  token_value=secret, verify_ssl=False)")
        sections.append("```\n")

    # Section 2b: Validated spec (if provided — replaces guessing endpoints)
    if spec:
        sections.append("## Validated SKILL_SPEC (implement this exactly)\n")
        sections.append(
            "The following spec was generated AND validated against the live service. "
            "All endpoints, auth patterns, and response fields are confirmed correct. "
            "Implement this spec faithfully — do not invent different endpoints or fields.\n"
        )
        sections.append("```json")
        sections.append(_json.dumps(spec, indent=2))
        sections.append("```\n")

    # Section 3: Reference Documentation (optional)
    if context_docs:
        sections.append("## Reference Documentation\n")
        for doc in context_docs:
            sections.append(f"```\n{doc}\n```\n")

    # Section 4: Existing Skills (optional)
    if existing_skills:
        sections.append("## Existing Skills (avoid these names)\n")
        for name in existing_skills:
            sections.append(f"- {name}")
        sections.append("")

    # Section 5: Hard Constraints
    sections.append("## Hard Constraints\n")
    sections.append("1. Output ONLY valid Python — no markdown fences, no explanation text before or after.")
    sections.append("2. SKILL_META name must be snake_case, descriptive, unique.")
    sections.append("3. Use httpx for HTTP calls with explicit timeouts (default 10s).")
    sections.append("4. Return _ok/_err/_degraded dicts exactly as shown in template.")
    sections.append("5. Include _ts, _ok, _err, _degraded helpers in every skill.")
    sections.append("6. NEVER import subprocess, os.system, eval, exec, __import__, importlib, shutil.")
    sections.append("7. Set readOnlyHint: True by default unless skill explicitly modifies state.")
    sections.append('8. Handle missing config: return _err("CONFIG_KEY not set. Configure via Settings or env var.")')
    sections.append("9. No markdown fences in output.")

    return "\n".join(sections)


def build_export_document(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    existing_skills: list = None,
    spec: dict = None,
) -> str:
    """Build a self-contained export document with instructions and prompt."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = build_generation_prompt(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        context_docs=context_docs,
        existing_skills=existing_skills,
        spec=spec,
    )

    header = f"# Skill Generation Export — {now}\n"
    instructions = (
        "## Instructions\n\n"
        "1. Copy everything below the separator line into your LLM chat (ChatGPT, Claude, etc.).\n"
        "2. Send the prompt. The LLM will output a single Python file.\n"
        "3. Save the output as a .py file (use the skill name from SKILL_META as the filename).\n"
        "4. Copy the .py file to the agent's `data/skill_imports/` directory.\n"
        "5. In the agent chat, run: `skill_import` to load and validate the skill.\n"
        "6. Verify with: `skill_list` to see the newly imported skill.\n"
    )

    return f"{header}\n{instructions}\n---\n\n{prompt}"
