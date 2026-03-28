"""Unit tests for mcp_server.tools.skills.validator — sandbox ban rules."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp_server.tools.skills.validator import validate_skill_code

_VALID_MINIMAL = '''
SKILL_META = {
    "name": "test_skill",
    "description": "A test skill",
    "category": "monitoring",
    "parameters": {},
}

def execute(**kwargs):
    return {"status": "ok", "data": None, "timestamp": "", "message": "ok"}
'''


def _skill_with_header(import_line: str, body: str = "") -> str:
    return f"""{import_line}

SKILL_META = {{
    "name": "test_skill",
    "description": "A test skill",
    "category": "monitoring",
    "parameters": {{}},
}}

def execute(**kwargs):
    {body or 'return {"status": "ok", "data": None, "timestamp": "", "message": "ok"}'}
"""


def test_subprocess_banned():
    code = _skill_with_header("import subprocess")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "subprocess" in result["error"]


def test_eval_banned():
    code = _skill_with_header("", "eval('1+1')")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "eval" in result["error"]


def test_socket_import_banned():
    code = _skill_with_header("import socket")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "socket" in result["error"]


def test_urllib_import_banned():
    code = _skill_with_header("import urllib")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_urllib_request_import_banned():
    code = _skill_with_header("import urllib.request")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_http_import_banned():
    code = _skill_with_header("import http")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_http_client_import_from_banned():
    code = _skill_with_header("from http import client")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_ftplib_banned():
    code = _skill_with_header("import ftplib")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_ssl_banned():
    code = _skill_with_header("import ssl")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_remove_banned():
    code = _skill_with_header("import os", "os.remove('/tmp/x')")
    result = validate_skill_code(code)
    assert result["valid"] is False
    assert "os.remove" in result["error"]


def test_os_makedirs_banned():
    code = _skill_with_header("import os", "os.makedirs('/tmp/x')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_rename_banned():
    code = _skill_with_header("import os", "os.rename('/a', '/b')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_listdir_banned():
    code = _skill_with_header("import os", "os.listdir('.')")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_execv_banned():
    code = _skill_with_header("import os", "os.execv('/bin/sh', [])")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_fork_banned():
    code = _skill_with_header("import os", "os.fork()")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_kill_banned():
    code = _skill_with_header("import os", "os.kill(1, 9)")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_import_ctypes_banned():
    code = _skill_with_header("import ctypes")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_from_ctypes_import_banned():
    code = _skill_with_header("from ctypes import cdll")
    result = validate_skill_code(code)
    assert result["valid"] is False, (
        "from ctypes import cdll must be blocked — if this fails, the ImportFrom "
        "check needs to be added explicitly"
    )


def test_from_ctypes_util_import_banned():
    code = _skill_with_header("from ctypes.util import find_library")
    result = validate_skill_code(code)
    assert result["valid"] is False


def test_os_environ_get_allowed():
    code = _skill_with_header(
        "import os",
        'x = os.environ.get("MY_VAR", "")\n    return {"status": "ok", "data": x, "timestamp": "", "message": ""}'
    )
    result = validate_skill_code(code)
    assert result["valid"] is True, f"os.environ.get must be allowed: {result.get('error')}"


def test_os_path_join_allowed():
    code = _skill_with_header(
        "import os",
        'p = os.path.join("/a", "b")\n    return {"status": "ok", "data": p, "timestamp": "", "message": ""}'
    )
    result = validate_skill_code(code)
    assert result["valid"] is True, f"os.path.join must be allowed: {result.get('error')}"


def test_valid_minimal_skill_passes():
    result = validate_skill_code(_VALID_MINIMAL)
    assert result["valid"] is True
    assert result["name"] == "test_skill"
