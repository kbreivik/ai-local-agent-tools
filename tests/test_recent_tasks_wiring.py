"""v2.37.0 — structural guards for the RECENT section wiring.

These are cheap file-level checks so future refactors can't silently
drop the feature. If these fail, the feature is shipping broken.
"""
import pathlib


REPO_ROOT = pathlib.Path(__file__).parent.parent


def test_recent_tasks_component_exists():
    p = REPO_ROOT / "gui" / "src" / "components" / "RecentTasks.jsx"
    assert p.exists(), "RecentTasks.jsx must exist (v2.37.0)"
    src = p.read_text(encoding="utf-8")
    assert "CollapsibleSection" in src
    assert 'storageKey="recent-tasks"' in src
    assert "defaultOpen={false}" in src
    assert "/api/logs/operations/recent" in src
    assert "setTask" in src


def test_recent_tasks_mounted_in_parent():
    """RecentTasks must be imported + rendered next to TaskTemplates."""
    candidates = [
        REPO_ROOT / "gui" / "src" / "components" / "CommandPanel.jsx",
        REPO_ROOT / "gui" / "src" / "App.jsx",
    ]
    matches = [
        p for p in candidates
        if p.exists() and "RecentTasks" in p.read_text(encoding="utf-8")
    ]
    assert matches, (
        "RecentTasks must be imported + rendered in CommandPanel.jsx or App.jsx"
    )


def test_templates_uses_collapsible_section():
    """TaskTemplates must use the canonical CollapsibleSection wrapper
    (v2.37.0 migration — no more inline useState(false) for open)."""
    p = REPO_ROOT / "gui" / "src" / "components" / "TaskTemplates.jsx"
    src = p.read_text(encoding="utf-8")
    assert "CollapsibleSection" in src, (
        "TaskTemplates must import + use CollapsibleSection (v2.37.0)"
    )
    assert 'storageKey="task-templates"' in src, (
        "TaskTemplates must use storageKey='task-templates' for persistence"
    )
    assert "defaultOpen={false}" in src, (
        "TaskTemplates must default to collapsed"
    )


def test_recent_tasks_count_setting_registered():
    """recentTasksCount Settings key must exist in api/routers/settings.py."""
    p = REPO_ROOT / "api" / "routers" / "settings.py"
    src = p.read_text(encoding="utf-8")
    assert "recentTasksCount" in src


def test_recent_tasks_count_in_frontend_allowlist():
    """recentTasksCount must be in OptionsContext DEFAULTS + SERVER_KEYS.
    The v2.36.6 CI guard would also catch this; explicit assertion here
    makes the v2.37.0 expectation visible."""
    p = REPO_ROOT / "gui" / "src" / "context" / "OptionsContext.jsx"
    src = p.read_text(encoding="utf-8")
    # Appears in DEFAULTS
    assert "recentTasksCount: 10" in src or "recentTasksCount:10" in src
    # Appears in SERVER_KEYS
    assert "'recentTasksCount'" in src or '"recentTasksCount"' in src


def test_recent_endpoint_filters_direct_prefix():
    """v2.37.1 — /api/logs/operations/recent must NOT include
    operations whose label starts with 'direct:' (TOOLBOX fires)."""
    p = REPO_ROOT / "api" / "routers" / "logs.py"
    src = p.read_text(encoding="utf-8")
    assert "label NOT LIKE 'direct:%'" in src, (
        "RECENT endpoint must filter out direct:-prefixed operations"
    )


def test_logs_escalations_reads_agent_escalations():
    """v2.37.1 — /api/logs/escalations must hit agent_escalations
    (canonical table), NOT the orphaned SQLAlchemy escalations table."""
    p = REPO_ROOT / "api" / "routers" / "logs.py"
    src = p.read_text(encoding="utf-8")
    # positive: reads from agent_escalations
    assert "FROM agent_escalations" in src, (
        "Logs escalations endpoint must read from agent_escalations"
    )
    # negative: no longer routes to q.get_escalations
    assert "q.get_escalations" not in src, (
        "v2.37.1 removed the q.get_escalations call from logs.py"
    )
    assert "q.resolve_escalation" not in src, (
        "v2.37.1 removed the q.resolve_escalation call from logs.py"
    )
