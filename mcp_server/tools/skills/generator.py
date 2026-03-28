"""Skill generation backends: local LM Studio, cloud Anthropic, and export."""
import json
import logging
import os
import re
from datetime import datetime, timezone

from api.constants import DEFAULT_LM_STUDIO_URL, DEFAULT_LM_STUDIO_KEY

import httpx

from mcp_server.tools.skills import prompt_builder, registry, validator
from mcp_server.tools.skills.doc_retrieval import fetch_relevant_docs, format_docs_for_prompt


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
            file_cfg.get("lm_studio_base_url", DEFAULT_LM_STUDIO_URL),
        ),
        "lm_studio_api_key": os.environ.get(
            "LM_STUDIO_API_KEY",
            file_cfg.get("lm_studio_api_key", DEFAULT_LM_STUDIO_KEY),
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


def _fetch_relevant_docs(
    description: str, category: str = "general", api_base: str = ""
) -> tuple:
    """
    Fetch documentation context for skill generation.

    Returns:
        (context_docs_list, raw_retrieval_data)
        context_docs_list: list[str] for build_generation_prompt(context_docs=)
        raw_retrieval_data: dict with keys: keywords, context_docs, sources_used,
                            total_tokens. Empty dict on failure.
    """
    try:
        result = fetch_relevant_docs(description, category=category, api_base=api_base, token_budget=3000)
        formatted = format_docs_for_prompt(result)
        raw = result.get("data", {})
        return ([formatted] if formatted else []), raw
    except Exception as e:
        log.debug("doc_retrieval failed: %s", e)
        return [], {}


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
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the skill now. Output only Python code."},
            ],
        },
        timeout=300.0,
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


def _write_generation_log(
    skill_name: str,
    triggered_by: str,
    backend: str,
    description: str,
    category: str,
    api_base: str,
    retrieval_data: dict,
    spec_used: bool,
    spec_warnings: list,
    outcome: str,
    error_message: str = "",
) -> None:
    """Write one generation trace row to skill_generation_log. Failures are swallowed."""
    try:
        import uuid as _uuid
        import time as _time
        from mcp_server.tools.skills.storage import get_backend

        retrieval_data = retrieval_data or {}
        context_docs = retrieval_data.get("context_docs", [])
        # Strip content field — keep only metadata to avoid blob storage
        docs_for_log = [
            {k: v for k, v in d.items() if k != "content"}
            for d in context_docs
        ]

        row = {
            "id": str(_uuid.uuid4()),
            "skill_name": skill_name or "unknown",
            "triggered_by": triggered_by,
            "backend": backend,
            "description": description,
            "category": category,
            "api_base": api_base or "",
            "keywords": json.dumps(retrieval_data.get("keywords", {})),
            "docs_retrieved": json.dumps(docs_for_log),
            "total_tokens": retrieval_data.get("total_tokens", 0),
            "sources_used": json.dumps(retrieval_data.get("sources_used", [])),
            "spec_used": 1 if spec_used else 0,
            "spec_warnings": json.dumps(spec_warnings),
            "outcome": outcome,
            "error_message": error_message,
            "created_at": _time.time(),
        }
        get_backend().write_generation_log(row)
    except Exception as _e:
        log.warning("Failed to write generation log: %s", _e)


def generate_skill(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    context_docs: list = None,
    backend: str = "",
    skip_spec: bool = False,
    triggered_by: str = "skill_create",
) -> dict:
    """Generate a new skill using spec-first flow.

    Flow when api_base is provided:
      1. LLM generates SKILL_SPEC (structured, no code)
      2. SKILL_SPEC validated against live service (HTTP probes)
      3. Code generated from validated spec (near-deterministic)

    Flow when api_base is absent (or skip_spec=True):
      1. Code generated directly from description + docs
    """
    from mcp_server.tools.skills import spec_generator as sg

    # Resolve backend
    if not backend:
        cfg = _get_backend_config()
        backend = cfg["backend"]

    # Load existing skill names for collision avoidance
    existing_names = [s["name"] for s in registry.list_skills(enabled_only=False)]

    # Fetch context docs — must be a list for build_generation_prompt
    _retrieval_data: dict = {}
    if context_docs is None:
        context_docs, _retrieval_data = _fetch_relevant_docs(description, category=category, api_base=api_base)
    elif isinstance(context_docs, str):
        # Caller supplied their own context — retrieval was bypassed.
        # sources_used stays empty; log will show this as "no retrieval" rather than a failure.
        context_docs = [context_docs] if context_docs else []

    validated_spec = None
    spec_warnings: list = []

    # ── Spec-first flow (when api_base provided and backend is not export) ─────
    if api_base and not skip_spec and backend != "export":
        spec_result = sg.generate_spec(
            description=description,
            category=category,
            api_base=api_base,
            auth_type=auth_type,
            backend=backend,
        )
        if spec_result.get("status") != "ok":
            log.warning("Spec generation failed (%s) — falling back to direct generation",
                        spec_result.get("message"))
        else:
            spec = spec_result["data"]["spec"]
            # Validate spec against live service
            probe_result = sg.validate_spec_live(spec, api_base)
            probe_data = probe_result.get("data", {})
            if not probe_data.get("valid"):
                # Hard stop — don't generate code from a bad spec
                _write_generation_log(
                    skill_name="unknown", triggered_by=triggered_by, backend=backend,
                    description=description, category=category, api_base=api_base,
                    retrieval_data=_retrieval_data, spec_used=False, spec_warnings=[],
                    outcome="error",
                    error_message=f"Spec validation failed: {probe_data.get('errors', [])}",
                )
                return _err(
                    f"Spec validation failed: endpoints not reachable or returned unexpected responses. "
                    f"Errors: {probe_data.get('errors', [])}. "
                    f"Fix the api_base, check service connectivity, then retry.",
                    data={
                        "spec": spec,
                        "probe_results": probe_data.get("probe_results", []),
                        "warnings": probe_data.get("warnings", []),
                    },
                )
            validated_spec = spec
            spec_warnings = probe_data.get("warnings", [])
            log.info("Spec validated for '%s' (%d warning(s))", spec.get("name"), len(spec_warnings))

    # ── Export path ───────────────────────────────────────────────────────────
    if backend == "export":
        doc = prompt_builder.build_export_document(
            description=description,
            category=category,
            api_base=api_base,
            auth_type=auth_type,
            context_docs=context_docs,
            existing_skills=existing_names,
            spec=validated_spec,
        )
        export_result = _generate_export(doc, description)
        _write_generation_log(
            skill_name="export", triggered_by=triggered_by, backend="export",
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="export",
        )
        return export_result

    # ── Build generation prompt (with spec if available) ──────────────────────
    prompt = prompt_builder.build_generation_prompt(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        context_docs=context_docs,
        existing_skills=existing_names,
        spec=validated_spec,
    )

    try:
        if backend == "cloud":
            code = _generate_cloud(prompt)
            backend_used = "cloud"
        else:
            code = _generate_local(prompt)
            backend_used = "local"
    except Exception as e:
        _write_generation_log(
            skill_name="unknown", triggered_by=triggered_by, backend=backend,
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="error",
            error_message=f"Generation failed ({backend}): {e}",
        )
        return _err(f"Generation failed ({backend}): {e}")

    # Validate generated code
    result = validator.validate_skill_code(code)
    if not result["valid"]:
        _write_generation_log(
            skill_name="unknown", triggered_by=triggered_by, backend=backend_used,
            description=description, category=category, api_base=api_base,
            retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
            spec_warnings=spec_warnings, outcome="error",
            error_message=f"Generated code failed validation: {result['error']}",
        )
        return _err(f"Generated code failed validation: {result['error']}", data={"code": code})

    _write_generation_log(
        skill_name=result["name"], triggered_by=triggered_by, backend=backend_used,
        description=description, category=category, api_base=api_base,
        retrieval_data=_retrieval_data, spec_used=validated_spec is not None,
        spec_warnings=spec_warnings, outcome="success",
    )
    return _ok({
        "code": code,
        "name": result["name"],
        "meta": result["meta"],
        "backend_used": backend_used,
        "spec_used": validated_spec is not None,
        "spec_warnings": spec_warnings,
    }, f"Skill '{result['name']}' generated via {backend_used}"
       + (" (spec-validated)" if validated_spec else ""))
