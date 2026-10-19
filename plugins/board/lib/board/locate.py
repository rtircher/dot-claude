"""Find which repo and branch hold the board for a working directory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from board.gitutil import run_git

SAME_BRANCH = "claude/board"
_LS_REMOTE_DEADLINE = 5.0
NEGATIVE_TTL = 3600.0


@dataclass
class BoardRef:
    key: str
    mode: str  # "same" or "external"
    url: str
    branch: str


def state_dir() -> Path:
    env = os.environ.get("BOARD_STATE_DIR")
    return Path(env) if env else Path.home() / ".claude" / "state" / "board"


def slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key.lower())


def _git(cwd: Path, *args: str, timeout: float | None = None) -> str | None:
    try:
        p = run_git(list(args), cwd, timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _common_dir(cwd: Path) -> str | None:
    out = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(out).resolve()) if out else None


def _origin_url(cwd: Path) -> str | None:
    return _git(cwd, "config", "--get", "remote.origin.url") or None


def normalize_url(url: str) -> str:
    u = url.strip()
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u, flags=re.I)
    u = re.sub(r"^[^@/]+@", "", u)
    u = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", u)  # scp style host:path
    u = re.sub(r"^([^/:]+):\d+/", r"\1/", u)  # host:port/path
    u = u.rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    host, sep, rest = u.partition("/")
    return host.lower() + sep + rest


def repo_key(cwd: Path) -> str | None:
    common = _common_dir(Path(cwd))
    if common is None:
        return None
    origin = _origin_url(Path(cwd))
    if origin:
        return normalize_url(origin)
    return "local-" + hashlib.sha1(common.encode("utf-8")).hexdigest()[:10]


def _config_path() -> Path:
    return state_dir() / "config.json"


def _load_config() -> dict:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(ref: BoardRef) -> None:
    cfg = _load_config()
    cfg[ref.key] = {"mode": ref.mode, "url": ref.url, "branch": ref.branch}
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _negative_path() -> Path:
    return state_dir() / "negative.json"


def _load_negative() -> dict:
    try:
        data = json.loads(_negative_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _negative_fresh(key: str) -> bool:
    ts = _load_negative().get(key)
    return isinstance(ts, (int, float)) and 0 <= time.time() - ts < NEGATIVE_TTL


def _write_negative(data: dict) -> None:
    path = _negative_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _mark_negative(key: str) -> None:
    data = _load_negative()
    data[key] = time.time()
    try:
        _write_negative(data)
    except OSError:
        pass


def clear_negative(key: str) -> None:
    data = _load_negative()
    if key in data:
        del data[key]
        try:
            _write_negative(data)
        except OSError:
            pass


def _remote_has_branch(url: str, branch: str, deadline: float, cwd: Path | None = None) -> bool:
    left = deadline - time.monotonic()
    if left <= 0:
        return False
    try:
        p = run_git(["ls-remote", "--exit-code", "--heads", url, f"refs/heads/{branch}"], cwd, left)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def _ref_exists(cwd: Path, ref: str) -> bool:
    try:
        return run_git(["show-ref", "--verify", "--quiet", ref], cwd).returncode == 0
    except OSError:
        return False


def resolve(cwd: Path) -> BoardRef | None:
    cwd = Path(cwd)
    key = repo_key(cwd)
    if key is None:
        return None
    entry = _load_config().get(key)
    if isinstance(entry, dict) and all(isinstance(entry.get(k), str) for k in ("mode", "url", "branch")):
        return BoardRef(key, entry["mode"], entry["url"], entry["branch"])
    deadline = time.monotonic() + _LS_REMOTE_DEADLINE
    probe = not _negative_fresh(key)
    ref = _discover(cwd, key, deadline, probe=probe)
    if ref is not None:
        try:
            save_config(ref)
        except OSError:
            pass
    elif probe:
        _mark_negative(key)
    return ref


def _discover(cwd: Path, key: str, deadline: float, probe: bool = True) -> BoardRef | None:
    external = os.environ.get("CLAUDE_BOARD_REPO")
    if external and probe:
        branch = f"board/{slug(key)}"
        if _remote_has_branch(external, branch, deadline, cwd):
            return BoardRef(key, "external", external, branch)
    origin = _origin_url(cwd)
    common = _common_dir(cwd)
    url = origin or common
    if url is None:
        return None
    if (
        _ref_exists(cwd, f"refs/heads/{SAME_BRANCH}")
        or _ref_exists(cwd, f"refs/remotes/origin/{SAME_BRANCH}")
        or (probe and origin is not None and _remote_has_branch("origin", SAME_BRANCH, deadline, cwd))
    ):
        return BoardRef(key, "same", url, SAME_BRANCH)
    return None
