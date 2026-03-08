"""
Docker Engine management tools — SSH to Debian 12 host.

Config env vars:
  DOCKER_ENGINE_HOST       IP of the Debian 12 Docker host
  DOCKER_ENGINE_USER       SSH username (default: root)
  DOCKER_ENGINE_SSH_KEY    Path to private key file
  DOCKER_ENGINE_SSH_PORT   SSH port (default: 22)

These can also be set via /api/settings (stored in data/agent_settings.json).
"""
import json
import os
import logging
from datetime import datetime, timezone
from typing import Generator

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _ssh_config() -> dict:
    """Load SSH config from env vars or settings file."""
    # Try settings file first (set via GUI)
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "agent_settings.json"
    )
    file_cfg = {}
    try:
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                cfg = json.load(f)
                file_cfg = cfg.get("docker_engine", {})
    except Exception:
        pass

    return {
        "host":     os.environ.get("DOCKER_ENGINE_HOST", file_cfg.get("host", "")),
        "user":     os.environ.get("DOCKER_ENGINE_USER", file_cfg.get("user", "root")),
        "key_path": os.environ.get("DOCKER_ENGINE_SSH_KEY", file_cfg.get("key_path", "")),
        "port":     int(os.environ.get("DOCKER_ENGINE_SSH_PORT", file_cfg.get("port", 22))),
    }


def _get_ssh_client():
    """Create and return a connected paramiko SSHClient."""
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("paramiko not installed — run: pip install paramiko")

    cfg = _ssh_config()
    if not cfg["host"]:
        raise RuntimeError(
            "DOCKER_ENGINE_HOST not configured. Set via Settings > Docker Engine or env var."
        )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": cfg["host"],
        "port": cfg["port"],
        "username": cfg["user"],
        "timeout": 15,
    }
    if cfg["key_path"] and os.path.exists(cfg["key_path"]):
        connect_kwargs["key_filename"] = cfg["key_path"]

    client.connect(**connect_kwargs)
    return client


def _run_ssh(command: str, timeout: int = 60) -> tuple[str, str, int]:
    """Run a command over SSH. Returns (stdout, stderr, exit_code)."""
    client = _get_ssh_client()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return out, err, exit_code
    finally:
        client.close()


def _run_ssh_streaming(command: str, timeout: int = 300) -> Generator[str, None, int]:
    """
    Run a command over SSH and yield output lines as they arrive.
    Yields strings. Returns exit code via StopIteration value.
    """
    try:
        import paramiko
    except ImportError:
        yield "[error] paramiko not installed"
        return 1

    cfg = _ssh_config()
    if not cfg["host"]:
        yield "[error] DOCKER_ENGINE_HOST not configured"
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = {
        "hostname": cfg["host"],
        "port": cfg["port"],
        "username": cfg["user"],
        "timeout": 15,
    }
    if cfg["key_path"] and os.path.exists(cfg["key_path"]):
        connect_kwargs["key_filename"] = cfg["key_path"]

    try:
        client.connect(**connect_kwargs)
        _, stdout, stderr = client.exec_command(
            command, timeout=timeout, get_pty=True
        )
        # Read line-by-line
        for line in stdout:
            yield line.rstrip("\n")
        exit_code = stdout.channel.recv_exit_status()
        return exit_code
    except Exception as e:
        yield f"[ssh error] {e}"
        return 1
    finally:
        client.close()


# ── Tool functions ─────────────────────────────────────────────────────────────

def docker_engine_version() -> dict:
    """
    Get the current Docker Engine version on the remote host.
    Returns version info including client and server versions.
    """
    try:
        out, err, code = _run_ssh("docker version --format '{{json .}}'", timeout=15)
        if code != 0:
            # Fallback to plain text
            out2, err2, code2 = _run_ssh("docker version", timeout=15)
            if code2 != 0:
                return _err(f"docker version failed (exit {code2}): {err2.strip()}")
            return _ok({"raw": out2.strip()}, "Docker Engine version (text format)")

        try:
            version_data = json.loads(out.strip())
            server_ver = version_data.get("Server", {}).get("Engine", {}).get("Version", "unknown")
            client_ver = version_data.get("Client", {}).get("Version", "unknown")
            return _ok(
                {"server_version": server_ver, "client_version": client_ver, "raw": version_data},
                f"Docker Engine server: {server_ver}, client: {client_ver}",
            )
        except json.JSONDecodeError:
            return _ok({"raw": out.strip()}, "Docker Engine version")

    except Exception as e:
        return _err(f"docker_engine_version error: {e}")


def docker_engine_check_update() -> dict:
    """
    Check if a Docker Engine update is available on the Debian 12 host.
    Runs: apt-get update (quietly) then apt-cache policy docker-ce
    Returns: current version, candidate version, update_available bool.
    """
    try:
        # Update package index (quiet)
        _run_ssh("apt-get update -qq 2>/dev/null", timeout=60)

        # Check policy
        out, err, code = _run_ssh("apt-cache policy docker-ce", timeout=30)
        if code != 0:
            return _err(f"apt-cache policy failed: {err.strip()}")

        current = "unknown"
        candidate = "unknown"
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Installed:"):
                current = line.split(":", 1)[1].strip()
            elif line.startswith("Candidate:"):
                candidate = line.split(":", 1)[1].strip()

        update_available = (
            current != candidate
            and current not in ("(none)", "unknown")
            and candidate not in ("(none)", "unknown")
        )

        msg = (
            f"Update available: {current} → {candidate}"
            if update_available
            else f"Docker Engine is up to date: {current}"
        )
        return _ok(
            {
                "current_version": current,
                "candidate_version": candidate,
                "update_available": update_available,
            },
            msg,
        )
    except Exception as e:
        return _err(f"docker_engine_check_update error: {e}")


def docker_engine_update(dry_run: bool = True) -> dict:
    """
    Upgrade Docker Engine on the remote Debian 12 host via apt-get.

    DESTRUCTIVE — requires plan_action() approval before calling with dry_run=False.

    dry_run=True  → runs apt-get upgrade --simulate (safe, no changes)
    dry_run=False → runs apt-get upgrade -y docker-ce docker-ce-cli containerd.io

    Streams output line-by-line. Returns final status and all output lines.
    """
    if dry_run:
        command = (
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade --simulate docker-ce docker-ce-cli containerd.io 2>&1"
        )
        mode = "dry-run"
    else:
        command = (
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y docker-ce docker-ce-cli containerd.io 2>&1"
        )
        mode = "live"

    output_lines = []
    exit_code = 1

    try:
        gen = _run_ssh_streaming(command, timeout=600)
        for line in gen:
            output_lines.append(line)
            log.info("[docker_engine_update:%s] %s", mode, line)
        # Get return value from generator
        try:
            next(gen)
        except StopIteration as si:
            exit_code = si.value if si.value is not None else 0

        success = exit_code == 0
        # Check for upgrade in output
        upgraded = any("upgraded" in l.lower() or "newly installed" in l.lower() for l in output_lines)

        if dry_run:
            msg = f"Dry-run complete (exit {exit_code}). {'Upgrade would occur.' if upgraded else 'No upgrade needed.'}"
        else:
            msg = f"Upgrade {'succeeded' if success else 'FAILED'} (exit {exit_code})."

        # Get new version after upgrade
        new_version = None
        if not dry_run and success:
            try:
                ver_result = docker_engine_version()
                new_version = ver_result.get("data", {}).get("server_version")
            except Exception:
                pass

        return {
            "status": "ok" if success else "error",
            "data": {
                "mode": mode,
                "exit_code": exit_code,
                "output_lines": output_lines,
                "upgraded": upgraded,
                "new_version": new_version,
            },
            "timestamp": _ts(),
            "message": msg,
        }

    except Exception as e:
        return _err(f"docker_engine_update error: {e}", data={"output_lines": output_lines})
