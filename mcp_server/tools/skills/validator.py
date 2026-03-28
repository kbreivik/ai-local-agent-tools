"""Validate generated skill Python code using AST analysis only."""
import ast
import re


# Modules that must never appear in skill code
_BANNED_MODULES = frozenset({
    "subprocess", "shutil", "importlib", "ctypes", "multiprocessing",
    # Network exfiltration vectors — skills must use httpx (already on allow-list by absence)
    "socket", "urllib", "http", "ftplib", "ssl",
    # Note: 'os' is intentionally NOT banned here because starter skills use os.environ.get()
    # and os.path.*. Dangerous os.* calls are blocked at the call-level via _BANNED_OS_CALLS.
})

# Names that must never appear in imports
_BANNED_NAMES = frozenset({
    "system", "popen", "exec", "eval", "__import__", "compile",
})

# Built-in tool names that skills must not collide with
_BUILTIN_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "kafka_broker_status", "kafka_consumer_lag",
    "kafka_topic_health", "elastic_cluster_health", "elastic_search_logs",
    "docker_engine_version_tool", "docker_engine_check_update_tool",
    "docker_engine_update_tool", "ingest_url", "ingest_pdf",
    "check_internet_connectivity",
})

# Write modes for open() that are forbidden
_WRITE_MODES = frozenset({"w", "a", "x", "wb", "ab", "xb"})

# os.* calls that are never legitimate in a skill
_BANNED_OS_CALLS = frozenset({
    "system", "popen",           # already checked — kept here for documentation
    "remove", "unlink", "rmdir",
    "makedirs", "mkdir",
    "rename", "replace",
    "listdir", "scandir", "walk",
    "execv", "execve", "execvp", "execvpe",
    "fork", "kill", "killpg",
    "chown", "chmod",
    "symlink", "link",
})


def validate_skill_code(code: str) -> dict:
    """Validate generated Python skill code.

    Returns:
        {"valid": True, "name": str, "meta": dict} on success.
        {"valid": False, "error": str} on failure.
    """
    # Step 1: Syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e}"}

    # Step 2: Find SKILL_META assignment
    meta_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SKILL_META":
                    meta_node = node
                    break

    if meta_node is None:
        return {"valid": False, "error": "SKILL_META assignment not found"}

    # Step 3: Find execute function
    has_execute = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            has_execute = True
            break

    if not has_execute:
        return {"valid": False, "error": "execute() function not found"}

    # Step 4: Check banned imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root in _BANNED_MODULES:
                    return {"valid": False, "error": f"Banned import: {alias.name}"}
                if alias.name in _BANNED_NAMES:
                    return {"valid": False, "error": f"Banned import name: {alias.name}"}
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if mod_root in _BANNED_MODULES:
                    return {"valid": False, "error": f"Banned import from: {node.module}"}
            if node.names:
                for alias in node.names:
                    if alias.name in _BANNED_NAMES:
                        return {"valid": False, "error": f"Banned import name: {alias.name}"}

    # Step 5: Check banned calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # os.system, os.popen, and other dangerous os.* calls
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "os":
                    if func.attr in _BANNED_OS_CALLS:
                        return {"valid": False, "error": f"Banned call: os.{func.attr}"}
            # eval(), exec(), compile()
            if isinstance(func, ast.Name):
                if func.id in ("eval", "exec", "compile"):
                    return {"valid": False, "error": f"Banned call: {func.id}()"}
                # open() with write mode
                if func.id == "open":
                    # Check positional arg 2 or keyword 'mode'
                    mode_val = None
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        mode_val = node.args[1].value
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode_val = kw.value.value
                    if isinstance(mode_val, str) and mode_val in _WRITE_MODES:
                        return {"valid": False, "error": f"Banned call: open() with write mode '{mode_val}'"}

    # Step 6: Extract SKILL_META
    meta = None
    name = None

    # Try ast.literal_eval first
    try:
        meta = ast.literal_eval(meta_node.value)
        name = meta.get("name", "")
    except (ValueError, TypeError):
        # Fallback: walk the dict node for "name" key
        if isinstance(meta_node.value, ast.Dict):
            for key, val in zip(meta_node.value.keys, meta_node.value.values):
                if isinstance(key, ast.Constant) and key.value == "name":
                    if isinstance(val, ast.Constant):
                        name = val.value
                    break

    if not name:
        return {"valid": False, "error": "Could not extract 'name' from SKILL_META"}

    # Validate name format
    if not re.match(r'^[a-z][a-z0-9_]*$', name):
        return {"valid": False, "error": f"Skill name '{name}' is not valid snake_case"}

    # Step 7: Check collision with built-in tools
    if name in _BUILTIN_TOOLS:
        return {"valid": False, "error": f"Skill name '{name}' collides with built-in tool"}

    return {"valid": True, "name": name, "meta": meta or {"name": name}}
