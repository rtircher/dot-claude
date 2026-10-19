"""Journaled sync: every change is an op replayed onto the remote tip."""
from __future__ import annotations

import fcntl
import json
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from board import gitutil, locate, ops
from board.locate import BoardRef, slug, state_dir

LOCK_WAIT = 10.0
MAX_ATTEMPTS = 5
_NO_HOOKS = ["-c", "core.hooksPath=/dev/null"]
_FALLBACK_IDENTITY = ["-c", "user.name=board", "-c", "user.email=board@users.noreply.invalid"]
_REJECTED = ("rejected", "non-fast-forward", "fetch first")


class BoardBusy(Exception):
    """Another process held the board lock for too long."""


@dataclass
class SyncResult:
    synced: bool
    warnings: list[str] = field(default_factory=list)


def run_git(args, cwd, timeout=None):
    return gitutil.run_git(args, cwd, timeout)


def checkout_dir(ref: BoardRef) -> Path:
    return state_dir() / "checkouts" / slug(ref.key)


def _journal_path(ref: BoardRef) -> Path:
    return state_dir() / "journal" / f"{slug(ref.key)}.jsonl"


@contextmanager
def _lock(ref: BoardRef, wait: float | None = None):
    path = state_dir() / "locks" / f"{slug(ref.key)}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        end = time.monotonic() + (LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise BoardBusy(f"board lock busy: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _read_journal(ref: BoardRef) -> tuple[list[dict], list[str]]:
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
    """Overall budget for the network calls of one sync/submit (R11)."""

    def __init__(self, timeout: float):
        self.end = time.monotonic() + timeout

    def net(self, args, cwd):
        """Run a network git call with the remaining budget; None on timeout or OS failure."""
        left = self.end - time.monotonic()
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
        msg = f"board: {op.get('op', 'op')} {op.get('id', '')}".rstrip()
        _local([*_NO_HOOKS, *ident, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", msg], cwd)


def _reset_to_remote(cwd: Path, branch: str) -> bool:
    ref = f"refs/remotes/origin/{branch}"
    if _local(["show-ref", "--verify", "--quiet", ref], cwd, check=False).returncode != 0:
        return False
    _local([*_NO_HOOKS, "checkout", "-q", "-f", "-B", branch, ref], cwd)
    _local(["clean", "-fdq"], cwd)
    return True


def _ensure_checkout(ref: BoardRef, dl: _Deadline) -> tuple[Path, bool]:
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


def _sync(ref: BoardRef, timeout: float) -> SyncResult:
    dl = _Deadline(timeout)
    journal, jwarn = _read_journal(ref)
    cwd, ok = _ensure_checkout(ref, dl)
    if not ok:
        return SyncResult(False, ["board remote unreachable"])
    last_warnings: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        warnings = list(jwarn)
        fetched = dl.net(["fetch", "-q", "origin", f"+refs/heads/{ref.branch}:refs/remotes/origin/{ref.branch}"], cwd)
        if fetched is None or fetched.returncode != 0:
            return _offline(cwd, ref, journal, warnings)
        if not _reset_to_remote(cwd, ref.branch):
            return SyncResult(False, warnings + ["board branch missing on remote"])
        _commit_ops(cwd, journal, warnings, commit=True)
        last_warnings = warnings
        if not journal:
            return SyncResult(True, warnings)
        pushed = dl.net(["push", "-q", "origin", f"HEAD:refs/heads/{ref.branch}"], cwd)
        if pushed is not None and pushed.returncode == 0:
            _journal_path(ref).write_text("", encoding="utf-8")
            return SyncResult(True, warnings)
        if pushed is None or not any(w in pushed.stderr for w in _REJECTED):
            return SyncResult(False, last_warnings + ["board push failed; changes kept locally"])
    return SyncResult(False, last_warnings + ["board push kept being rejected; changes kept locally"])


def _offline(cwd: Path, ref: BoardRef, journal: list[dict], warnings: list[str]) -> SyncResult:
    if _reset_to_remote(cwd, ref.branch):
        _commit_ops(cwd, journal, warnings, commit=False)
    return SyncResult(False, warnings)


def submit(ref: BoardRef, op: dict, timeout: float = 5, lock_wait: float | None = None) -> SyncResult:
    with _lock(ref, lock_wait):
        path = _journal_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(op, ensure_ascii=False) + "\n")
        return _sync(ref, timeout)


def sync(ref: BoardRef, timeout: float = 5, lock_wait: float | None = None) -> SyncResult:
    with _lock(ref, lock_wait):
        return _sync(ref, timeout)
