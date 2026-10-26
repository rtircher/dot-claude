"""Journaled sync: every change is an op replayed onto the remote tip."""
from __future__ import annotations

import fcntl
import json
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from quests import gitutil, locate, ops, store
from quests.locate import QuestsRef, slug, state_dir

MAX_ATTEMPTS = 5
# An interrupted push can still land, so a push gets at least this long by default.
PUSH_MIN = 10.0
# Outlasts the longest default hold: 5 s fetch, PUSH_MIN push, local git.
LOCK_WAIT = 20.0
_NO_HOOKS = ["-c", "core.hooksPath=/dev/null"]
_FALLBACK_IDENTITY = ["-c", "user.name=quests", "-c", "user.email=quests@users.noreply.invalid"]
_REJECTED = ("rejected", "non-fast-forward", "fetch first")


class QuestsBusy(Exception):
    """Another process held the quests lock for too long."""


@dataclass
class SyncResult:
    synced: bool
    warnings: list[str] = field(default_factory=list)
    # Set when pending ops were left unapplied because the log format is newer than ours.
    too_new: int | None = None


def run_git(args, cwd, timeout=None):
    return gitutil.run_git(args, cwd, timeout)


def checkout_dir(ref: QuestsRef) -> Path:
    return state_dir() / "checkouts" / slug(ref.key)


def _journal_path(ref: QuestsRef) -> Path:
    return state_dir() / "journal" / f"{slug(ref.key)}.jsonl"


def _lock(ref: QuestsRef, wait: float | None = None):
    return lock_slug(slug(ref.key), wait)


@contextmanager
def lock_slug(name: str, wait: float | None = None):
    """The per-repo lock, by slug (the journal file stem), for callers without a ref."""
    path = state_dir() / "locks" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        end = time.monotonic() + (LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise QuestsBusy(f"quests lock busy: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read_journal(ref: QuestsRef) -> tuple[list[dict], list[str]]:
    path = _journal_path(ref)
    items: list[dict] = []
    warnings: list[str] = []
    if not path.exists():
        return items, warnings
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            op = json.loads(line)
        except ValueError:
            warnings.append("skipped unreadable journal line")
            continue
        if isinstance(op, dict):
            items.append(op)
        else:
            warnings.append("skipped malformed journal entry")
    return items, warnings


class _Deadline:
    """Budget for the network calls of one sync/submit (R11); a push may run past it to its floor."""

    def __init__(self, timeout: float):
        self.end = time.monotonic() + timeout

    def net(self, args, cwd, floor: float = 0.0):
        """Run a network git call with the remaining budget (at least `floor`); None on timeout or OS failure."""
        left = max(self.end - time.monotonic(), floor)
        if left <= 0:
            return None
        try:
            return run_git(args, cwd, left)
        except (subprocess.TimeoutExpired, OSError):
            return None


def _local(args, cwd, check=True):
    p = run_git(args, cwd, None)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p


def _commit_ops(cwd: Path, journal: list[dict], warnings: list[str], commit: bool) -> None:
    ident: list[str] = []
    if commit:
        email = _local(["config", "user.email"], cwd, check=False).stdout.strip()
        if not email:
            ident = _FALLBACK_IDENTITY
    for op in journal:
        warnings += ops.apply_op(cwd, op)
        if not commit:
            continue
        if not _local(["status", "--porcelain"], cwd).stdout.strip():
            continue
        _local(["add", "-A"], cwd)
        msg = f"quests: {op.get('op', 'op')} {op.get('id', '')}".rstrip()
        _local([*_NO_HOOKS, *ident, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", msg], cwd)


def _too_new(cwd: Path, journal: list[dict]) -> int | None:
    """The log's format when pending ops must not be applied to it, else None."""
    if not journal:
        return None
    n = store.read_format(cwd)
    return n if n > store.FORMAT else None


def _reset_to_remote(cwd: Path, branch: str) -> bool:
    ref = f"refs/remotes/origin/{branch}"
    if _local(["show-ref", "--verify", "--quiet", ref], cwd, check=False).returncode != 0:
        return False
    _local([*_NO_HOOKS, "checkout", "-q", "-f", "-B", branch, ref], cwd)
    _local(["clean", "-fdq"], cwd)
    return True


def _at_remote_tip(cwd: Path, branch: str) -> bool:
    head = _local(["rev-parse", "HEAD"], cwd).stdout.strip()
    tip = _local(["rev-parse", f"refs/remotes/origin/{branch}"], cwd).stdout.strip()
    return head == tip


def _ensure_checkout(ref: QuestsRef, dl: _Deadline) -> tuple[Path, bool]:
    cwd = checkout_dir(ref)
    if (cwd / ".git").exists():
        cur = _local(["config", "--get", "remote.origin.url"], cwd, check=False).stdout.strip()
        if cur != ref.url:
            _local(["remote", "set-url", "origin", ref.url], cwd)
        return cwd, True
    existed = cwd.exists()
    cwd.parent.mkdir(parents=True, exist_ok=True)
    p = dl.net([*_NO_HOOKS, "clone", "-q", "--single-branch", "--branch", ref.branch, ref.url, str(cwd)], None)
    if p is None or p.returncode != 0:
        if not existed and cwd.exists():
            import shutil

            shutil.rmtree(cwd, ignore_errors=True)
        return cwd, False
    return cwd, True


def _clear_journal(ref: QuestsRef) -> None:
    _journal_path(ref).write_text("", encoding="utf-8")


def _sync(ref: QuestsRef, timeout: float, push_min: float, push: bool = True) -> SyncResult:
    dl = _Deadline(timeout)
    journal, jwarn = _read_journal(ref)
    cwd, ok = _ensure_checkout(ref, dl)
    if not ok:
        return SyncResult(False, ["quests remote unreachable"])
    last_warnings: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        warnings = list(jwarn)
        fetched = dl.net(["fetch", "-q", "origin", f"+refs/heads/{ref.branch}:refs/remotes/origin/{ref.branch}"], cwd)
        if fetched is None or fetched.returncode != 0:
            return _offline(cwd, ref, journal, warnings)
        if not _reset_to_remote(cwd, ref.branch):
            return SyncResult(False, warnings + ["quests branch missing on remote"])
        newer = _too_new(cwd, journal)
        if newer:
            return SyncResult(False, warnings, too_new=newer)
        _commit_ops(cwd, journal, warnings, commit=True)
        last_warnings = warnings
        if not journal:
            return SyncResult(True, warnings)
        if not push:
            # Read-only caller: show the pending ops, leave the push to the next normal sync.
            _reset_to_remote(cwd, ref.branch)
            _commit_ops(cwd, journal, warnings, commit=False)
            return SyncResult(False, warnings)
        if _at_remote_tip(cwd, ref.branch):
            # Every op is already on the remote, e.g. an earlier push landed but timed out.
            _clear_journal(ref)
            return SyncResult(True, warnings)
        pushed = dl.net(["push", "-q", "origin", f"HEAD:refs/heads/{ref.branch}"], cwd, floor=push_min)
        if pushed is not None and pushed.returncode == 0:
            _clear_journal(ref)
            return SyncResult(True, warnings)
        if pushed is None or not any(w in pushed.stderr for w in _REJECTED):
            return SyncResult(False, last_warnings + ["quests push failed; changes kept locally"])
    return SyncResult(False, last_warnings + ["quests push kept being rejected; changes kept locally"])


def _offline(cwd: Path, ref: QuestsRef, journal: list[dict], warnings: list[str]) -> SyncResult:
    if _reset_to_remote(cwd, ref.branch):
        newer = _too_new(cwd, journal)
        if newer:
            return SyncResult(False, warnings, too_new=newer)
        _commit_ops(cwd, journal, warnings, commit=False)
    return SyncResult(False, warnings)


def submit(ref: QuestsRef, op: dict, timeout: float = 5, lock_wait: float | None = None,
           push_min: float = PUSH_MIN) -> SyncResult:
    with _lock(ref, lock_wait):
        path = _journal_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(op, ensure_ascii=False) + "\n")
        return _sync(ref, timeout, push_min)


def sync(ref: QuestsRef, timeout: float = 5, lock_wait: float | None = None,
         push_min: float = PUSH_MIN, push: bool = True) -> SyncResult:
    with _lock(ref, lock_wait):
        return _sync(ref, timeout, push_min, push)
