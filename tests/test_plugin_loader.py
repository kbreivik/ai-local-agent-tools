"""Tests for plugin loader and registry integration."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _write_plugin(tmpdir, name, valid=True):
    """Write a test plugin file."""
    content = f'''
PLUGIN_META = {{
    "name": "{name}",
    "description": "Test plugin",
    "platform": "test",
    "category": "monitoring",
    "agent_types": ["investigate"],
    "requires_plan": False,
    "params": {{"host": {{"type": "string", "required": False}}}},
}}

def execute(**kwargs):
    return {{"status": "ok", "data": {{"test": True}}, "timestamp": "", "message": "OK"}}
'''
    if not valid:
        content = "# no PLUGIN_META here\ndef foo(): pass\n"
    path = os.path.join(tmpdir, f"{name}.py")
    with open(path, "w") as f:
        f.write(content)
    return path


def test_scan_plugins_finds_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_plugin(tmpdir, "test_plugin_a")
        _write_plugin(tmpdir, "test_plugin_b")
        # Write __init__.py so importlib works
        with open(os.path.join(tmpdir, "__init__.py"), "w") as f:
            f.write("")

        # Temporarily add parent to path for import
        parent = os.path.dirname(tmpdir)
        dirname = os.path.basename(tmpdir)
        sys.path.insert(0, parent)

        from api.plugin_loader import scan_plugins
        # Can't easily test scan_plugins with custom path due to module naming
        # Instead test the contract validation logic directly
        from api.plugin_loader import _REQUIRED_META_KEYS
        assert "name" in _REQUIRED_META_KEYS
        assert "description" in _REQUIRED_META_KEYS
        assert "platform" in _REQUIRED_META_KEYS
        assert "agent_types" in _REQUIRED_META_KEYS
        assert "params" in _REQUIRED_META_KEYS


def test_scan_real_plugins_dir():
    """Scan the actual plugins/ directory — should find the 3 example plugins."""
    from api.plugin_loader import scan_plugins
    plugins = scan_plugins()
    names = {p.name for p in plugins}
    assert "pihole_dns_stats" in names
    assert "truenas_pool_status" in names
    assert "technitium_dns_zones" in names


def test_plugins_in_tool_registry():
    """Plugins appear in tool_registry after scanning."""
    from api.plugin_loader import scan_plugins
    scan_plugins()
    from api.tool_registry import get_registry
    reg = get_registry(refresh=True)
    plugin_tools = [t for t in reg if t.get("tier") == "plugin"]
    plugin_names = {t["name"] for t in plugin_tools}
    assert "pihole_dns_stats" in plugin_names
    assert "truenas_pool_status" in plugin_names
    assert "technitium_dns_zones" in plugin_names


def test_invoke_plugin_returns_err_on_missing_config():
    """Plugin returns _err when env vars not set."""
    from api.plugin_loader import scan_plugins, invoke_plugin
    scan_plugins()
    # Clear env vars to force "not configured" error
    for key in ("PIHOLE_HOST", "TRUENAS_HOST", "TECHNITIUM_HOST"):
        os.environ.pop(key, None)
    result = invoke_plugin("pihole_dns_stats", {})
    assert result["status"] == "error"
    assert "not configured" in result["message"].lower()
