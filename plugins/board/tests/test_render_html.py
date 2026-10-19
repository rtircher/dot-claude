import re
import unittest
from datetime import datetime, timezone

from board import views
from board.render_html import render_html
from board.store import Board, Goal, LogEntry, Owner, Ticket

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
TS = "2026-10-18T11:00:00Z"


def tk(id, **over):
    base = dict(id=id, title=f"Title {id}", status="todo", goal="g1", parent=None,
                blocked_by=[], owner=None, links=[], created=TS, updated=TS, log=[])
    base.update(over)
    return Ticket(**base)


def page(*tickets, goals=None):
    goals = goals or [Goal("g1", "Example goal", 1, [])]
    b = Board({"code_repo": "example/repo"}, {g.id: g for g in goals}, {t.id: t for t in tickets})
    return render_html(b, views.summary(b, {}, NOW, None, True))


class RenderHtmlTest(unittest.TestCase):
    def test_html_escapes_titles(self):
        out = page(tk("a", title="<script>alert(1)</script>",
                      log=[LogEntry(TS, "s1", '<b onclick="x">')]))
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        self.assertNotIn('<b onclick', out)

    def test_html_has_no_external_urls(self):
        out = page(tk("a", links=["https://example.com/issue/1", "docs/plan.md"]))
        urls = re.findall(r'(?:src|href)="([^"]*)"', out)
        self.assertEqual(urls, ["https://example.com/issue/1"])
        self.assertNotIn("<script", out)
        self.assertNotIn("@import", out)
        self.assertIn("<code>docs/plan.md</code>", out)

    def test_html_nests_side_quests(self):
        out = page(tk("p", title="Parent one"), tk("c", title="Child one", parent="p"))
        m = re.search(r'<li class="ticket"[^>]*id="t-p".*?</li>\s*</ul>', out, re.S)
        self.assertIsNotNone(m)
        self.assertIn("Child one", m.group(0))

    def test_cycles_and_missing_parents_do_not_hang_or_vanish(self):
        out = page(tk("a", title="Alpha", parent="b", status="blocked"),
                   tk("b", title="Beta", parent="a", status="blocked"),
                   tk("o", title="Orphan", parent="gone", status="blocked"))
        for t in ("Alpha", "Beta", "Orphan"):
            self.assertEqual(out.count(f">{t}<"), 1, t)

    def test_javascript_links_never_become_hrefs(self):
        out = page(tk("a", links=["javascript:alert(1)", "JavaScript:alert(2)", "data:text/html,x"]))
        self.assertNotIn("href=", out.lower())
        self.assertIn("<code>javascript:alert(1)</code>", out)

    def test_no_goal_group_and_done_collapsed(self):
        out = page(tk("a", goal=None, title="Loose"), tk("d", status="done", title="Finished"))
        self.assertIn("No goal", out)
        self.assertRegex(out, r"<details[^>]*>\s*<summary>Done")
        self.assertNotRegex(out, r"<details open[^>]*>\s*<summary>Done")

    def test_in_progress_sessions_and_progress_bar(self):
        owner = Owner("s1", "alice", "local", TS)
        b = Board({"code_repo": "example/repo"}, {"g1": Goal("g1", "Example goal", 1, [])},
                  {"a": tk("a", status="in_progress", owner=owner, title="Working")})
        out = render_html(b, views.summary(b, {}, NOW, None, True))
        self.assertIn("alice", out)
        self.assertIn("<progress", out)
