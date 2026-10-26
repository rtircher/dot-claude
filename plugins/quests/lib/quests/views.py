"""Quests summary view and plain-text rendering. Pure; no git, no network."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quests.store import QuestLog, Ticket, too_new_message, log_format, FORMAT, ticket_key

_FMT = "%Y-%m-%dT%H:%M:%SZ"
IDLE_AFTER = timedelta(minutes=15)
LOCAL_STALE_AFTER = timedelta(hours=2)
REMOTE_STALE_AFTER = timedelta(hours=24)
MAX_LINES = 25


@dataclass
class SessionState:
    session: str
    label: str
    where: str
    state: str  # active | waiting | ended
    last_seen: str


def _parse(ts: str) -> datetime:
    try:
        return datetime.strptime(ts, _FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def load_sessions(state_dir: Path, repo_key: str) -> dict[str, SessionState]:
    out: dict[str, SessionState] = {}
    sdir = Path(state_dir) / "sessions"
    if not sdir.is_dir():
        return out
    for p in sorted(sdir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d["repo_key"] != repo_key:
                continue
            out[d["session"]] = SessionState(
                d["session"], d["label"], d["where"], d["state"], d["last_seen"]
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _owner_activity(t: Ticket) -> datetime:
    """Latest sign of life from the owner: the claim or their own log entries."""
    times = [_parse(t.owner.claimed_at)]
    times += [_parse(e.at) for e in t.log if e.session == t.owner.session]
    return max(times)


def _chain(qlog: QuestLog, t: Ticket) -> list[dict]:
    chain, seen, cur = [], set(), t
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        chain.append({"id": cur.id, "title": cur.title})
        cur = qlog.tickets.get(cur.parent) if cur.parent else None
    chain.reverse()
    return chain


def _latest(tickets: list[Ticket]) -> Ticket:
    """The ticket a session is on now: its most recently claimed one."""
    return max(tickets, key=lambda t: (t.owner.claimed_at, t.id))


def current_ticket(qlog, session: str) -> Ticket | None:
    """The in-progress ticket this session holds, by the same rule the summary uses for its chain."""
    mine = [t for t in qlog.tickets.values()
            if t.owner is not None and t.owner.session == session and t.status == "in_progress"]
    return _latest(mine) if mine else None


def is_ready(qlog, t: Ticket) -> bool:
    """What 'next up' lists: todo, unclaimed, and every blocker done."""
    return (t.status == "todo" and t.owner is None
            and all(b in qlog.tickets and qlog.tickets[b].status == "done" for b in t.blocked_by))


def position(qlog, t: Ticket) -> int:
    """1-based place of t among its main quest's ready tickets, as the pane and 'next up' show them."""
    group = [s for s in qlog.tickets.values() if s.goal == t.goal and (s is t or is_ready(qlog, s))]
    return sorted(group, key=ticket_key).index(t) + 1


def summary(qlog, sessions, now, current_session, synced, next_limit=5) -> dict:
    goals_sorted = sorted(qlog.goals.values(), key=lambda g: (g.order, g.id))
    goals = []
    for g in goals_sorted:
        ts = [t for t in qlog.tickets.values() if t.goal == g.id and t.status != "dropped"]
        goals.append({"id": g.id, "title": g.title,
                      "done": sum(1 for t in ts if t.status == "done"), "total": len(ts)})

    by_session: dict[str, list[Ticket]] = {}
    for t in qlog.tickets.values():
        if t.owner is not None and t.status not in ("done", "dropped"):
            by_session.setdefault(t.owner.session, []).append(t)

    entries, stale = [], []
    for sid, ts in by_session.items():
        hb = sessions.get(sid)
        if hb is not None:
            seen = _parse(hb.last_seen)
            if hb.state == "ended":
                dead = ts
            else:
                dead = [t for t in ts if now - max(seen, _owner_activity(t)) > LOCAL_STALE_AFTER]
        else:
            dead = [t for t in ts if now - _owner_activity(t) > REMOTE_STALE_AFTER]
        dead_ids = {t.id for t in dead}
        for t in sorted(dead, key=lambda t: t.id):
            stale.append({"id": t.id, "title": t.title, "owner_label": t.owner.label})
        live = [t for t in ts if t.id not in dead_ids and t.status == "in_progress"]
        if not live:
            continue
        latest = _latest(live)
        if hb is None:
            state, label, where = "remote", latest.owner.label, latest.owner.where
        else:
            state, label, where = hb.state, hb.label, hb.where
            if state == "active" and now - _parse(hb.last_seen) > IDLE_AFTER:
                state = "idle"
        entries.append({"session": sid, "label": label, "where": where,
                        "state": state, "chain": _chain(qlog, latest)})
    entries.sort(key=lambda e: (e["session"] != current_session, e["label"], e["session"]))

    order = {g.id: g.order for g in qlog.goals.values()}
    ready = [t for t in qlog.tickets.values() if is_ready(qlog, t)]
    ready.sort(key=lambda t: (order.get(t.goal, 10**9), ticket_key(t)))
    nxt = [{"id": t.id, "title": t.title, "goal": t.goal} for t in ready[:next_limit]]

    out = {
        "repo": qlog.meta.get("code_repo", ""),
        "synced": synced,
        "goals": goals,
        "sessions": entries,
        "next": nxt,
        "next_more": max(0, len(ready) - next_limit),
        "stale": stale,
    }
    if log_format(qlog.meta) > FORMAT:
        out["format_error"] = too_new_message(log_format(qlog.meta))
    return out


def _section(header: str, rows: list[str], budget: int, more_label: str,
             extra: int = 0) -> list[str]:
    """Header plus rows, truncated to budget lines with a '+N more' tail."""
    if not rows or budget < 2:
        return []
    room = budget - 1
    if len(rows) > room:
        keep = room - 1
        rows = rows[:keep] + [f"  +{len(rows) - keep + extra} more {more_label}"]
    elif extra:
        rows = rows + [f"  +{extra} more"]
    return [header] + rows


def render_text(s: dict) -> str:
    head = f"Quests: {s['repo']}" + ("" if s["synced"] or s.get("format_error") else " (unsynced)")
    goal_rows = [f"  {g['title']}: {g['done']}/{g['total']}" for g in s["goals"]]
    sess_rows = []
    for e in s["sessions"]:
        chain = " > ".join(c["title"] for c in e["chain"])
        sess_rows.append(f"  {e['label']} ({e['state']}): {chain}")
    next_rows = [f"  {n['title']}" for n in s["next"]]
    stale_rows = [f"  {x['title']} ({x['owner_label']})" for x in s["stale"]]

    # Fixed budgets so no section starves the others; leftover goes to goals.
    lines = [head]
    avail = MAX_LINES - 1
    sections = [("Main quests", goal_rows, "main quests"), ("In progress", sess_rows, "sessions"),
                ("Next up", next_rows, "quests"), ("Stale quests", stale_rows, "quests")]
    extras = {"Next up": s["next_more"]}
    sections = [x for x in sections if x[1]]
    caps = {"Main quests": 6, "In progress": 8, "Next up": 7, "Stale quests": 4}
    for name, rows, label in sections:
        cap = min(caps[name], avail - (len(sections) - sections.index((name, rows, label)) - 1) * 2)
        block = _section(name, rows, cap, label, extras.get(name, 0))
        lines += block
        avail -= len(block)
    if s.get("format_error"):
        lines.insert(1, s["format_error"])
    return "\n".join(lines[:MAX_LINES])
