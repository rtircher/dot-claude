"""Carry a board made by the plugin's old name (`board`) over to the quests names.

Everything here only adds: the quests branch is created at the very same commit as
the old branch (no rewrite), the old branch, the old state directory's config and
checkouts are never modified or deleted. The one thing that moves is a non-empty
pending journal, so its ops replay onto the new branch on the next sync.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from quests import locate
from quests.gitutil import run_git
from quests.locate import SAME_BRANCH, QuestsRef, slug, state_dir

OLD_SAME_BRANCH = "claude/board"
OLD_EXTERNAL_PREFIX = "board/"
OLD_ENV_REPO = "CLAUDE_BOARD_REPO"
OLD_MARKER = "board.json"
AUTO_BUDGET = 5.0
AUTO_TTL = 3600.0
_NO_HOOKS = ["-c", "core.hooksPath=/dev/null"]


class MigrateError(Exception):
    """Migration could not finish; nothing was changed that is not already described."""

    def __init__(self, msg: str, found: bool = False):
        super().__init__(msg)
        self.found = found


@dataclass
class Outcome:
    lines: list[str] = field(default_factory=list)
    found: bool = False  # an old board was seen
    ref: QuestsRef | None = None  # the quests board to use afterwards, if one now exists
    created: list[str] = field(default_factory=list)  # new branches this run created


def old_state_dir() -> Path:
    env = os.environ.get("BOARD_STATE_DIR")
    return Path(env) if env else Path.home() / ".claude" / "state" / "board"


class _Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def left(self) -> float:
        left = self.end - time.monotonic()
        if left <= 0:
            raise MigrateError("timed out")
        return left


def _git(dl: _Deadline, args: list[str], cwd: Path | None):
    try:
        return run_git(args, cwd, dl.left())
    except subprocess.TimeoutExpired:
        raise MigrateError(f"git {args[0]} timed out")
    except OSError as e:
        raise MigrateError(f"cannot run git ({e})")


def _tip(dl: _Deadline, url: str, branch: str, cwd: Path | None) -> str | None:
    """Commit the branch points to on `url`, or None when it is absent."""
    p = _git(dl, ["ls-remote", "--heads", url, f"refs/heads/{branch}"], cwd)
    if p.returncode != 0:
        raise MigrateError(f"cannot reach {url}")
    out = p.stdout.split()
    return out[0] if out else None


def _is_marker(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def migrate_branch(url: str, old: str, new: str, cwd: Path | None, dl: _Deadline) -> tuple[str, str]:
    """Create `new` at the commit `old` points to. Returns (status, short sha).

    status: exists | missing | unmarked | created
    """
    have = _tip(dl, url, new, cwd)
    if have is not None:
        return "exists", have[:7]
    if _tip(dl, url, old, cwd) is None:
        return "missing", ""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _git(dl, ["init", "-q"], t)
        f = _git(dl, [*_NO_HOOKS, "fetch", "-q", url, f"refs/heads/{old}"], t)
        if f.returncode != 0:
            raise MigrateError(f"cannot fetch {old} from {url}", found=True)
        show = _git(dl, ["show", f"FETCH_HEAD:{OLD_MARKER}"], t)
        if show.returncode != 0 or not _is_marker(show.stdout):
            return "unmarked", ""
        sha = _git(dl, ["rev-parse", "FETCH_HEAD"], t).stdout.strip()
        p = _git(dl, ["push", "-q", url, f"{sha}:refs/heads/{new}"], t)
        if p.returncode != 0:
            raise MigrateError(f"push of {new} to {url} failed: {p.stderr.strip()}", found=True)
    return "created", sha[:7]


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def migrate_state() -> list[str]:
    """Copy old config entries the new config lacks; move pending journals across."""
    lines: list[str] = []
    old = old_state_dir()
    new = state_dir()
    if old.resolve() == new.resolve():
        return lines
    old_cfg = _read_json(old / "config.json")
    cfg = locate._load_config()
    added = [k for k in old_cfg if k not in cfg and isinstance(old_cfg[k], dict)]
    if added:
        for k in added:
            cfg[k] = old_cfg[k]
        locate.write_config(cfg)
        lines.append(f"Copied {len(added)} config entr{'y' if len(added) == 1 else 'ies'} to {new}.")
    jdir = old / "journal"
    if jdir.is_dir():
        for src in sorted(jdir.glob("*.jsonl")):
            try:
                text = src.read_text(encoding="utf-8")
            except OSError:
                continue
            ops = [ln for ln in text.splitlines() if ln.strip()]
            if not ops:
                continue
            dest = new / "journal" / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "a", encoding="utf-8") as fh:
                fh.write("\n".join(ops) + "\n")
            src.write_text("", encoding="utf-8")
            lines.append(f"Moved {len(ops)} pending journal entr{'y' if len(ops) == 1 else 'ies'} "
                         f"({src.stem}) to {new / 'journal'}.")
    return lines


def _targets(cwd: Path, key: str) -> list[tuple[str, str, str, str]]:
    """(mode, url, old branch, new branch) for each old board this repo may have."""
    out: list[tuple[str, str, str, str]] = []
    entry = locate._load_config().get(key)
    if isinstance(entry, dict) and all(isinstance(entry.get(k), str) for k in ("mode", "url", "branch")):
        b = entry["branch"]
        if b == OLD_SAME_BRANCH:
            return [(entry["mode"], entry["url"], b, SAME_BRANCH)]
        if b.startswith(OLD_EXTERNAL_PREFIX):
            return [(entry["mode"], entry["url"], b, "quests/" + b[len(OLD_EXTERNAL_PREFIX):])]
        if b == SAME_BRANCH:
            return [(entry["mode"], entry["url"], OLD_SAME_BRANCH, b)]
        if b.startswith("quests/"):
            return [(entry["mode"], entry["url"], OLD_EXTERNAL_PREFIX + b[len("quests/"):], b)]
        return []  # something custom: leave it
    external = os.environ.get("CLAUDE_QUESTS_REPO") or os.environ.get(OLD_ENV_REPO)
    if external:
        s = slug(key)
        out.append(("external", external, f"{OLD_EXTERNAL_PREFIX}{s}", f"quests/{s}"))
    url = locate._origin_url(cwd) or locate._common_dir(cwd)
    if url:
        out.append(("same", url, OLD_SAME_BRANCH, SAME_BRANCH))
    return out


def migrate(cwd: Path, budget: float = 30.0) -> Outcome:
    """Migrate state, then this repo's old board branch. Raises MigrateError."""
    cwd = Path(cwd)
    dl = _Deadline(budget)
    key = locate.repo_key(cwd)
    if key is None:
        raise MigrateError("not inside a git repository")
    out = Outcome()
    try:
        out.lines += migrate_state()
    except OSError as e:
        out.lines.append(f"Could not carry the old state over ({e}); continuing.")
    for mode, url, old, new in _targets(cwd, key):
        status, sha = migrate_branch(url, old, new, cwd, dl)
        ref = QuestsRef(key, mode, url, new)
        if status == "created":
            out.found = True
            out.created.append(new)
            out.ref = out.ref or ref
            out.lines.append(f"Created {new} at {sha}, the same commit as {old}. "
                             f"{old} was left untouched.")
        elif status == "exists":
            out.ref = out.ref or ref
            out.lines.append(f"{new} already exists; nothing to do.")
        elif status == "unmarked":
            out.found = True
            out.lines.append(f"{old} exists but is not an old board (no {OLD_MARKER}); left alone.")
    if out.ref is not None:
        entry = locate._load_config().get(key)
        if entry is None or _is_old_entry(entry):
            locate.save_config(out.ref)
        locate.clear_negative(key)
    if not out.lines:
        out.lines.append("No old board found for this repo; nothing to migrate.")
    return out


def _is_old_entry(entry) -> bool:
    b = entry.get("branch") if isinstance(entry, dict) else None
    return isinstance(b, str) and (b == OLD_SAME_BRANCH or b.startswith(OLD_EXTERNAL_PREFIX))


def _gate_path() -> Path:
    return state_dir() / "migrate-attempts.json"


def _gate_load() -> dict:
    return _read_json(_gate_path())


def _gate_set(key: str, failed_found: bool) -> None:
    data = _gate_load()
    data[key] = [time.time(), failed_found]
    path = _gate_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def auto(cwd: Path) -> tuple[QuestsRef | None, str | None]:
    """SessionStart: migrate an old board once. Returns (ref or None, one-line note or None).

    Never raises. A failed attempt is not retried for AUTO_TTL; the hint is repeated meanwhile.
    """
    hint = 'Quests: an old board was found but not migrated yet; run `quest migrate`.'
    try:
        key = locate.repo_key(cwd)
        if key is None:
            return None, None
        prior = _gate_load().get(key)
        if isinstance(prior, list) and len(prior) == 2 and isinstance(prior[0], (int, float)) \
                and 0 <= time.time() - prior[0] < AUTO_TTL:
            return None, (hint if prior[1] else None)
        try:
            res = migrate(cwd, budget=AUTO_BUDGET)
        except MigrateError as e:
            _gate_set(key, e.found)
            _log(f"auto-migrate: {e}")
            return None, (hint if e.found else None)
        except Exception as e:  # never fail a session
            _gate_set(key, False)
            _log(f"auto-migrate: {type(e).__name__}: {e}")
            return None, None
        _gate_set(key, False)
        if res.created:
            return res.ref, f"Quests: migrated the old board to {', '.join(res.created)} (the old branch is untouched)."
        return res.ref, None
    except Exception:
        return None, None


def _log(msg: str) -> None:
    try:
        path = state_dir() / "hook-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{msg}\n")
    except OSError:
        pass
