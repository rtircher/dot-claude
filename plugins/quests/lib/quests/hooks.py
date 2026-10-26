"""Claude Code hook handlers: heartbeats, the startup summary, and cue capture.

Every entry point swallows exceptions (logged to state_dir()/hook-errors.log) and
exits 0, so a qlog problem can never fail a session.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from quests import cues, locate, migrate, store, sync, views

NO_QUESTS = 'Quests: none for this repo (say "set up quests" to create it).'
CLAIM_LINE = "Take a quest before starting work; file side quests with `quest side`."
PARK_CONTEXT = ("Quests cue: the user is parking something. File it with "
                "`quest side \"<title>\"` and confirm in one line.")
BTW_CONTEXT = "Quests cue: answer the btw first; if it turns into work, offer a ticket in one line."
SESSION_NET_BUDGET = 5.0
HOOK_LOCK_WAIT = 2.0
# Lock wait + fetch + push floor must stay under the SessionStart hook's 15 s timeout.
HOOK_SYNC_TIMEOUT = 4.0
HOOK_PUSH_MIN = 6.0
MAX_LINES = 25


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _git_out(cwd: Path, *args: str) -> str:
    try:
        p = locate.run_git(list(args), cwd, 5)
    except Exception:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def session_label(cwd: Path) -> str:
    cwd = Path(cwd)
    branch = _git_out(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    if branch:
        name = branch.rsplit("/", 1)[-1]
        name = re.sub(r"-[0-9a-f]{6}$", "", name)
        if name:
            return name
    top = _git_out(cwd, "rev-parse", "--show-toplevel")
    return Path(top or cwd).name or "session"


def where() -> str:
    return "cloud" if os.environ.get("CLAUDE_CODE_REMOTE") == "true" else "local"


def write_heartbeat(session: str, cwd: Path, state: str) -> None:
    """repo_key is null outside git; load_sessions then ignores the file."""
    if not session:
        return
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session)
    path = locate.state_dir() / "sessions" / f"{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"session": session, "label": session_label(cwd), "where": where(),
            "repo_key": locate.repo_key(cwd), "state": state, "last_seen": store.now_iso()}
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _write_env_file(session: str, cwd: Path) -> bool:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return False
    q = shlex.quote
    bindir = q(str(plugin_root() / "bin"))
    lines = [f"export QUESTS_SESSION_ID={q(session)}",
             f"export QUESTS_SESSION_LABEL={q(session_label(cwd))}",
             f"export QUESTS_WHERE={q(where())}",
             f'export PATH={bindir}":$PATH"']
    with open(env_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return True


def _summary_text(ref, session: str, push: bool = True) -> str:
    res = None
    try:
        res = sync.sync(ref, timeout=HOOK_SYNC_TIMEOUT, lock_wait=HOOK_LOCK_WAIT, push_min=HOOK_PUSH_MIN, push=push)
    except sync.QuestsBusy:
        pass
    synced = bool(res and res.synced)
    d = sync.checkout_dir(ref)
    if not (d / "board.json").exists():
        return f"Quests: {ref.key} (unsynced, not fetched yet)"
    qlog = store.load_quests(d)
    sessions = views.load_sessions(locate.state_dir(), ref.key)
    s = views.summary(qlog, sessions, datetime.now(timezone.utc), session, synced)
    return views.render_text(s)


def session_start(data: dict) -> list[str]:
    session = data.get("session_id") or ""
    cwd = Path(data.get("cwd") or os.getcwd())
    try:
        write_heartbeat(session, cwd, "active")
    except Exception:
        _log_error("session-start heartbeat")
    wrote_env = False
    if session:
        try:
            wrote_env = _write_env_file(session, cwd)
        except Exception:
            _log_error("session-start env file")
    # One 5 s network budget for resolve and the old-board migration together.
    net_end = time.monotonic() + SESSION_NET_BUDGET
    probe = locate.Probe()
    ref = locate.resolve(cwd, deadline=net_end, probe=probe)
    note = None
    migrated = False
    # Skipped when resolve's listing already saw no old branch: a second round trip can overrun the budget.
    if ref is None and not migrate.ruled_out(cwd, probe):
        # An old `board` branch is carried over once. A journal it moves is not pushed from here.
        ref, note = migrate.auto(cwd, deadline=net_end)
        migrated = ref is not None
    if ref is None:
        return [note or NO_QUESTS]
    extra = [CLAIM_LINE]
    if not wrote_env or where() == "cloud":
        extra.append(f"Quests CLI: {plugin_root() / 'bin' / 'quest'}; session: {session}")
    try:
        body = _summary_text(ref, session, push=not migrated).splitlines()
    except Exception:
        _log_error("session-start summary")
        body = [f"Quests: {ref.key} (unreadable; see hook-errors.log)"]
    if note:
        extra.insert(0, note)
    return body[:MAX_LINES - len(extra)] + extra


def prompt(data: dict) -> dict | None:
    write_heartbeat(data.get("session_id") or "", Path(data.get("cwd") or os.getcwd()), "active")
    kind = cues.match(data.get("prompt") or "")
    ctx = {"park": PARK_CONTEXT, "btw": BTW_CONTEXT}.get(kind)
    if ctx is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}


def _log_error(event: str) -> None:
    try:
        path = locate.state_dir() / "hook-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{store.now_iso()} {event}\n{traceback.format_exc()}\n")
    except Exception:
        pass


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    try:
        try:
            data = json.load(sys.stdin)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        cwd = Path(data.get("cwd") or os.getcwd())
        if event == "session-start":
            print("\n".join(session_start(data)))
        elif event == "prompt":
            out = prompt(data)
            if out is not None:
                print(json.dumps(out))
        elif event in ("stop", "end"):
            write_heartbeat(data.get("session_id") or "", cwd,
                            "waiting" if event == "stop" else "ended")
    except Exception:
        _log_error(event)
    return 0
