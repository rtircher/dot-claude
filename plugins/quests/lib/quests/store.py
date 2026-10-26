"""Quest log file format: dataclasses, load, and write. No CLI, no git."""
from __future__ import annotations

import json
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Highest board.json "format" this plugin reads and writes; a missing key means 1.
FORMAT = 2

_ID_CHARS = string.ascii_lowercase + string.digits
_LOG_RE = re.compile(r"^- (\S+) \(([^)\s]*)\) ?(.*)$")
# Every character str.splitlines() treats as a line break (\r\n counts once).
_BREAKS = re.compile("\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")
_SESSION_BAD = re.compile(r"[)\s]")


@dataclass
class Owner:
    session: str
    label: str
    where: str  # "local" or "cloud"
    claimed_at: str


@dataclass
class LogEntry:
    at: str
    session: str
    text: str


@dataclass
class Ticket:
    id: str
    title: str
    status: str
    goal: str | None
    parent: str | None
    blocked_by: list[str]
    owner: Owner | None
    links: list[str]
    created: str
    updated: str
    log: list[LogEntry] = field(default_factory=list)
    # Manual order within the ticket's main quest; None means creation order. Needs log format 2.
    rank: int | float | None = None


@dataclass
class Goal:
    id: str
    title: str
    order: int
    links: list[str]


@dataclass
class QuestLog:
    meta: dict
    goals: dict[str, Goal]
    tickets: dict[str, Ticket]


def log_format(meta: dict) -> int:
    f = meta.get("format", 1)
    return f if isinstance(f, int) and not isinstance(f, bool) else 1


def read_format(root: Path) -> int:
    try:
        meta = json.loads((Path(root) / "board.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    return log_format(meta) if isinstance(meta, dict) else 1


def too_new_message(n: int) -> str:
    return (f"this quest log needs a newer quests plugin (log format {n}, "
            f"this plugin supports {FORMAT}); update dot-claude")


ACTIVE = ("todo", "in_progress", "blocked")


def ticket_key(t: Ticket) -> tuple:
    """Order of tickets within one main quest: ranked by rank, then unranked by creation."""
    if t.rank is not None:
        return (0, t.rank, t.created, t.id)
    return (1, 0, t.created, t.id)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str, existing: set[str]) -> str:
    while True:
        cand = prefix + "-" + "".join(random.choices(_ID_CHARS, k=5))
        if cand not in existing:
            return cand


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _clean(text: str) -> str:
    return _BREAKS.sub(" / ", text)


def _clean_session(session: str) -> str:
    return _SESSION_BAD.sub("_", session)


def _title_line(title: str) -> str:
    return "# " + _clean(title)


def write_ticket(root: Path, t: Ticket) -> Path:
    owner = None
    if t.owner is not None:
        owner = {
            "session": t.owner.session,
            "label": t.owner.label,
            "where": t.owner.where,
            "claimed_at": t.owner.claimed_at,
        }
    fields = [
        ("id", t.id),
        ("title", t.title),
        ("status", t.status),
        ("goal", t.goal),
        ("parent", t.parent),
        ("blocked_by", t.blocked_by),
        ("owner", owner),
        ("links", t.links),
        ("created", t.created),
        ("updated", t.updated),
    ]
    if t.rank is not None:
        fields.append(("rank", t.rank))
    lines = ["---"] + [f"{k}: {_dump(v)}" for k, v in fields] + ["---"]
    lines += [_title_line(t.title), "", "## Log"]
    lines += [f"- {e.at} ({_clean_session(e.session)}) {_clean(e.text)}" for e in t.log]
    return _write(Path(root) / "tickets" / f"{t.id}.md", "\n".join(lines) + "\n")


def write_goal(root: Path, g: Goal) -> Path:
    fields = [("id", g.id), ("title", g.title), ("order", g.order), ("links", g.links)]
    lines = ["---"] + [f"{k}: {_dump(v)}" for k, v in fields] + ["---"]
    lines.append(_title_line(g.title))
    return _write(Path(root) / "goals" / f"{g.id}.md", "\n".join(lines) + "\n")


def write_meta(root: Path, meta: dict) -> Path:
    return _write(Path(root) / "board.json", _dump(meta) + "\n")


def _split(text: str) -> tuple[dict, list[str]]:
    """Return (frontmatter dict, body lines). Frontmatter is the block between
    the first two lines that are exactly '---'."""
    lines = text.split("\n")
    fences = [i for i, ln in enumerate(lines) if ln == "---"]
    if len(fences) < 2:
        raise ValueError("missing frontmatter")
    fm = {}
    for ln in lines[fences[0] + 1 : fences[1]]:
        if not ln.strip():
            continue
        key, sep, raw = ln.partition(": ")
        if not sep:
            raise ValueError(f"bad frontmatter line: {ln!r}")
        fm[key] = json.loads(raw)
    return fm, lines[fences[1] + 1 :]


def _read_ticket(path: Path) -> Ticket:
    fm, body = _split(path.read_text(encoding="utf-8"))
    log: list[LogEntry] = []
    in_log = False
    for ln in body:
        if ln.startswith("## "):
            in_log = ln == "## Log"
            continue
        if in_log:
            m = _LOG_RE.match(ln)
            if m:
                log.append(LogEntry(m.group(1), m.group(2), m.group(3)))
    rank = fm.get("rank")
    o = fm["owner"]
    owner = Owner(o["session"], o["label"], o["where"], o["claimed_at"]) if o else None
    return Ticket(
        id=fm["id"],
        title=fm["title"],
        status=fm["status"],
        goal=fm["goal"],
        parent=fm["parent"],
        blocked_by=fm["blocked_by"],
        owner=owner,
        links=fm["links"],
        created=fm["created"],
        updated=fm["updated"],
        log=log,
        rank=rank if isinstance(rank, (int, float)) and not isinstance(rank, bool) else None,
    )


def _read_goal(path: Path) -> Goal:
    fm, _ = _split(path.read_text(encoding="utf-8"))
    return Goal(fm["id"], fm["title"], fm["order"], fm["links"])


def load_quests(root: Path) -> QuestLog:
    root = Path(root)
    meta = json.loads((root / "board.json").read_text(encoding="utf-8"))
    goals: dict[str, Goal] = {}
    tickets: dict[str, Ticket] = {}
    gdir, tdir = root / "goals", root / "tickets"
    if gdir.is_dir():
        for p in sorted(gdir.glob("*.md")):
            g = _read_goal(p)
            goals[g.id] = g
    if tdir.is_dir():
        for p in sorted(tdir.glob("*.md")):
            t = _read_ticket(p)
            tickets[t.id] = t
    return QuestLog(meta, goals, tickets)
