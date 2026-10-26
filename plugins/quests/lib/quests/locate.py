"""Find which repo and branch hold the quest log for a working directory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from quests.gitutil import run_git

SAME_BRANCH = "claude/quests"
OLD_SAME_BRANCH = "claude/board"
OLD_EXTERNAL_PREFIX = "board/"
_LS_REMOTE_DEADLINE = 5.0
NEGATIVE_TTL = 3600.0


@dataclass
class QuestsRef:
    key: str
    mode: str  # "same" or "external"
    url: str
    branch: str


@dataclass
class Probe:
    """What resolve's network check listed: remote URL -> the branches present there.

    A URL is missing when it was not listed (not probed, unreachable or out of time).
    """
    heads: dict[str, set[str]] = field(default_factory=dict)


def state_dir() -> Path:
    env = os.environ.get("QUESTS_STATE_DIR")
    return Path(env) if env else Path.home() / ".claude" / "state" / "quests"


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


def save_config(ref: QuestsRef) -> None:
    cfg = _load_config()
    cfg[ref.key] = {"mode": ref.mode, "url": ref.url, "branch": ref.branch}
    write_config(cfg)


def write_config(cfg: dict) -> None:
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


def _remote_heads(url: str, branches: list[str], deadline: float, cwd: Path | None = None) -> set[str] | None:
    """Which of `branches` exist on `url`, in one round trip.

    None only when the remote could not be listed in time; a missing branch is never None.
    """
    left = deadline - time.monotonic()
    if left <= 0:
        return None
    try:
        p = run_git(["ls-remote", "--heads", url, *(f"refs/heads/{b}" for b in branches)], cwd, left)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    found = set()
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/") and parts[1][11:] in branches:
            found.add(parts[1][11:])
    return found


def _ref_exists(cwd: Path, ref: str) -> bool:
    try:
        return run_git(["show-ref", "--verify", "--quiet", ref], cwd).returncode == 0
    except OSError:
        return False


def is_old_branch(branch: str) -> bool:
    """A branch name from before the rename; the new plugin never reads or writes these."""
    return branch == OLD_SAME_BRANCH or branch.startswith(OLD_EXTERNAL_PREFIX)


def resolve(cwd: Path, deadline: float | None = None, probe: Probe | None = None) -> QuestsRef | None:
    """`deadline` is a time.monotonic() end shared with the caller's other network work.

    `probe`, when given, records what the remote listing saw (old branch names included).
    """
    cwd = Path(cwd)
    key = repo_key(cwd)
    if key is None:
        return None
    entry = _load_config().get(key)
    if isinstance(entry, dict) and all(isinstance(entry.get(k), str) for k in ("mode", "url", "branch")):
        if is_old_branch(entry["branch"]):
            return None  # needs `quest migrate`; never used as is, and not negative-cached
        return QuestsRef(key, entry["mode"], entry["url"], entry["branch"])
    if deadline is None:
        deadline = time.monotonic() + _LS_REMOTE_DEADLINE
    network = not _negative_fresh(key)
    ref = _discover(cwd, key, deadline, probe=network, seen=probe)
    if ref is not None:
        try:
            save_config(ref)
        except OSError:
            pass
    elif network:
        _mark_negative(key)
    return ref


def _discover(cwd: Path, key: str, deadline: float, probe: bool = True, seen: Probe | None = None) -> QuestsRef | None:
    seen = seen if seen is not None else Probe()
    external = os.environ.get("CLAUDE_QUESTS_REPO")
    if external and probe:
        s = slug(key)
        branch = f"quests/{s}"
        heads = _remote_heads(external, [branch, f"{OLD_EXTERNAL_PREFIX}{s}"], deadline, cwd)
        if heads is not None:
            seen.heads[external] = heads
            if branch in heads:
                return QuestsRef(key, "external", external, branch)
    origin = _origin_url(cwd)
    common = _common_dir(cwd)
    url = origin or common
    if url is None:
        return None
    if _ref_exists(cwd, f"refs/heads/{SAME_BRANCH}") or _ref_exists(cwd, f"refs/remotes/origin/{SAME_BRANCH}"):
        return QuestsRef(key, "same", url, SAME_BRANCH)
    if probe and origin is not None:
        heads = _remote_heads("origin", [SAME_BRANCH, OLD_SAME_BRANCH], deadline, cwd)
        if heads is not None:
            seen.heads[origin] = heads
            if SAME_BRANCH in heads:
                return QuestsRef(key, "same", url, SAME_BRANCH)
    return None
