"""Skill generation backends: local LM Studio, cloud Anthropic, and export."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import httpx

from mcp_server.tools.skills import prompt_builder, registry, validator


log = logging.getLogger(__name__)

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "agent_settings.json"
)
_EXPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_exports"
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _get_backend_config() -> dict:
    """Load skill generation config from settings file + env var overrides."""
    file_cfg = {}
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                cfg = json.load(f)
                file_cfg = cfg.get("skill_generation", {})
    except Exception:
        pass

    return {
        "backend": os.environ.get("SKILL_GEN_BACKEND", file_cfg.get("backend", "local")),
        "lm_studio_base_url": os.environ.get(
            "LM_STUDIO_BASE_URL",
            file_cfg.get("lm_studio_base_url", "http://localhost:1234/v1"),
        ),
        "lm_studio_api_key": os.environ.get(
            "LM_STUDIO_API_KEY",
            file_cfg.get("lm_studio_api_key", "lm-studio"),
        ),
        "lm_studio_model": file_cfg.get("lm_studio_model", ""),
        "anthropic_api_key": os.environ.get(
            "ANTHROPIC_API_KEY",
            file_cfg.get("anthropic_api_key", ""),
        ),
    }


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = re.sub(r'^```python\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


def _fetch_relevant_docs(description: str) -> list[str]:
    """Extract keywords from description, query MuninnDB for context."""
    stop_words = frozenset({
        "the", "and", "for", "that", "this", "with", "from", "into",
        "will", "should", "could", "would", "have", "been", "being",
        "their", "there", "then", "than", "when", "what", "which",
        "about", "some", "other", "more", "also", "very", "just",
    })
    words = description.split()
    keywords = [w for w in words if len(w) > 4 and w.lower() not in stop_words]
    if not keywords:
        return []

    query_str = " ".join(keywords[:8])
    api_port = os.environ.get("API_PORT", "8000")

    try:
        r = httpx.post(
            f"http://localhost:{api_port}/api/memory/activate",
            json={"query": query_str},
            timeout=3.0,
        )
        if r.status_code == 200:
            activations = r.json().get("activations", [])
            docs = []
            total = 0
            for a in activations:
                content = a.get("content", "")
                if total + len(content) > 2000:
                    remaining = 2000 - total
                    if remaining > 100:
                        docs.append(content[:remaining])
                    break
                docs.append(content)
                total += len(content)
            return docs
    except Exception:
        pass
    return []


def _generate_local(prompt: str) -> str:
    """Generate skill code via local LM Studio (OpenAI-compatible API)."""
    cfg = _get_backend_config()
    base_url = cfg["lm_studio_base_url"]
    api_key = cfg["lm_studio_api_key"]
    model = cfg["lm_studio_model"]

    # Auto-detect model if not configured
    if not model:
        try:
            r = httpx.get(f"{base_url}/models", timeout=5.0)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    model = models[0].get("id", "")
        except Exception:
            pass
    if not model:
        model = "default"

    r = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the skill now. Output only Python code."},
            ],
        },
        timeout=120.0,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    return _strip_fences(text)


def _generate_cloud(prompt: str) -> str:
    """Generate skill code via Anthropic Claude API."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic>=0.50.0"
        )

    cfg = _get_backend_config()
    api_key = cfg["anthropic_api_key"]
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Configure via Settings or env var."
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=prompt,
        messages=[
            {"role": "user", "content": "Generate the skill now. Output only Python code."},
        ],
    )
    text = message.content[0].text
    return _strip_fences(text)


def _suggest_name(description: str) -> str:
    """Generate a suggested filename from description (first 4 significant words)."""
    stop_words = frozenset({
        "the", "and", "for", "that", "this", "with", "from", "into",
        "a", "an", "of", "on", "in", "to", "is", "it", "by", "as",
    })
    words = description.lower().split()
    significant = [re.sub(r'[^a-z0-9]', '', w) for w in words if w not in stop_words]
    significant = [w for w in significant if w]
    return "_".join(significant[:4]) or "skill"


def _generate_export(prompt: str, description: str) -> dict:
    """Save generation prompt as an export document for offline use."""
    os.makedirs(_EXPORTS_DIR, exist_ok=True)

    # Rebuild as export document (with instructions header)
    # The prompt passed in is the raw generation prompt; we need the export document
    # We re-derive it here since we have description but not all params.
    # Actually the caller should pass the export doc. Let's just save the prompt
    # with a header.
    suggested = _suggest_name(description)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{suggested}_{timestamp}.md"
    filepath = os.path.join(_EXPORTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(prompt)

    return _ok({"export_path": filepath, "filename": filename},
               f"Export saved to data/skill_exports/{filename}")


def generate_skill(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    backend: str = "",
) -> dict:
    """Generate a new skill. Dispatches to local, cloud, or export backend."""
    # Resolve backend
    if not backend:
        cfg = _get_backend_config()
        backend = cfg["backend"]

    # Load existing skill names for collision avoidance
    existing_names = [s["name"] for s in registry.list_skills(enabled_only=False)]

    # Fetch context docs from MuninnDB
    if context_docs is None:
        context_docs = _fetch_relevant_docs(description)

    # Export path — build export document instead of generation prompt
    if backend == "export":
        doc = prompt_builder.build_export_document(
            description=description,
            category=category,
            api_base=api_base,
            auth_type=auth_type,
            context_docs=context_docs,
            existing_skills=existing_names,
        )
        return _generate_export(doc, description)

    # Build generation prompt for local/cloud
    prompt = prompt_builder.build_generation_prompt(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        context_docs=context_docs,
        existing_skills=existing_names,
    )

    try:
        if backend == "cloud":
            code = _generate_cloud(prompt)
            backend_used = "cloud"
        else:
            code = _generate_local(prompt)
            backend_used = "local"
    except Exception as e:
        return _err(f"Generation failed ({backend}): {e}")

    # Validate
    result = validator.validate_skill_code(code)
    if not result["valid"]:
        return _err(f"Generated code failed validation: {result['error']}", data={"code": code})

    return _ok({
        "code": code,
        "name": result["name"],
        "meta": result["meta"],
        "backend_used": backend_used,
    }, f"Skill '{result['name']}' generated via {backend_used}")
