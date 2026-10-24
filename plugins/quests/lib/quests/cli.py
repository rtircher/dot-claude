"""The `quest` command line. Claude sessions call this; it never prints a traceback."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from quests import locate, render_html, setup, store, sync, views
from quests.locate import QuestsRef

NO_QUESTS = "No quest log for this repo. Run: quest init --mode same|external [--url URL]"
UNSYNCED = "(unsynced: will push on next sync)"
STATUSES = ("todo", "in_progress", "blocked", "done", "dropped")


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--session")
    return p


def _parser() -> argparse.ArgumentParser:
    c = _common()
    p = _Parser(prog="quest", description="Shared per-repo quest log.")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    s = sub.add_parser("init", parents=[c])
    s.add_argument("--mode", choices=("same", "external"), required=True)
    s.add_argument("--url")
    for name in ("next", "sync"):
        sub.add_parser(name, parents=[c])
    sub.add_parser("log", parents=[c]).add_argument("--next-limit", type=int, default=5)
    for name in ("show", "take", "drop", "done"):
        sub.add_parser(name, parents=[c]).add_argument("id")
    s = sub.add_parser("add", parents=[c])
    s.add_argument("title")
    s.add_argument("--main", dest="goal")
    s.add_argument("--parent")
    s.add_argument("--link", action="append", default=[])
    s = sub.add_parser("side", parents=[c])
    s.add_argument("title")
    s.add_argument("--link", action="append", default=[])
    s = sub.add_parser("status", parents=[c])
    s.add_argument("id")
    s.add_argument("status", choices=STATUSES)
    s = sub.add_parser("note", parents=[c])
    s.add_argument("id")
    s.add_argument("text")
    s = sub.add_parser("link", parents=[c])
    s.add_argument("id")
    s.add_argument("link")
    g = sub.add_parser("main", parents=[c])
    gs = g.add_subparsers(dest="main_cmd", required=True, parser_class=_Parser)
    a = gs.add_parser("add", parents=[c])
    a.add_argument("title")
    a.add_argument("--link", action="append", default=[])
    gs.add_parser("list", parents=[c])
    sub.add_parser("html", parents=[c]).add_argument("--out")
    return p


class _Ctx:
    def __init__(self, args, cwd: Path):
        self.args = args
        self.cwd = cwd
        self.session = args.session or os.environ.get("QUESTS_SESSION_ID") \
            or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
        self.label = os.environ.get("QUESTS_SESSION_LABEL") or self.session[:8] or "cli"
        remote = os.environ.get("CLAUDE_CODE_REMOTE") == "true"
        self.where = os.environ.get("QUESTS_WHERE") or ("cloud" if remote else "local")
        self.ref: QuestsRef | None = None
        self.synced = True

    def out(self, text: str = "") -> None:
        print(text)

    def emit(self, obj, text: str) -> None:
        self.out(json.dumps(obj, indent=2, ensure_ascii=False) if self.args.as_json else text)

    def load(self):
        """Sync (reads) and load the checkout; None when nothing has been fetched yet."""
        res = sync.sync(self.ref)
        self.synced = res.synced
        return self.load_local(), res

    def load_local(self):
        d = sync.checkout_dir(self.ref)
        if not (d / "board.json").exists():
            return None
        return store.load_quests(d)

    def summary(self, qlog, limit=5) -> dict:
        sessions = views.load_sessions(locate.state_dir(), self.ref.key)
        return views.summary(qlog, sessions, datetime.now(timezone.utc), self.session,
                             self.synced, next_limit=limit)

    def op(self, name: str, **fields) -> dict:
        return {"op": name, "at": store.now_iso(), "session": self.session or "cli", **fields}

    def submit(self, op: dict) -> int:
        res = sync.submit(self.ref, op)
        self.synced = res.synced
        lost = False
        needle = (f"claim on {op['id']} by {op['session']} lost to"
                  if op.get("op") == "claim" else None)
        for w in res.warnings:
            print(f"warning: {w}", file=sys.stderr)
            lost = lost or (needle is not None and needle in w)
        return 3 if lost else 0

    def tail(self) -> None:
        if not self.synced and not self.args.as_json:
            self.out(UNSYNCED)


def _not_fetched(ctx: _Ctx) -> int:
    ctx.emit({"repo": ctx.ref.key, "synced": False, "fetched": False},
             f"Quests: {ctx.ref.key} (unsynced, not fetched yet)")
    return 0


def _find(qlog, tid: str):
    t = qlog.tickets.get(tid)
    if t is None:
        raise _Fail(f"no such ticket: {tid}")
    return t


class _Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _cmd_init(ctx: _Ctx) -> int:
    ref = setup.init(ctx.cwd, ctx.args.mode, ctx.args.url)
    ctx.emit(dataclasses.asdict(ref), f"Quests ready: {ref.branch} on {ref.url}")
    return 0


def _cmd_log(ctx: _Ctx) -> int:
    qlog, _ = ctx.load()
    if qlog is None:
        return _not_fetched(ctx)
    s = ctx.summary(qlog, limit=max(0, ctx.args.next_limit))
    ctx.emit(s, views.render_text(s))
    return 0


def _cmd_show(ctx: _Ctx) -> int:
    qlog, _ = ctx.load()
    if qlog is None:
        return _not_fetched(ctx)
    t = _find(qlog, ctx.args.id)
    lines = [f"{t.id}  {t.title}", f"status: {t.status}", f"main quest: {t.goal or '-'}",
             f"parent: {t.parent or '-'}",
             "owner: " + (f"{t.owner.label} ({t.owner.where})" if t.owner else "-")]
    if t.links:
        lines.append("links: " + ", ".join(t.links))
    lines += [f"  {e.at} ({e.session}) {e.text}" for e in t.log]
    ctx.emit(dataclasses.asdict(t), "\n".join(lines))
    return 0


def _cmd_next(ctx: _Ctx) -> int:
    qlog, _ = ctx.load()
    if qlog is None:
        return _not_fetched(ctx)
    nxt = ctx.summary(qlog, limit=1)["next"]
    ctx.emit(nxt[0] if nxt else None, f"{nxt[0]['id']}  {nxt[0]['title']}" if nxt else "Nothing ready.")
    return 0


def _cmd_html(ctx: _Ctx) -> int:
    qlog, _ = ctx.load()
    if qlog is None:
        return _not_fetched(ctx)
    page = render_html.render_html(qlog, ctx.summary(qlog))
    if ctx.args.out:
        path = Path(ctx.args.out)
    else:
        path = locate.state_dir() / "html" / f"{locate.slug(ctx.ref.key)}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".quests-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    ctx.emit({"path": str(path)}, str(path))
    return 0


def _cmd_sync(ctx: _Ctx) -> int:
    locate.clear_negative(ctx.ref.key)
    res = sync.sync(ctx.ref)
    ctx.synced = res.synced
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    ctx.emit({"synced": res.synced}, "Synced." if res.synced else UNSYNCED)
    return 0


def _cmd_add(ctx: _Ctx) -> int:
    a = ctx.args
    qlog = ctx.load_local()
    existing = set(qlog.tickets) if qlog else set()
    goal = a.goal
    if a.parent and qlog and a.parent in qlog.tickets and not goal:
        goal = qlog.tickets[a.parent].goal
    tid = store.new_id("t", existing)
    code = ctx.submit(ctx.op("create_ticket", id=tid, title=a.title, goal=goal,
                             parent=a.parent, links=list(a.link)))
    ctx.emit({"id": tid, "synced": ctx.synced}, tid)
    ctx.tail()
    return code


def _cmd_take(ctx: _Ctx) -> int:
    if not ctx.session:
        raise _Fail("take needs a session id: pass --session or set QUESTS_SESSION_ID")
    qlog, _ = ctx.load()
    if qlog is None:
        raise _Fail("quest log not fetched yet (remote unreachable); try again when online")
    t = _find(qlog, ctx.args.id)
    extra = {}
    if t.owner is not None and t.owner.session != ctx.session:
        stale = {x["id"] for x in ctx.summary(qlog)["stale"]}
        if t.id not in stale:
            ctx.emit({"id": t.id, "refused": True, "owner": t.owner.label},
                     f"Take refused: {t.id} is owned by {t.owner.label}")
            return 3
        extra["takeover_from"] = t.owner.session
    owner = {"session": ctx.session, "label": ctx.label, "where": ctx.where,
             "claimed_at": store.now_iso()}
    code = ctx.submit(ctx.op("claim", id=t.id, owner=owner, **extra))
    if code == 3:
        ctx.out(f"Take refused: {t.id} was taken by another session first")
        return 3
    ctx.emit({"id": t.id, "synced": ctx.synced}, f"Took {t.id}")
    ctx.tail()
    return code


def _cmd_side(ctx: _Ctx) -> int:
    """File a quest under the quest this session is on, so it cannot be lost."""
    a = ctx.args
    qlog, _ = ctx.load()
    if qlog is None:
        raise _Fail("quest log not fetched yet (remote unreachable); try again when online")
    cur = views.current_ticket(qlog, ctx.session) if ctx.session else None
    if cur is None:
        print("quest: this session has no current quest to hang a side quest on; "
              "use `quest add` instead")
        return 2
    tid = store.new_id("t", set(qlog.tickets))
    code = ctx.submit(ctx.op("create_ticket", id=tid, title=a.title, goal=cur.goal,
                             parent=cur.id, links=list(a.link)))
    ctx.emit({"id": tid, "parent": cur.id, "synced": ctx.synced}, tid)
    ctx.tail()
    return code


def _cmd_done(ctx: _Ctx) -> int:
    qlog, _ = ctx.load()
    t = qlog.tickets.get(ctx.args.id) if qlog else None
    code = ctx.submit(ctx.op("set_status", id=ctx.args.id, status="done"))
    parent = qlog.tickets.get(t.parent) if t is not None and t.parent else None
    back = parent if parent is not None and parent.status != "done" else None
    obj = {"id": ctx.args.id, "synced": ctx.synced}
    text = f"Done {ctx.args.id}"
    if back is not None:
        obj["back_to"] = {"id": back.id, "title": back.title}
        text += f"\nBack to: {back.id} {back.title}  (run: quest take {back.id})"
    ctx.emit(obj, text)
    ctx.tail()
    return code


def _simple_write(name: str, msg: str, **fields_from_args):
    def run(ctx: _Ctx) -> int:
        fields = {k: getattr(ctx.args, v) for k, v in fields_from_args.items()}
        code = ctx.submit(ctx.op(name, id=ctx.args.id, **fields))
        ctx.emit({"id": ctx.args.id, "synced": ctx.synced}, msg.format(id=ctx.args.id))
        ctx.tail()
        return code
    return run


def _cmd_note(ctx: _Ctx) -> int:
    text = " / ".join(ctx.args.text.splitlines()) or ctx.args.text
    code = ctx.submit(ctx.op("note", id=ctx.args.id, text=text))
    ctx.emit({"id": ctx.args.id, "synced": ctx.synced}, f"Noted {ctx.args.id}")
    ctx.tail()
    return code


def _cmd_main(ctx: _Ctx) -> int:
    a = ctx.args
    if a.main_cmd == "list":
        qlog, _ = ctx.load()
        if qlog is None:
            return _not_fetched(ctx)
        goals = ctx.summary(qlog)["goals"]
        ctx.emit(goals, "\n".join(f"{g['id']}  {g['title']}: {g['done']}/{g['total']}"
                                  for g in goals) or "No main quests.")
        return 0
    qlog = ctx.load_local()
    existing = set(qlog.goals) if qlog else set()
    order = max((g.order for g in qlog.goals.values()), default=0) + 1 if qlog else 1
    gid = store.new_id("g", existing)
    code = ctx.submit(ctx.op("create_goal", id=gid, title=a.title, order=order, links=list(a.link)))
    ctx.emit({"id": gid, "synced": ctx.synced}, gid)
    ctx.tail()
    return code


_COMMANDS = {
    "log": _cmd_log, "html": _cmd_html, "show": _cmd_show, "next": _cmd_next, "sync": _cmd_sync,
    "add": _cmd_add, "take": _cmd_take, "note": _cmd_note, "main": _cmd_main, "side": _cmd_side, "done": _cmd_done,
    "drop": _simple_write("release", "Dropped {id}"),
    "status": _simple_write("set_status", "Updated {id}", status="status"),
    "link": _simple_write("add_link", "Linked {id}", link="link"),
}


def _run(argv: list[str], cwd: Path) -> int:
    args = _parser().parse_args(argv)
    ctx = _Ctx(args, cwd)
    if args.cmd == "init":
        return _cmd_init(ctx)
    if args.cmd == "sync":
        key = locate.repo_key(cwd)
        if key is not None:
            locate.clear_negative(key)
    ctx.ref = locate.resolve(cwd)
    if ctx.ref is None:
        print(NO_QUESTS)
        return 2
    return _COMMANDS[args.cmd](ctx)


def main(argv: list[str], cwd: Path | None = None) -> int:
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    try:
        return _run(argv, cwd)
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0
    except _Usage as e:
        print(f"quest: {e}", file=sys.stderr)
        return 1
    except setup.SetupRefused as e:
        print(f"quest: {e}")
        return 4
    except sync.QuestsBusy:
        print("quest: busy, another quest command is running; try again shortly")
        return 5
    except _Fail as e:
        print(f"quest: {e}")
        return e.code
    except Exception as e:  # never a traceback for users
        print(f"quest: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
