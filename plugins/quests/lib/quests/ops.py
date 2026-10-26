"""Journaled quest log operations. Replayable onto any tip; no git, no network."""
from __future__ import annotations

from pathlib import Path

from quests import store, views
from quests.store import Goal, LogEntry, Owner, Ticket


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
    "move_goal": ("id", "to"),
    "move_ticket": ("id", "to"),
}
RANK_STEP = 1000
# The first rank written needs log format 2; older clients would drop the key on rewrite.
RANK_FORMAT = 2
_OWNER_KEYS = ("session", "label", "claimed_at")


def _owner(d: dict) -> Owner:
    return Owner(d["session"], d["label"], d.get("where", "local"), d["claimed_at"])


class Rejected(str):
    """A warning that says the op itself was refused (a move), with the op for the caller to match."""

    def __new__(cls, text: str, op: dict):
        self = super().__new__(cls, text)
        self.op = op
        return self


def apply_op(root: Path, op: dict) -> list[str]:
    res = _apply(Path(root), op)
    if str(op.get("op", "")).startswith("move_"):
        res = [Rejected(w, op) for w in res]  # a move has no warnings but refusals
    return res


def _apply(root: Path, op: dict) -> list[str]:
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
    qlog = store.load_quests(root)
    return handler(root, qlog, op)


def _create_goal(root, qlog, op):
    if op["id"] in qlog.goals:
        return []
    store.write_goal(root, Goal(op["id"], op["title"], op.get("order", 0), list(op.get("links") or [])))
    return []


def _bottom_rank(qlog, goal, exclude=None):
    """Rank that puts a ticket last in its group, or None while the group has no ranks."""
    ranks = [t.rank for t in qlog.tickets.values()
             if t.goal == goal and t.id != exclude and t.rank is not None]
    return max(ranks) + RANK_STEP if ranks else None


def _create_ticket(root, qlog, op):
    if op["id"] in qlog.tickets:
        return []
    t = Ticket(
        id=op["id"], title=op["title"], status="todo", goal=op.get("goal"),
        parent=op.get("parent"), blocked_by=[], owner=None,
        links=list(op.get("links") or []), created=op["at"], updated=op["at"],
        log=[LogEntry(op["at"], op["session"], "created")],
        rank=_bottom_rank(qlog, op.get("goal")),
    )
    store.write_ticket(root, t)
    return []


def _with_ticket(fn):
    def handler(root, qlog, op):
        t = qlog.tickets.get(op["id"])
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


def _set_goal(root, qlog, op):
    t = qlog.tickets.get(op["id"])
    if t is None:
        return [f"set_goal: unknown ticket {op['id']}"]
    if t.goal != op["goal"]:
        t.rank = _bottom_rank(qlog, op["goal"], exclude=t.id)
    t.goal = op["goal"]
    t.updated = op["at"]
    store.write_ticket(root, t)
    return []


def _target(op):
    """(kind, other id or None) from a move op's `to`, or an error string."""
    to = op["to"]
    if to in ("top", "bottom", "up", "down"):
        return to, None
    if isinstance(to, dict) and len(to) == 1:
        (kind, other), = to.items()
        if kind in ("before", "after") and isinstance(other, str):
            return kind, other
    return f"{op['op']}: invalid target {to!r}"


def _place(order, tid, kind, other, active):
    """`order` with tid moved per kind; up and down step past the nearest id in `active`."""
    rest = [x for x in order if x != tid]
    here = order.index(tid)
    if kind == "top":
        i = 0
    elif kind == "bottom":
        i = len(rest)
    elif kind in ("before", "after"):
        if other == tid:
            return order
        i = rest.index(other) + (kind == "after")
    elif kind == "up":
        prev = [x for x in order[:here] if x in active]
        if not prev:
            return order
        i = rest.index(prev[-1])
    else:
        nxt = [x for x in order[here + 1:] if x in active]
        if not nxt:
            return order
        i = rest.index(nxt[0]) + 1
    return rest[:i] + [tid] + rest[i:]


def _move_goal(root, qlog, op):
    tgt = _target(op)
    if isinstance(tgt, str):
        return [tgt]
    kind, other = tgt
    if op["id"] not in qlog.goals:
        return [f"move_goal: unknown main quest {op['id']}"]
    if other is not None and other not in qlog.goals:
        return [f"move_goal: unknown main quest {other}"]
    ids = [g.id for g in sorted(qlog.goals.values(), key=lambda g: (g.order, g.id))]
    new = _place(ids, op["id"], kind, other, set(ids))
    if new == ids:
        return []
    for n, gid in enumerate(new, 1):
        if qlog.goals[gid].order != n:
            qlog.goals[gid].order = n
            store.write_goal(root, qlog.goals[gid])
    return []


def _move_ticket(root, qlog, op):
    """Reorder within the ticket's main quest. Ranks are written for the whole group, in its
    current effective order, then the ticket is placed. done and dropped tickets keep a place
    in the group; up and down step past the nearest ready sibling so the move shows in next up."""
    tgt = _target(op)
    if isinstance(tgt, str):
        return [tgt]
    kind, other = tgt
    t = qlog.tickets.get(op["id"])
    if t is None:
        return [f"move_ticket: unknown ticket {op['id']}"]
    if other is not None:
        o = qlog.tickets.get(other)
        if o is None:
            return [f"move_ticket: unknown ticket {other}"]
        if o.goal != t.goal:
            return [f"move_ticket: {other} is in a different main quest than {t.id}"]
    group = sorted((x for x in qlog.tickets.values() if x.goal == t.goal), key=store.ticket_key)
    ids = [x.id for x in group]
    # Step past what "next up" shows (ready quests), so a move is always visible there.
    active = {x.id for x in group if views.is_ready(qlog, x)}
    new = _place(ids, t.id, kind, other, active)
    if new == ids:
        return []
    for n, tid in enumerate(new, 1):
        x = qlog.tickets[tid]
        if x.rank != n * RANK_STEP:
            x.rank = n * RANK_STEP
            store.write_ticket(root, x)
    if store.log_format(qlog.meta) < RANK_FORMAT:
        store.write_meta(root, {**qlog.meta, "format": RANK_FORMAT})
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
    "move_goal": _move_goal,
    "move_ticket": _move_ticket,
}
