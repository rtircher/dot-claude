import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quests import views
from quests.store import QuestLog, Goal, LogEntry, Owner, Ticket
from quests.views import SessionState

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)


def iso(hours_ago):
    from datetime import timedelta
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def tk(id, **over):
    base = dict(id=id, title=f"Title {id}", status="todo", goal="g1", parent=None,
                blocked_by=[], owner=None, links=[], created=iso(48), updated=iso(48), log=[])
    base.update(over)
    return Ticket(**base)


def own(session="s1", label="alice", hours_ago=1):
    return Owner(session, label, "local", iso(hours_ago))


def qlog(*tickets, goals=None):
    goals = goals or [Goal("g1", "Example goal", 1, [])]
    return QuestLog({"code_repo": "example/repo"}, {g.id: g for g in goals}, {t.id: t for t in tickets})


def hb(session="s1", state="active", hours_ago=0.1, label="alice"):
    return SessionState(session, label, "local", state, iso(hours_ago))


class ViewsTest(unittest.TestCase):
    def summ(self, b, sessions=None, current=None, synced=True):
        return views.summary(b, sessions or {}, NOW, current, synced)

    def test_goal_progress_excludes_dropped(self):
        b = qlog(tk("a", status="done"), tk("b"), tk("c", status="dropped"))
        g = self.summ(b)["goals"][0]
        self.assertEqual((g["done"], g["total"]), (1, 2))
        self.assertEqual(self.summ(b)["repo"], "example/repo")

    def test_next_skips_blocked_and_owned(self):
        b = qlog(
            tk("a", status="done"),
            tk("free"),
            tk("blocked", blocked_by=["free"]),
            tk("unblocked", blocked_by=["a"]),
            tk("owned", owner=own(), status="in_progress"),
        )
        ids = [n["id"] for n in self.summ(b)["next"]]
        self.assertEqual(sorted(ids), ["free", "unblocked"])

    def test_next_uses_rank_within_a_goal_and_goal_order_first(self):
        goals = [Goal("g1", "One", 2, []), Goal("g2", "Two", 1, [])]
        b = qlog(tk("a", created=iso(5)), tk("b", created=iso(4), rank=1000), tk("c", created=iso(3), rank=500),
                 tk("d", goal="g2", created=iso(1)), tk("e", goal=None, created=iso(9)), goals=goals)
        self.assertEqual([n["id"] for n in self.summ(b)["next"]], ["d", "c", "b", "a", "e"])

    def test_position_counts_active_siblings(self):
        b = qlog(tk("a", status="done", rank=1000), tk("b", rank=2000), tk("c", rank=3000),
                 tk("z", goal=None))
        self.assertEqual(views.position(b, b.tickets["c"]), 2)
        self.assertEqual(views.position(b, b.tickets["a"]), 1)
        self.assertEqual(views.position(b, b.tickets["z"]), 1)

    def test_next_limit_and_more(self):
        b = qlog(*[tk(f"t{i}", created=iso(100 - i)) for i in range(8)])
        s = views.summary(b, {}, NOW, None, True, next_limit=3)
        self.assertEqual(len(s["next"]), 3)
        self.assertEqual(s["next_more"], 5)

    def test_chain_root_first(self):
        b = qlog(
            tk("A"),
            tk("B", parent="A"),
            tk("C", parent="B", status="in_progress", owner=own()),
        )
        s = self.summ(b, {"s1": hb()})
        self.assertEqual([c["id"] for c in s["sessions"][0]["chain"]], ["A", "B", "C"])

    def test_chain_cycle_guard(self):
        b = qlog(tk("A", parent="B"), tk("B", parent="A", status="in_progress", owner=own()))
        s = self.summ(b, {"s1": hb()})
        self.assertEqual(len(s["sessions"][0]["chain"]), 2)

    def test_current_session_first_and_most_recent_claim(self):
        b = qlog(
            tk("x", status="in_progress", owner=own("s1", "alice", 3)),
            tk("y", status="in_progress", owner=own("s1", "alice", 1)),
            tk("z", status="in_progress", owner=own("s2", "bob", 2)),
        )
        s = self.summ(b, {"s1": hb(), "s2": hb("s2", label="bob")}, current="s2")
        self.assertEqual([e["session"] for e in s["sessions"]], ["s2", "s1"])
        self.assertEqual(s["sessions"][1]["chain"][-1]["id"], "y")

    def test_session_states(self):
        b = qlog(
            tk("a", status="in_progress", owner=own("s1")),
            tk("b", status="in_progress", owner=own("s2", "bob")),
            tk("c", status="in_progress", owner=own("s3", "cy"), updated=iso(1)),
            tk("d", status="in_progress", owner=own("s4", "di")),
        )
        sess = {
            "s1": hb("s1", "active", 0.1),
            "s2": hb("s2", "active", 0.5, "bob"),
            "s4": hb("s4", "waiting", 0.6, "di"),
        }
        s = self.summ(b, sess)
        got = {e["session"]: e["state"] for e in s["sessions"]}
        self.assertEqual(got["s1"], "active")
        self.assertEqual(got["s2"], "idle")
        self.assertEqual(got["s3"], "remote")
        self.assertEqual(got["s4"], "waiting")

    def test_stale_local_and_remote(self):
        b = qlog(
            tk("a", status="in_progress", owner=own("s1", "alice", 5), updated=iso(1)),
            tk("b", status="in_progress", owner=own("s2", "bob", 25), updated=iso(1)),
            tk("c", status="in_progress", owner=own("s3", "cy", 23), updated=iso(1)),
            tk("d", status="in_progress", owner=own("s4", "di"), updated=iso(1)),
        )
        sess = {"s1": hb("s1", "active", 3), "s4": hb("s4", "ended", 0.1, "di")}
        s = self.summ(b, sess)
        stale = {e["id"]: e for e in s["stale"]}
        self.assertEqual(set(stale), {"a", "b", "d"})
        self.assertEqual(stale["b"]["owner_label"], "bob")
        self.assertEqual([e["session"] for e in s["sessions"]], ["s3"])

    def test_local_heartbeat_old_but_owner_note_recent_is_not_stale(self):
        t = tk("a", status="in_progress", owner=own("s1", "alice", 5),
               log=[LogEntry(iso(1 / 6), "s1", "progress")])
        s = self.summ(qlog(t), {"s1": hb("s1", "active", 3)})
        self.assertEqual(s["stale"], [])
        self.assertEqual(len(s["sessions"]), 1)

    def test_dead_owner_blocked_ticket_is_stale_but_not_a_session_entry(self):
        t = tk("a", status="blocked", owner=own("s1", "alice", 5))
        s = self.summ(qlog(t), {"s1": hb("s1", "ended", 3)})
        self.assertEqual([e["id"] for e in s["stale"]], ["a"])
        self.assertEqual(s["sessions"], [])
        live = tk("b", status="blocked", owner=own("s2", "bob", 1))
        s = self.summ(qlog(live), {"s2": hb("s2", "active", 0.1, "bob")})
        self.assertEqual(s["stale"], [])
        self.assertEqual(s["sessions"], [])

    def test_other_sessions_note_does_not_keep_remote_claim_alive(self):
        t = tk("b", status="in_progress", owner=own("s2", "bob", 25), updated=iso(1),
               log=[LogEntry(iso(1), "s9", "ping")])
        s = self.summ(qlog(t))
        self.assertEqual([e["id"] for e in s["stale"]], ["b"])
        self.assertEqual(s["sessions"], [])

    def test_owner_log_entry_keeps_remote_claim_alive(self):
        t = tk("b", status="in_progress", owner=own("s2", "bob", 25),
               log=[LogEntry(iso(1), "s2", "progress")])
        s = self.summ(qlog(t))
        self.assertEqual(s["stale"], [])
        self.assertEqual(len(s["sessions"]), 1)

    def test_remote_staleness_is_per_ticket(self):
        b = qlog(
            tk("old", status="in_progress", owner=own("s2", "bob", 30)),
            tk("new", status="in_progress", owner=own("s2", "bob", 1)),
        )
        s = self.summ(b)
        self.assertEqual([e["id"] for e in s["stale"]], ["old"])
        self.assertEqual(s["sessions"][0]["chain"][-1]["id"], "new")

    def test_render_text_max_25_lines(self):
        ts = [tk(f"t{i}", goal=f"g{i % 3}") for i in range(40)]
        ts += [tk(f"p{i}", status="in_progress", owner=own(f"s{i}", f"u{i}")) for i in range(10)]
        goals = [Goal(f"g{i}", f"Goal {i}", i, []) for i in range(3)]
        b = qlog(*ts, goals=goals)
        s = views.summary(b, {}, NOW, None, False, next_limit=20)
        text = views.render_text(s)
        lines = text.split("\n")
        self.assertLessEqual(len(lines), 25)
        self.assertEqual(lines[0], "Quests: example/repo (unsynced)")
        self.assertIn("more", text)
        for ch in (chr(0x2014), chr(0x2013)):
            self.assertNotIn(ch, text)

    def test_render_text_next_more_count(self):
        b = qlog(*[tk(f"t{i}", created=iso(100 - i)) for i in range(30)])
        s = views.summary(b, {}, NOW, None, True, next_limit=20)
        text = views.render_text(s)
        shown = [l for l in text.split("\n") if l.startswith("  Title")]
        more = [l for l in text.split("\n") if "more quests" in l][0]
        self.assertEqual(len(shown) + int(more.split("+")[1].split()[0]), 30)

    def test_render_text_synced_first_line(self):
        s = self.summ(qlog(tk("a")))
        self.assertEqual(views.render_text(s).split("\n")[0], "Quests: example/repo")

    def test_load_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            sd = Path(d) / "sessions"
            sd.mkdir()
            good = {"session": "s1", "label": "alice", "where": "local",
                    "repo_key": "k1", "state": "active", "last_seen": iso(1)}
            other = dict(good, session="s2", repo_key="k2")
            (sd / "a.json").write_text(json.dumps(good))
            (sd / "b.json").write_text(json.dumps(other))
            (sd / "c.json").write_text("{not json")
            (sd / "d.json").write_text(json.dumps({"session": "s5"}))
            got = views.load_sessions(Path(d), "k1")
            self.assertEqual(list(got), ["s1"])
            self.assertEqual(got["s1"].label, "alice")
            self.assertEqual(views.load_sessions(Path(d) / "nope", "k1"), {})


if __name__ == "__main__":
    unittest.main()
