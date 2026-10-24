import tempfile
import unittest
from pathlib import Path

from quests import ops, store


def seed(root):
    store.write_meta(root, {"code_repo": "example/repo"})


def create_ops():
    return [
        {"op": "create_goal", "at": "2026-10-18T09:00:00Z", "session": "s1",
         "id": "g-1", "title": "Example goal", "order": 1, "links": []},
        {"op": "create_ticket", "at": "2026-10-18T09:01:00Z", "session": "s1",
         "id": "t-1", "title": "Set up backups", "goal": "g-1", "parent": None, "links": []},
    ]


def owner(session="s1", label="alice"):
    return {"session": session, "label": label, "where": "local",
            "claimed_at": "2026-10-18T10:00:00Z"}


class OpsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        seed(self.root)

    def run_ops(self, items):
        warnings = []
        for o in items:
            warnings += ops.apply_op(self.root, o)
        return warnings

    def ticket(self, tid="t-1"):
        return store.load_quests(self.root).tickets[tid]

    def test_apply_create_and_note(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "note", "at": "2026-10-18T11:00:00Z", "session": "s2",
                       "id": "t-1", "text": "hello"}])
        b = store.load_quests(self.root)
        self.assertEqual(b.goals["g-1"].title, "Example goal")
        t = b.tickets["t-1"]
        self.assertEqual(t.status, "todo")
        self.assertEqual(t.goal, "g-1")
        self.assertEqual(t.updated, "2026-10-18T11:00:00Z")
        self.assertEqual((t.log[-1].session, t.log[-1].text), ("s2", "hello"))

    def test_done_releases_owner(self):
        self.run_ops(create_ops())
        self.run_ops([
            {"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1", "id": "t-1", "owner": owner()},
            {"op": "set_status", "at": "2026-10-18T12:00:00Z", "session": "s1", "id": "t-1", "status": "done"},
        ])
        t = self.ticket()
        self.assertEqual(t.status, "done")
        self.assertIsNone(t.owner)

    def test_take_sets_in_progress_and_release_restores_todo(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        self.assertEqual(self.ticket().status, "in_progress")
        self.assertEqual(self.ticket().owner.label, "alice")
        self.run_ops([{"op": "release", "at": "2026-10-18T10:30:00Z", "session": "s1", "id": "t-1"}])
        self.assertEqual(self.ticket().status, "todo")
        self.assertIsNone(self.ticket().owner)

    def test_take_lost_race_logs_and_warns(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        w = self.run_ops([{"op": "claim", "at": "2026-10-18T10:05:00Z", "session": "s2",
                           "id": "t-1", "owner": owner("s2", "bob")}])
        self.assertEqual(len(w), 1)
        t = self.ticket()
        self.assertEqual(t.owner.session, "s1")
        self.assertEqual(t.log[-1].text, "claim by s2 lost to alice")

    def test_take_same_session_is_refresh(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        w = self.run_ops([{"op": "claim", "at": "2026-10-18T10:05:00Z", "session": "s1",
                           "id": "t-1", "owner": owner()}])
        self.assertEqual(w, [])
        self.assertEqual(self.ticket().owner.session, "s1")

    def test_take_takeover_from_stale_owner(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        w = self.run_ops([{"op": "claim", "at": "2026-10-18T15:00:00Z", "session": "s2",
                           "id": "t-1", "owner": owner("s2", "bob"), "takeover_from": "s1"}])
        self.assertEqual(w, [])
        t = self.ticket()
        self.assertEqual(t.owner.session, "s2")
        self.assertEqual(t.log[-1].text, "claim taken over from alice")

    def test_take_takeover_naming_wrong_session_loses(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        w = self.run_ops([{"op": "claim", "at": "2026-10-18T15:00:00Z", "session": "s2",
                           "id": "t-1", "owner": owner("s2", "bob"), "takeover_from": "s9"}])
        self.assertEqual(len(w), 1)
        self.assertEqual(self.ticket().owner.session, "s1")

    def test_replay_is_idempotent(self):
        items = create_ops() + [
            {"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1", "id": "t-1", "owner": owner()},
            {"op": "add_link", "at": "2026-10-18T10:01:00Z", "session": "s1", "id": "t-1", "link": "https://example.com/x"},
        ]
        self.run_ops(items)
        first = {p.name: p.read_text() for p in sorted(self.root.rglob("*.md"))}
        self.run_ops(items)
        second = {p.name: p.read_text() for p in sorted(self.root.rglob("*.md"))}
        self.assertEqual(first, second)

    def test_unknown_id_warns(self):
        w = self.run_ops([{"op": "note", "at": "2026-10-18T11:00:00Z", "session": "s1",
                           "id": "t-nope", "text": "x"}])
        self.assertEqual(len(w), 1)
        self.assertFalse((self.root / "tickets" / "t-nope.md").exists())

    def test_note_replay_appends_once(self):
        self.run_ops(create_ops())
        n = {"op": "note", "at": "2026-10-18T11:00:00Z", "session": "s2", "id": "t-1", "text": "hello"}
        self.run_ops([n, n])
        self.assertEqual([e.text for e in self.ticket().log].count("hello"), 1)

    def test_lost_claim_replay_logs_once(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "claim", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "owner": owner()}])
        c = {"op": "claim", "at": "2026-10-18T10:05:00Z", "session": "s2",
             "id": "t-1", "owner": owner("s2", "bob")}
        self.run_ops([c, c])
        texts = [e.text for e in self.ticket().log]
        self.assertEqual(texts.count("claim by s2 lost to alice"), 1)

    def test_missing_fields_warn_without_raising(self):
        self.run_ops(create_ops())
        for bad in (
            {"op": "note", "at": "2026-10-18T11:00:00Z", "session": "s1", "id": "t-1"},
            {"op": "claim", "at": "2026-10-18T11:00:00Z", "session": "s1", "id": "t-1", "owner": {"session": "s1"}},
            {"op": "create_ticket", "at": "2026-10-18T11:00:00Z", "session": "s1", "id": "t-9"},
            {"op": "set_status", "session": "s1", "id": "t-1", "status": "done"},
        ):
            self.assertEqual(len(self.run_ops([bad])), 1, bad)
        self.assertEqual(self.ticket().status, "todo")
        self.assertFalse((self.root / "tickets" / "t-9.md").exists())

    def test_invalid_status_warns_and_changes_nothing(self):
        self.run_ops(create_ops())
        w = self.run_ops([{"op": "set_status", "at": "2026-10-18T11:00:00Z", "session": "s1",
                           "id": "t-1", "status": "finished"}])
        self.assertEqual(len(w), 1)
        t = self.ticket()
        self.assertEqual((t.status, t.updated), ("todo", "2026-10-18T09:01:00Z"))

    def test_take_done_ticket_warns_and_changes_nothing(self):
        self.run_ops(create_ops())
        self.run_ops([{"op": "set_status", "at": "2026-10-18T10:00:00Z", "session": "s1",
                       "id": "t-1", "status": "done"}])
        w = self.run_ops([{"op": "claim", "at": "2026-10-18T11:00:00Z", "session": "s1",
                           "id": "t-1", "owner": owner()}])
        self.assertEqual(len(w), 1)
        t = self.ticket()
        self.assertEqual((t.status, t.owner, t.updated), ("done", None, "2026-10-18T10:00:00Z"))

    def test_unknown_op_warns(self):
        w = self.run_ops([{"op": "frobnicate", "at": "2026-10-18T11:00:00Z", "session": "s1"}])
        self.assertEqual(len(w), 1)

    def test_set_goal_and_add_link(self):
        self.run_ops(create_ops())
        self.run_ops([
            {"op": "create_goal", "at": "2026-10-18T09:02:00Z", "session": "s1",
             "id": "g-2", "title": "Second goal", "order": 2, "links": []},
            {"op": "set_goal", "at": "2026-10-18T09:03:00Z", "session": "s1", "id": "t-1", "goal": "g-2"},
            {"op": "add_link", "at": "2026-10-18T09:04:00Z", "session": "s1", "id": "t-1", "link": "https://example.com/y"},
        ])
        t = self.ticket()
        self.assertEqual(t.goal, "g-2")
        self.assertEqual(t.links, ["https://example.com/y"])


if __name__ == "__main__":
    unittest.main()
