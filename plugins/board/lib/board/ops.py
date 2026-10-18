"""Journaled board operations. Replayable onto any tip; no git, no network."""
from __future__ import annotations

from pathlib import Path

from board import store
from board.store import Goal, LogEntry, Owner, Ticket


def _log(t: Ticket, op: dict, text: str) -> None:
    entry = LogEntry(op["at"], op["session"], text)
    if entry not in t.log:
        t.log.append(entry)


_STATUSES = ("todo", "in_progress", "blocked", "done", "dropped")
_REQUIRED = {
    "create_goal": ("id", "title"),
    "create_ticket": ("id", "title"),
    "claim": ("id", "owner"),
    "release": ("id",),
    "set_status": ("id", "status"),
    "note": ("id", "text"),
    "add_link": ("id", "link"),
    "set_goal": ("id", "goal"),
}
_OWNER_KEYS = ("session", "label", "claimed_at")


def _owner(d: dict) -> Owner:
    return Owner(d["session"], d["label"], d.get("where", "local"), d["claimed_at"])


def apply_op(root: Path, op: dict) -> list[str]:
    root = Path(root)
    name = op.get("op")
    handler = _HANDLERS.get(name)
    if handler is None:
        return [f"unknown op: {name}"]
    missing = [k for k in ("at", "session") + _REQUIRED[name] if k not in op]
    if name == "claim" and not missing:
        if not isinstance(op["owner"], dict):
            missing = ["owner"]
        else:
            missing = [f"owner.{k}" for k in _OWNER_KEYS if k not in op["owner"]]
    if missing:
        return [f"{name}: missing field(s) {', '.join(missing)}"]
    if name == "set_status" and op["status"] not in _STATUSES:
        return [f"set_status: invalid status {op['status']!r}"]
    board = store.load_board(root)
    return handler(root, board, op)


def _create_goal(root, board, op):
    if op["id"] in board.goals:
        return []
    store.write_goal(root, Goal(op["id"], op["title"], op.get("order", 0), list(op.get("links") or [])))
    return []


def _create_ticket(root, board, op):
    if op["id"] in board.tickets:
        return []
    t = Ticket(
        id=op["id"], title=op["title"], status="todo", goal=op.get("goal"),
        parent=op.get("parent"), blocked_by=[], owner=None,
        links=list(op.get("links") or []), created=op["at"], updated=op["at"],
        log=[LogEntry(op["at"], op["session"], "created")],
    )
    store.write_ticket(root, t)
    return []


def _with_ticket(fn):
    def handler(root, board, op):
        t = board.tickets.get(op["id"])
        if t is None:
            return [f"{op['op']}: unknown ticket {op['id']}"]
        before = t.updated
        warnings = fn(t, op)
        if warnings and t.updated == before:
            return warnings  # rejected without any change
        store.write_ticket(root, t)
        return warnings
    return handler


@_with_ticket
def _claim(t, op):
    if t.status in ("done", "dropped"):
        return [f"claim on {t.id} ignored: ticket is {t.status}"]
    new = _owner(op["owner"])
    cur = t.owner
    if cur is not None and cur.session != new.session:
        if op.get("takeover_from") == cur.session:
            _log(t, op, f"claim taken over from {cur.label}")
        else:
            _log(t, op, f"claim by {op['session']} lost to {cur.label}")
            t.updated = op["at"]
            return [f"claim on {t.id} by {op['session']} lost to {cur.label}"]
    t.owner = new
    if t.status in ("todo", "blocked"):
        t.status = "in_progress"
    t.updated = op["at"]
    return []


@_with_ticket
def _release(t, op):
    t.owner = None
    if t.status == "in_progress":
        t.status = "todo"
    t.updated = op["at"]
    return []


@_with_ticket
def _set_status(t, op):
    t.status = op["status"]
    if t.status in ("done", "dropped"):
        t.owner = None
    t.updated = op["at"]
    return []


@_with_ticket
def _note(t, op):
    _log(t, op, op["text"])
    t.updated = op["at"]
    return []


@_with_ticket
def _add_link(t, op):
    if op["link"] not in t.links:
        t.links.append(op["link"])
    t.updated = op["at"]
    return []


@_with_ticket
def _set_goal(t, op):
    t.goal = op["goal"]
    t.updated = op["at"]
    return []


_HANDLERS = {
    "create_goal": _create_goal,
    "create_ticket": _create_ticket,
    "claim": _claim,
    "release": _release,
    "set_status": _set_status,
    "note": _note,
    "add_link": _add_link,
    "set_goal": _set_goal,
}
