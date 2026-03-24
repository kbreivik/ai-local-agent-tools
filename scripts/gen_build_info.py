#!/usr/bin/env python3
"""Generate api/build_info.json from git metadata and CI environment variables.

Run before `docker build` or locally:
    python scripts/gen_build_info.py

Outputs api/build_info.json with: version, commit, branch, built_at, build_number.
All git/env failures fall back to "unknown". Script always exits 0.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
OUTPUT_FILE = REPO_ROOT / "api" / "build_info.json"


def _run_git(*args) -> str:
    """Run a git command and return stdout. Returns 'unknown' on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, check=True, cwd=REPO_ROOT
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _get_branch() -> str:
    """Get branch name. Falls back to GITHUB_REF_NAME on detached HEAD."""
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        # Detached HEAD — happens on tag pushes in CI
        branch = os.environ.get("GITHUB_REF_NAME", "unknown")
    return branch


def main():
    version = "unknown"
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        pass

    build_info = {
        "version": version,
        "commit": _run_git("rev-parse", "--short", "HEAD"),
        "branch": _get_branch(),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_number": os.environ.get("GITHUB_RUN_NUMBER", "local"),
    }

    OUTPUT_FILE.write_text(json.dumps(build_info, indent=2))
    print(f"Written: {OUTPUT_FILE}")
    print(json.dumps(build_info, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Warning: gen_build_info.py failed: {e}", file=sys.stderr)
    sys.exit(0)
