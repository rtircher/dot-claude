"""Render the full quest log as one self-contained HTML page. Pure; no scripts, no network."""
from __future__ import annotations

from html import escape

from quests.store import QuestLog, Ticket, ticket_key

_CSS = """
:root{--bg:#fafafa;--fg:#1c1c1e;--muted:#6b6b70;--card:#fff;--line:#d8d8de;--accent:#2f6fdb;
--ok:#2e8b57;--warn:#b7791f}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececf0;--muted:#9a9aa3;--card:#1f1f23;
--line:#34343b;--accent:#6ea2ff;--ok:#5cc08a;--warn:#e0a84a}}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:60rem;margin-inline:auto}
h1{font-size:1.4rem;margin:0 0 .25rem}h2{font-size:1.1rem;margin:1.5rem 0 .5rem}
.muted{color:var(--muted)}a{color:var(--accent)}
section{margin-bottom:1rem}
ul{list-style:none;margin:.25rem 0;padding-left:0}ul ul{padding-left:1.1rem;border-left:2px solid var(--line);margin-left:.4rem}
li.ticket{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:.5rem .7rem;margin:.35rem 0}
li.ticket>ul{margin-top:.4rem}
.badge{display:inline-block;font-size:.75rem;padding:0 .45rem;border-radius:999px;border:1px solid var(--line);
color:var(--muted);margin-right:.4rem;white-space:nowrap}
.badge.in_progress{color:var(--accent);border-color:var(--accent)}
.badge.done{color:var(--ok);border-color:var(--ok)}
.badge.blocked{color:var(--warn);border-color:var(--warn)}
.title{font-weight:600;overflow-wrap:anywhere}
progress{width:100%;max-width:18rem;height:.7rem;vertical-align:middle}
.goal{display:flex;flex-wrap:wrap;gap:.25rem .75rem;align-items:center}
details{margin:.3rem 0}summary{cursor:pointer}
.log{font-size:.85rem;color:var(--muted);margin:.3rem 0 0;padding-left:1rem;list-style:disc}
code{font-family:ui-monospace,Menlo,monospace;font-size:.85em;overflow-wrap:anywhere}
.links{font-size:.85rem;margin-top:.2rem}
"""


def _e(text) -> str:
    return escape(str(text), quote=True)


def _link(link: str) -> str:
    low = link.strip().lower()
    if low.startswith(("http://", "https://")):
        return f'<a href="{_e(link.strip())}" rel="noopener noreferrer">{_e(link)}</a>'
    return f"<code>{_e(link)}</code>"


def _ticket(qlog: QuestLog, t: Ticket, kids: dict, seen: set) -> str:
    owner = f' <span class="muted">{_e(t.owner.label)} ({_e(t.owner.where)})</span>' if t.owner else ""
    parts = [f'<li class="ticket" id="t-{_e(t.id)}"><span class="badge {_e(t.status)}">{_e(t.status)}</span>'
             f'<span class="title">{_e(t.title)}</span>{owner}']
    if t.links:
        parts.append('<div class="links">' + " ".join(_link(x) for x in t.links) + "</div>")
    if t.log:
        rows = "".join(f"<li>{_e(e.at)} ({_e(e.session)}) {_e(e.text)}</li>" for e in t.log)
        parts.append(f'<details><summary>Log ({len(t.log)})</summary><ul class="log">{rows}</ul></details>')
    parts.append(_tree(qlog, kids.get(t.id, []), kids, seen))
    parts.append("</li>")
    return "".join(parts)


def _tree(qlog: QuestLog, nodes: list, kids: dict, seen: set) -> str:
    items = []
    for t in nodes:
        if t.id in seen:
            continue
        seen.add(t.id)
        items.append(_ticket(qlog, t, kids, seen))
    return f"<ul>{''.join(items)}</ul>" if items else ""


def _forest(qlog: QuestLog, tickets: list[Ticket]) -> str:
    """Tickets nested under their parents; missing parents and cycles fall back to roots."""
    ids = {t.id for t in tickets}
    ordered = sorted(tickets, key=lambda t: (t.goal or "", ticket_key(t)))
    kids: dict[str, list[Ticket]] = {}
    roots = []
    for t in ordered:
        if t.parent and t.parent in ids and t.parent != t.id:
            kids.setdefault(t.parent, []).append(t)
        else:
            roots.append(t)
    seen: set[str] = set()
    out = _tree(qlog, roots, kids, seen)
    # Anything left sits in a parent cycle: surface it as extra roots.
    rest = [t for t in ordered if t.id not in seen]
    return out + _tree(qlog, rest, kids, seen)


def _group(qlog: QuestLog, title: str, tickets: list[Ticket], done: int, total: int) -> str:
    openish = [t for t in tickets if t.status not in ("done", "dropped")]
    parts = [f'<section><div class="goal"><h2>{_e(title)}</h2>'
             f'<progress value="{done}" max="{max(total, 1)}"></progress>'
             f'<span class="muted">{done}/{total}</span></div>']
    parts.append(_forest(qlog, openish))
    for status, label in (("done", "Done"), ("dropped", "Dropped")):
        sel = [t for t in tickets if t.status == status]
        if sel:
            parts.append(f"<details><summary>{label} ({len(sel)})</summary>{_forest(qlog, sel)}</details>")
    parts.append("</section>")
    return "".join(parts)


def render_html(qlog: QuestLog, s: dict) -> str:
    repo = s.get("repo") or qlog.meta.get("code_repo", "")
    body = [f"<h1>Quest log: {_e(repo)}</h1>"]
    if not s.get("synced", True):
        body.append('<p class="muted">(unsynced: will push on next sync)</p>')

    progress = {g["id"]: g for g in s["goals"]}
    body.append("<section><h2>Main quests</h2><ul>")
    for g in s["goals"]:
        body.append(f'<li class="goal"><span class="title">{_e(g["title"])}</span>'
                    f'<progress value="{g["done"]}" max="{max(g["total"], 1)}"></progress>'
                    f'<span class="muted">{g["done"]}/{g["total"]}</span></li>')
    body.append("</ul></section>")

    if s["sessions"]:
        body.append("<section><h2>In progress</h2><ul>")
        for e in s["sessions"]:
            chain = " &gt; ".join(_e(c["title"]) for c in e["chain"])
            body.append(f'<li><span class="badge">{_e(e["state"])}</span><strong>{_e(e["label"])}</strong> '
                        f'<span class="muted">({_e(e["where"])})</span>: {chain}</li>')
        body.append("</ul></section>")

    if s["next"]:
        body.append("<section><h2>Next up</h2><ul>")
        for n in s["next"]:
            body.append(f'<li>{_e(n["title"])}</li>')
        if s["next_more"]:
            body.append(f'<li class="muted">+{s["next_more"]} more</li>')
        body.append("</ul></section>")

    if s["stale"]:
        body.append("<section><h2>Stale claims</h2><ul>")
        for x in s["stale"]:
            body.append(f'<li>{_e(x["title"])} <span class="muted">({_e(x["owner_label"])})</span></li>')
        body.append("</ul></section>")

    body.append("<h2>All main quests</h2>")
    for g in sorted(qlog.goals.values(), key=lambda g: (g.order, g.id)):
        ts = [t for t in qlog.tickets.values() if t.goal == g.id]
        p = progress.get(g.id, {"done": 0, "total": 0})
        body.append(_group(qlog, g.title, ts, p["done"], p["total"]))
        if g.links:
            body.append('<div class="links">' + " ".join(_link(x) for x in g.links) + "</div>")
    loose = [t for t in qlog.tickets.values() if t.goal not in qlog.goals]
    if loose:
        done = sum(1 for t in loose if t.status == "done")
        total = sum(1 for t in loose if t.status != "dropped")
        body.append(_group(qlog, "No main quest", loose, done, total))

    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Quest log</title><style>{_CSS}</style></head><body>{''.join(body)}</body></html>\n")
