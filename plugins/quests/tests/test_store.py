import json
import tempfile
import unittest
from pathlib import Path

from quests import store
from quests.store import Goal, LogEntry, Owner, Ticket


def make_ticket(**over):
    base = dict(
        id="t-abc12",
        title="Set up backups",
        status="in_progress",
        goal="g-xyz89",
        parent=None,
        blocked_by=["t-def34"],
        owner=Owner("sess-1", "alice", "local", "2026-10-18T10:00:00Z"),
        links=["https://example.com/pr/1"],
        created="2026-10-18T09:00:00Z",
        updated="2026-10-18T10:00:00Z",
        log=[
            LogEntry("2026-10-18T09:00:00Z", "sess-1", "created"),
            LogEntry("2026-10-18T10:00:00Z", "sess-2", "started work"),
        ],
    )
    base.update(over)
    return Ticket(**base)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        store.write_meta(self.root, {"schema": 1, "code_repo": "example/repo"})

    def test_ticket_round_trip(self):
        t = make_ticket()
        store.write_ticket(self.root, t)
        g = Goal("g-xyz89", "Example goal", 1, ["https://example.com/doc"])
        store.write_goal(self.root, g)
        qlog = store.load_quests(self.root)
        self.assertEqual(qlog.tickets["t-abc12"], t)
        self.assertEqual(qlog.goals["g-xyz89"], g)
        self.assertEqual(qlog.meta, {"schema": 1, "code_repo": "example/repo"})

    def test_rank_is_written_only_when_set_and_old_files_load(self):
        store.write_ticket(self.root, make_ticket())
        text = (self.root / "tickets" / "t-abc12.md").read_text()
        self.assertNotIn("rank", text)
        self.assertIsNone(store.load_quests(self.root).tickets["t-abc12"].rank)
        store.write_ticket(self.root, make_ticket(rank=2000))
        self.assertIn("rank: 2000\n", (self.root / "tickets" / "t-abc12.md").read_text())
        self.assertEqual(store.load_quests(self.root).tickets["t-abc12"].rank, 2000)

    def test_ticket_key_ranked_first_by_rank_then_unranked_by_creation(self):
        a = make_ticket(id="a", created="2026-10-18T09:00:00Z")
        b = make_ticket(id="b", created="2026-10-18T09:01:00Z", rank=2000)
        c = make_ticket(id="c", created="2026-10-18T09:02:00Z", rank=1000)
        d = make_ticket(id="d", created="2026-10-18T09:03:00Z")
        self.assertEqual([t.id for t in sorted([d, a, b, c], key=store.ticket_key)], ["c", "b", "a", "d"])

    def test_log_format_defaults_to_one_and_reads_newer(self):
        self.assertEqual(store.log_format({"schema": 1}), 1)
        self.assertEqual(store.log_format({"format": 2}), 2)
        self.assertEqual(store.log_format({"format": "junk"}), 1)
        self.assertEqual(store.read_format(self.root), 1)
        store.write_meta(self.root, {"schema": 1, "format": store.FORMAT + 1})
        self.assertEqual(store.read_format(self.root), store.FORMAT + 1)
        self.assertEqual(store.read_format(self.root / "missing"), 1)
        self.assertEqual(
            store.too_new_message(3),
            "this quest log needs a newer quests plugin (log format 3, this plugin supports "
            f"{store.FORMAT}); update dot-claude")

    def test_awkward_titles_round_trip(self):
        title = 'OPNsense: "quoted" --- é'
        t = make_ticket(
            title=title,
            log=[LogEntry("2026-10-18T09:00:00Z", "s", "line1\nline2")],
        )
        store.write_ticket(self.root, t)
        loaded = store.load_quests(self.root).tickets[t.id]
        self.assertEqual(loaded.title, title)
        self.assertEqual(loaded.log[0].text, "line1 / line2")

    def test_line_separators_round_trip(self):
        for sep in ("\u2028", "\x85", "\x0b", "\u2029", "\x0c", "\x1c"):
            with self.subTest(sep=repr(sep)):
                t = make_ticket(
                    title=f"a{sep}b",
                    log=[
                        LogEntry("2026-10-18T09:00:00Z", "s", f"x{sep}y"),
                        LogEntry("2026-10-18T09:01:00Z", "s", "next"),
                    ],
                )
                store.write_ticket(self.root, t)
                loaded = store.load_quests(self.root).tickets[t.id]
                self.assertEqual(loaded.title, t.title)
                self.assertEqual([e.text for e in loaded.log], ["x / y", "next"])

    def test_session_with_paren_and_space(self):
        t = make_ticket(log=[LogEntry("2026-10-18T09:00:00Z", "a) b", "hello (x) y")])
        store.write_ticket(self.root, t)
        e = store.load_quests(self.root).tickets[t.id].log[0]
        self.assertEqual((e.session, e.text), ("a__b", "hello (x) y"))

    def test_frontmatter_key_order_is_stable(self):
        path = store.write_ticket(self.root, make_ticket())
        expected = (
            "---\n"
            'id: "t-abc12"\n'
            'title: "Set up backups"\n'
            'status: "in_progress"\n'
            'goal: "g-xyz89"\n'
            "parent: null\n"
            'blocked_by: ["t-def34"]\n'
            'owner: {"session": "sess-1", "label": "alice", "where": "local", '
            '"claimed_at": "2026-10-18T10:00:00Z"}\n'
            'links: ["https://example.com/pr/1"]\n'
            'created: "2026-10-18T09:00:00Z"\n'
            'updated: "2026-10-18T10:00:00Z"\n'
            "---\n"
            "# Set up backups\n"
            "\n"
            "## Log\n"
            "- 2026-10-18T09:00:00Z (sess-1) created\n"
            "- 2026-10-18T10:00:00Z (sess-2) started work\n"
        )
        self.assertEqual(path.read_text(encoding="utf-8"), expected)
        self.assertEqual(path, self.root / "tickets" / "t-abc12.md")

    def test_goal_file_format(self):
        path = store.write_goal(self.root, Goal("g-xyz89", "Example goal", 2, []))
        expected = (
            "---\n"
            'id: "g-xyz89"\n'
            'title: "Example goal"\n'
            "order: 2\n"
            "links: []\n"
            "---\n"
            "# Example goal\n"
        )
        self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_null_owner_round_trip(self):
        t = make_ticket(owner=None, goal=None, blocked_by=[], links=[])
        store.write_ticket(self.root, t)
        self.assertEqual(store.load_quests(self.root).tickets[t.id], t)

    def test_new_id_format(self):
        for _ in range(50):
            self.assertRegex(store.new_id("t", set()), r"^t-[a-z0-9]{5}$")
        self.assertRegex(store.new_id("g", set()), r"^g-[a-z0-9]{5}$")
        existing = {store.new_id("t", set()) for _ in range(20)}
        for _ in range(50):
            self.assertNotIn(store.new_id("t", existing), existing)

    def test_load_empty_quests(self):
        qlog = store.load_quests(self.root)
        self.assertEqual(qlog.goals, {})
        self.assertEqual(qlog.tickets, {})
        self.assertEqual(json.loads((self.root / "board.json").read_text()), qlog.meta)


if __name__ == "__main__":
    unittest.main()
