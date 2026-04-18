"""Snapshot tests for agent system prompts (v2.34.15).

If a PR changes the rendered prompt text — directly, via tool registry
introspection (signature injection, call-example rendering), or via an
allowlist change — this test fails. The diff is printed so the reviewer
can see exactly what the LLM will now see.

To update snapshots intentionally::

    pytest tests/test_prompt_snapshots.py --update-snapshots

Snapshots live in ``tests/snapshots/prompts/*.txt``. Commit them with
the PR; reviewers use the diff as the artifact.
"""
import difflib
import pathlib

import pytest

SNAPSHOT_DIR = pathlib.Path(__file__).parent / "snapshots" / "prompts"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _render_all() -> dict:
    """Render the four agent prompts. Returns ``{name: rendered_text}``."""
    from api.agents.router import (
        STATUS_PROMPT, RESEARCH_PROMPT, ACTION_PROMPT, BUILD_PROMPT,
    )
    return {
        "observe":     STATUS_PROMPT,
        "investigate": RESEARCH_PROMPT,
        "execute":     ACTION_PROMPT,
        "build":       BUILD_PROMPT,
    }


@pytest.mark.parametrize("name", ["observe", "investigate", "execute", "build"])
def test_prompt_snapshot(name, update_snapshots):
    rendered = _render_all()[name]
    snapshot_path = SNAPSHOT_DIR / f"{name}.txt"

    if update_snapshots or not snapshot_path.exists():
        snapshot_path.write_text(rendered, encoding="utf-8")
        pytest.skip(f"Snapshot written: {snapshot_path}")

    expected = snapshot_path.read_text(encoding="utf-8")
    if expected == rendered:
        # Canary: record "not diverged" for Prometheus consumers that watch
        # this metric for drift between committed snapshots and runtime prompt.
        try:
            from api.metrics import PROMPT_SNAPSHOT_DIVERGED_COUNTER  # noqa: F401
        except Exception:
            pass
        return

    diff = "\n".join(difflib.unified_diff(
        expected.splitlines(),
        rendered.splitlines(),
        fromfile=f"snapshot:{name}.txt",
        tofile=f"rendered:{name}",
        lineterm="",
    ))
    try:
        from api.metrics import PROMPT_SNAPSHOT_DIVERGED_COUNTER
        PROMPT_SNAPSHOT_DIVERGED_COUNTER.labels(prompt_name=name).inc()
    except Exception:
        pass
    pytest.fail(
        f"Prompt '{name}' diverges from committed snapshot.\n"
        f"Review the diff below. If the change is intentional, run:\n"
        f"  pytest tests/test_prompt_snapshots.py --update-snapshots\n"
        f"and commit tests/snapshots/prompts/{name}.txt.\n\n"
        f"{diff}"
    )
