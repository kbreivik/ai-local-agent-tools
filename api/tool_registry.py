"""
Auto-discovers tools from mcp_server/tools/*.py by inspecting function
signatures and docstrings. Adding a new .py file to mcp_server/tools/
makes it appear in the GUI automatically — no changes needed here.
"""
import ast
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).parent.parent / "mcp_server" / "tools"

# Functions that are internal helpers, not public tools
_SKIP = {"_client", "_ts", "_ok", "_err", "_degraded", "_bootstrap", "_checkpoint_dir",
         "_audit_path", "_assert_not_failed", "_gate"}


def _ast_param_info(filepath: Path, func_name: str) -> list[dict]:
    """Extract param names, types and defaults via AST (no import needed)."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                params = []
                args = node.args
                defaults = args.defaults
                offset = len(args.args) - len(defaults)
                for i, arg in enumerate(args.args):
                    if arg.arg == "self":
                        continue
                    ann = ""
                    if arg.annotation:
                        ann = ast.unparse(arg.annotation)
                    default = None
                    has_default = (i - offset) >= 0
                    if has_default:
                        default = ast.unparse(defaults[i - offset])
                    params.append({
                        "name": arg.arg,
                        "type": ann or "str",
                        "default": default,
                        "required": not has_default,
                    })
                return params
    except Exception:
        pass
    return []


def _python_type_to_json(t: str) -> str:
    mapping = {"str": "string", "int": "integer", "float": "number",
               "bool": "boolean", "dict": "object", "list": "array"}
    return mapping.get(t, "string")


def load_registry() -> list[dict]:
    """Return list of tool descriptors for every public function in tools/."""
    registry = []

    # Ensure project root is importable
    project_root = str(TOOLS_DIR.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    for py_file in sorted(TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"mcp_server.tools.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            continue

        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if name.startswith("_") or name in _SKIP:
                continue
            if obj.__module__ != module_name:
                continue  # skip re-exports

            doc = (inspect.getdoc(obj) or "").strip()
            raw_params = _ast_param_info(py_file, name)
            params_schema = {
                "type": "object",
                "properties": {
                    p["name"]: {
                        "type": _python_type_to_json(p["type"]),
                        "description": p["name"],
                        **({"default": p["default"]} if p["default"] is not None else {}),
                    }
                    for p in raw_params
                },
                "required": [p["name"] for p in raw_params if p["required"]],
            }
            registry.append({
                "name": name,
                "module": py_file.stem,
                "description": doc,
                "params": raw_params,
                "schema": params_schema,
                "category": py_file.stem,
            })

    return registry


def invoke_tool(name: str, params: dict[str, Any]) -> Any:
    """Dynamically invoke a tool by name with given params."""
    project_root = str(TOOLS_DIR.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    for py_file in TOOLS_DIR.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        module_name = f"mcp_server.tools.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        fn = getattr(mod, name, None)
        if fn and callable(fn) and name not in _SKIP:
            return fn(**params)

    raise ValueError(f"Tool '{name}' not found in registry")


# Cached registry — reloaded on each request in dev, could be cached in prod
_CACHE: list[dict] | None = None


def get_registry(refresh: bool = False) -> list[dict]:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = load_registry()
    return _CACHE
