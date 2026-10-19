"""Board setup: create or adopt the board branch. Never touches the code repo's tree."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from board import locate, store
from board.gitutil import run_git
from board.locate import SAME_BRANCH, BoardRef

_TIMEOUT = 30.0
_IDENT = ["-c", "user.name=board", "-c", "user.email=board@users.noreply.invalid"]
_NO_HOOKS = ["-c", "core.hooksPath=/dev/null"]


class SetupRefused(Exception):
    """Setup would change something that is not ours, or cannot proceed."""


def _git(args: list[str], cwd: Path | None, timeout: float | None = _TIMEOUT):
    try:
        return run_git(args, cwd, timeout)
    except subprocess.TimeoutExpired:
        raise SetupRefused(f"git {args[0]} timed out; nothing changed")
    except OSError as e:
        raise SetupRefused(f"cannot run git ({e}); nothing changed")


def _branch_state(url: str, branch: str, cwd: Path) -> str | None:
    """None when the branch is absent; otherwise the board.json text ('' if missing)."""
    ls = _git(["ls-remote", "--heads", url, f"refs/heads/{branch}"], cwd)
    if ls.returncode != 0:
        raise SetupRefused(f"cannot reach {url}; nothing changed")
    if not ls.stdout.strip():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _git(["init", "-q"], t)
        f = _git([*_NO_HOOKS, "fetch", "-q", url, f"refs/heads/{branch}"], t)
        if f.returncode != 0:
            raise SetupRefused(f"cannot fetch branch {branch}; nothing changed")
        show = _git(["show", "FETCH_HEAD:board.json"], t)
        return show.stdout if show.returncode == 0 else ""


def _is_board(text: str) -> bool:
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("schema") == 1


def _create(url: str, branch: str, key: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for args in (["init", "-q"], ["checkout", "-q", "--orphan", "board-init"]):
            if _git(args, t).returncode != 0:
                raise SetupRefused("cannot prepare the board branch; nothing changed")
        store.write_meta(t, {"schema": 1, "code_repo": key})
        _git(["add", "-A"], t)
        c = _git([*_NO_HOOKS, *_IDENT, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify",
                  "-m", "board: init"], t)
        if c.returncode != 0:
            raise SetupRefused(f"cannot create the board commit: {c.stderr.strip()}")
        p = _git(["push", "-q", url, f"HEAD:refs/heads/{branch}"], t)
        if p.returncode != 0:
            raise SetupRefused(f"push to {url} failed: {p.stderr.strip()}; nothing changed")


def init(cwd: Path, mode: str, url: str | None) -> BoardRef:
    cwd = Path(cwd)
    key = locate.repo_key(cwd)
    if key is None:
        raise SetupRefused("not inside a git repository")
    if mode == "same":
        url = locate._origin_url(cwd) or locate._common_dir(cwd)
        branch = SAME_BRANCH
    elif mode == "external":
        if not url:
            raise SetupRefused("external mode needs --url")
        branch = f"board/{locate.slug(key)}"
    else:
        raise SetupRefused(f"unknown mode {mode!r}")
    ref = BoardRef(key, mode, url, branch)
    existing = _branch_state(url, branch, cwd)
    if existing is None:
        _create(url, branch, key)
    elif not _is_board(existing):
        raise SetupRefused(f"branch {branch} exists and is not a board; nothing changed")
    locate.save_config(ref)
    locate.clear_negative(key)
    return ref
