"""v2.36.0 — regression test for agent_llm_traces.model capture.

The bug: pre-v2.36.0 passed the env-var _lm_model() to log_llm_step instead
of the actual model the API returned. When external AI lands in v2.36.3, a
Claude call would silently log as 'qwen3-coder-next'.

This test asserts _extract_response_model correctly prefers the response's
model attribute over the fallback.
"""
from types import SimpleNamespace


def test_extract_response_model_prefers_response_attr():
    from api.routers.agent import _extract_response_model

    # OpenAI SDK response shape — model is an attribute
    resp = SimpleNamespace(model="claude-sonnet-4-6")
    assert _extract_response_model(resp, fallback="qwen3-coder-next") == \
        "claude-sonnet-4-6"


def test_extract_response_model_falls_back_when_missing():
    from api.routers.agent import _extract_response_model

    resp = SimpleNamespace()  # no model attr
    assert _extract_response_model(resp, fallback="qwen3-coder-next") == \
        "qwen3-coder-next"


def test_extract_response_model_falls_back_on_none_value():
    from api.routers.agent import _extract_response_model

    resp = SimpleNamespace(model=None)
    assert _extract_response_model(resp, fallback="qwen3-coder-next") == \
        "qwen3-coder-next"


def test_extract_response_model_handles_dict_shape():
    """Raw fallback responses (our forced_synthesis shim) are dicts."""
    from api.routers.agent import _extract_response_model

    resp = {"model": "grok-2-latest", "choices": []}
    assert _extract_response_model(resp, fallback="qwen3-coder-next") == \
        "grok-2-latest"


def test_extract_response_model_returns_empty_when_no_fallback():
    from api.routers.agent import _extract_response_model

    resp = SimpleNamespace()
    assert _extract_response_model(resp, fallback="") == ""


def test_write_trace_step_accepts_provider_kwarg():
    """Smoke test — function signature accepts provider kwarg (v2.36.0).

    Runs against sqlite / no-op path (no postgres in CI). Never actually
    touches the DB. Validates the signature hasn't regressed.
    """
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")  # no-op path
    from api.db.llm_traces import write_trace_step
    # Should not raise on the provider kwarg
    write_trace_step(
        operation_id="test-op",
        step_index=0,
        messages_delta=[],
        response_raw={},
        provider="claude",
    )
