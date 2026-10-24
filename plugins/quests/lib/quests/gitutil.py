"""The single place git is invoked: one helper, one environment policy."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    if not env.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=5"
    return env


def run_git(args: list[str], cwd: Path | None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run git; never raises on a non-zero exit. A timeout raises TimeoutExpired."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else None,
        env=git_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
