"""The `board` command line. Claude sessions call this; it never prints a traceback."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from board import locate, render_html, setup, store, sync, views
from board.locate import BoardRef

NO_BOARD = "No board for this repo. Run: board init --mode same|external [--url URL]"
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
    p = _Parser(prog="board", description="Shared per-repo ticket board.")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    s = sub.add_parser("init", parents=[c])
    s.add_argument("--mode", choices=("same", "external"), required=True)
    s.add_argument("--url")
    for name in ("summary", "next", "sync"):
        sub.add_parser(name, parents=[c])
    for name in ("show", "claim", "release"):
        sub.add_parser(name, parents=[c]).add_argument("id")
    s = sub.add_parser("add", parents=[c])
    s.add_argument("title")
    s.add_argument("--goal")
    s.add_argument("--parent")
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
    g = sub.add_parser("goal", parents=[c])
    gs = g.add_subparsers(dest="goal_cmd", required=True, parser_class=_Parser)
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
        self.session = args.session or os.environ.get("BOARD_SESSION_ID") \
            or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
        self.label = os.environ.get("BOARD_SESSION_LABEL") or self.session[:8] or "cli"
        remote = os.environ.get("CLAUDE_CODE_REMOTE") == "true"
        self.where = os.environ.get("BOARD_WHERE") or ("cloud" if remote else "local")
        self.ref: BoardRef | None = None
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
        return store.load_board(d)

    def summary(self, board, limit=5) -> dict:
        sessions = views.load_sessions(locate.state_dir(), self.ref.key)
        return views.summary(board, sessions, datetime.now(timezone.utc), self.session,
                             self.synced, next_limit=limit)

    def op(self, name: str, **fields) -> dict:
        return {"op": name, "at": store.now_iso(), "session": self.session or "cli", **fields}

    def submit(self, op: dict) -> int:
        res = sync.submit(self.ref, op)
        self.synced = res.synced
        lost = False
        for w in res.warnings:
            print(f"warning: {w}", file=sys.stderr)
            lost = lost or "lost to" in w
        return 3 if lost else 0

    def tail(self) -> None:
        if not self.synced and not self.args.as_json:
            self.out(UNSYNCED)


def _not_fetched(ctx: _Ctx) -> int:
    ctx.emit({"repo": ctx.ref.key, "synced": False, "fetched": False},
             f"Board: {ctx.ref.key} (unsynced, not fetched yet)")
    return 0


def _find(board, tid: str):
    t = board.tickets.get(tid)
    if t is None:
        raise _Fail(f"no such ticket: {tid}")
    return t


class _Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _cmd_init(ctx: _Ctx) -> int:
    ref = setup.init(ctx.cwd, ctx.args.mode, ctx.args.url)
    ctx.emit(dataclasses.asdict(ref), f"Board ready: {ref.branch} on {ref.url}")
    return 0


def _cmd_summary(ctx: _Ctx) -> int:
    board, _ = ctx.load()
    if board is None:
        return _not_fetched(ctx)
    s = ctx.summary(board)
    ctx.emit(s, views.render_text(s))
    return 0


def _cmd_show(ctx: _Ctx) -> int:
    board, _ = ctx.load()
    if board is None:
        return _not_fetched(ctx)
    t = _find(board, ctx.args.id)
    lines = [f"{t.id}  {t.title}", f"status: {t.status}", f"goal: {t.goal or '-'}",
             f"parent: {t.parent or '-'}",
             "owner: " + (f"{t.owner.label} ({t.owner.where})" if t.owner else "-")]
    if t.links:
        lines.append("links: " + ", ".join(t.links))
    lines += [f"  {e.at} ({e.session}) {e.text}" for e in t.log]
    ctx.emit(dataclasses.asdict(t), "\n".join(lines))
    return 0


def _cmd_next(ctx: _Ctx) -> int:
    board, _ = ctx.load()
    if board is None:
        return _not_fetched(ctx)
    nxt = ctx.summary(board, limit=1)["next"]
    ctx.emit(nxt[0] if nxt else None, f"{nxt[0]['id']}  {nxt[0]['title']}" if nxt else "Nothing ready.")
    return 0


def _cmd_html(ctx: _Ctx) -> int:
    board, _ = ctx.load()
    if board is None:
        return _not_fetched(ctx)
    page = render_html.render_html(board, ctx.summary(board))
    if ctx.args.out:
        path = Path(ctx.args.out)
    else:
        path = locate.state_dir() / "html" / f"{locate.slug(ctx.ref.key)}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".board-", suffix=".tmp")
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
    res = sync.sync(ctx.ref)
    ctx.synced = res.synced
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    ctx.emit({"synced": res.synced}, "Synced." if res.synced else UNSYNCED)
    return 0


def _cmd_add(ctx: _Ctx) -> int:
    a = ctx.args
    board = ctx.load_local()
    existing = set(board.tickets) if board else set()
    goal = a.goal
    if a.parent and board and a.parent in board.tickets and not goal:
        goal = board.tickets[a.parent].goal
    tid = store.new_id("t", existing)
    code = ctx.submit(ctx.op("create_ticket", id=tid, title=a.title, goal=goal,
                             parent=a.parent, links=list(a.link)))
    ctx.emit({"id": tid, "synced": ctx.synced}, tid)
    ctx.tail()
    return code


def _cmd_claim(ctx: _Ctx) -> int:
    if not ctx.session:
        raise _Fail("claim needs a session id: pass --session or set BOARD_SESSION_ID")
    board, _ = ctx.load()
    if board is None:
        raise _Fail("board not fetched yet (remote unreachable); try again when online")
    t = _find(board, ctx.args.id)
    extra = {}
    if t.owner is not None and t.owner.session != ctx.session:
        stale = {x["id"] for x in ctx.summary(board)["stale"]}
        if t.id not in stale:
            ctx.emit({"id": t.id, "refused": True, "owner": t.owner.label},
                     f"Claim refused: {t.id} is owned by {t.owner.label}")
            return 3
        extra["takeover_from"] = t.owner.session
    owner = {"session": ctx.session, "label": ctx.label, "where": ctx.where,
             "claimed_at": store.now_iso()}
    code = ctx.submit(ctx.op("claim", id=t.id, owner=owner, **extra))
    if code == 3:
        ctx.out(f"Claim refused: {t.id} was claimed by another session first")
        return 3
    ctx.emit({"id": t.id, "synced": ctx.synced}, f"Claimed {t.id}")
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


def _cmd_goal(ctx: _Ctx) -> int:
    a = ctx.args
    if a.goal_cmd == "list":
        board, _ = ctx.load()
        if board is None:
            return _not_fetched(ctx)
        goals = ctx.summary(board)["goals"]
        ctx.emit(goals, "\n".join(f"{g['id']}  {g['title']}: {g['done']}/{g['total']}"
                                  for g in goals) or "No goals.")
        return 0
    board = ctx.load_local()
    existing = set(board.goals) if board else set()
    order = max((g.order for g in board.goals.values()), default=0) + 1 if board else 1
    gid = store.new_id("g", existing)
    code = ctx.submit(ctx.op("create_goal", id=gid, title=a.title, order=order, links=list(a.link)))
    ctx.emit({"id": gid, "synced": ctx.synced}, gid)
    ctx.tail()
    return code


_COMMANDS = {
    "summary": _cmd_summary, "html": _cmd_html, "show": _cmd_show, "next": _cmd_next, "sync": _cmd_sync,
    "add": _cmd_add, "claim": _cmd_claim, "note": _cmd_note, "goal": _cmd_goal,
    "release": _simple_write("release", "Released {id}"),
    "status": _simple_write("set_status", "Updated {id}", status="status"),
    "link": _simple_write("add_link", "Linked {id}", link="link"),
}


def _run(argv: list[str], cwd: Path) -> int:
    args = _parser().parse_args(argv)
    ctx = _Ctx(args, cwd)
    if args.cmd == "init":
        return _cmd_init(ctx)
    ctx.ref = locate.resolve(cwd)
    if ctx.ref is None:
        print(NO_BOARD)
        return 2
    return _COMMANDS[args.cmd](ctx)


def main(argv: list[str], cwd: Path | None = None) -> int:
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    try:
        return _run(argv, cwd)
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0
    except _Usage as e:
        print(f"board: {e}", file=sys.stderr)
        return 1
    except setup.SetupRefused as e:
        print(f"board: {e}")
        return 4
    except sync.BoardBusy:
        print("board: busy, another board command is running; try again shortly")
        return 5
    except _Fail as e:
        print(f"board: {e}")
        return e.code
    except Exception as e:  # never a traceback for users
        print(f"board: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
