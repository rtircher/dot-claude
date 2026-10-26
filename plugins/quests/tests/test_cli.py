import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from quests import cli, store
from tests import gitfixture as gf

BIN = Path(__file__).resolve().parents[1] / "bin" / "quest"


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        ctx = gf.isolated(self.tmp)
        self.state = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        for k in ("QUESTS_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "QUESTS_SESSION_LABEL",
                  "QUESTS_WHERE", "CLAUDE_CODE_REMOTE"):
            os.environ.pop(k, None)
        self.origin = gf.make_remote(self.tmp, "origin.git", branch=None)
        self.repo = gf.make_code_repo(self.tmp, self.origin)

    def run_cli(self, *argv, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), cwd=cwd or self.repo)
        return code, out.getvalue(), err.getvalue()

    def init_same(self):
        code, out, err = self.run_cli("init", "--mode", "same")
        self.assertEqual(code, 0, out + err)

    def test_no_quests_exit_2_with_hint(self):
        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 2)
        self.assertIn("No quest log for this repo. Run: quest init --mode same|external [--url URL]", out)

    def test_sync_bypasses_fresh_negative_cache(self):
        self.assertEqual(self.run_cli("log")[0], 2)
        self.assertTrue((self.state / "negative.json").exists())
        seed = self.tmp / "seed"
        gf.git(self.tmp, "init", "-q", str(seed))
        gf.git(seed, "checkout", "-q", "--orphan", gf.BRANCH)
        (seed / "board.json").write_text('{"code_repo": "example/repo"}\n', encoding="utf-8")
        gf.git(seed, "add", "-A")
        gf.git(seed, "commit", "-q", "-m", "quests: init")
        gf.git(seed, "push", "-q", str(self.origin), f"{gf.BRANCH}:refs/heads/{gf.BRANCH}")
        self.assertEqual(self.run_cli("log")[0], 2)
        code, out, err = self.run_cli("sync")
        self.assertNotEqual(code, 2, out + err)
        self.assertEqual(self.run_cli("log")[0], 0)

    def test_outside_git_exit_2(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        code, out, err = self.run_cli("log", cwd=plain)
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", out + err)

    def test_init_same_then_add_and_log_json(self):
        self.init_same()
        code, out, _ = self.run_cli("main", "add", "Example goal")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("add", "Set up backups", "--session", "s1")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("log", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(set(data), {"repo", "synced", "goals", "sessions", "next", "next_more", "stale"})
        self.assertTrue(data["synced"])
        self.assertEqual(data["goals"][0]["title"], "Example goal")
        self.assertEqual(data["next"][0]["title"], "Set up backups")
        self.assertEqual(data["repo"], data["repo"] or "")

    def test_log_next_limit(self):
        self.init_same()
        for i in range(7):
            self.run_cli("add", f"Example task {i}", "--session", "s1")
        data = json.loads(self.run_cli("log", "--json")[1])
        self.assertEqual((len(data["next"]), data["next_more"]), (5, 2))
        data = json.loads(self.run_cli("log", "--json", "--next-limit", "100")[1])
        self.assertEqual((len(data["next"]), data["next_more"]), (7, 0))

    def test_html_writes_file_and_prints_path(self):
        self.init_same()
        self.run_cli("main", "add", "Example goal")
        self.run_cli("add", "Set up backups", "--session", "s1")
        out_path = self.tmp / "out" / "quests.html"
        code, out, _ = self.run_cli("html", "--out", str(out_path), "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["path"], str(out_path))
        self.assertIn("Set up backups", out_path.read_text(encoding="utf-8"))
        code, out, _ = self.run_cli("html")
        self.assertEqual(code, 0)
        default = Path(out.strip())
        self.assertTrue(default.exists())
        self.assertEqual(default.parent.name, "html")

    def test_add_prints_id_and_text_summary(self):
        self.init_same()
        code, out, _ = self.run_cli("add", "Title: with \"quotes\" and --- dashes")
        self.assertEqual(code, 0)
        tid = out.strip().split()[0]
        code, out, _ = self.run_cli("show", tid)
        self.assertIn("with \"quotes\" and ---", out)
        code, out, _ = self.run_cli("next")
        self.assertIn(tid, out)

    def test_init_refuses_foreign_branch(self):
        seed = self.tmp / "seed"
        gf.git(self.tmp, "init", "-q", str(seed))
        (seed / "x.txt").write_text("unrelated\n")
        gf.git(seed, "add", "-A")
        gf.git(seed, "commit", "-q", "-m", "unrelated")
        gf.git(seed, "push", "-q", str(self.origin), "HEAD:refs/heads/claude/quests")
        tip = gf.git(self.origin, "rev-parse", "claude/quests").stdout
        code, out, err = self.run_cli("init", "--mode", "same")
        self.assertEqual(code, 4)
        self.assertIn("exists and is not a quest log; nothing changed", out + err)
        self.assertEqual(gf.git(self.origin, "rev-parse", "claude/quests").stdout, tip)

    def test_init_adopts_existing_quests(self):
        seed = self.tmp / "seed"
        gf.git(self.tmp, "init", "-q", str(seed))
        gf.git(seed, "checkout", "-q", "--orphan", "b")
        (seed / "board.json").write_text('{"schema": 1, "code_repo": "x"}\n')
        gf.git(seed, "add", "-A")
        gf.git(seed, "commit", "-q", "-m", "quests: init")
        gf.git(seed, "push", "-q", str(self.origin), "b:refs/heads/claude/quests")
        tip = gf.git(self.origin, "rev-parse", "claude/quests").stdout
        self.init_same()
        self.assertEqual(gf.git(self.origin, "rev-parse", "claude/quests").stdout, tip)
        self.assertEqual(self.run_cli("log")[0], 0)

    def test_init_does_not_touch_code_repo(self):
        before = gf.git(self.repo, "status", "--porcelain").stdout
        head = gf.git(self.repo, "rev-parse", "HEAD").stdout
        branch = gf.git(self.repo, "branch", "--show-current").stdout
        self.init_same()
        self.assertEqual(gf.git(self.repo, "status", "--porcelain").stdout, before)
        self.assertEqual(gf.git(self.repo, "rev-parse", "HEAD").stdout, head)
        self.assertEqual(gf.git(self.repo, "branch", "--show-current").stdout, branch)

    def test_init_same_without_origin_uses_local_repo(self):
        repo = gf.make_code_repo(self.tmp, None, name="solo")
        code, out, err = self.run_cli("init", "--mode", "same", cwd=repo)
        self.assertEqual(code, 0, out + err)
        gf.git(repo, "rev-parse", "--verify", "refs/heads/claude/quests")
        self.assertEqual(self.run_cli("log", cwd=repo)[0], 0)

    def test_init_external_writes_config_and_branch_name(self):
        ext = gf.make_remote(self.tmp, "ext.git", branch=None)
        gf.git(self.repo, "remote", "set-url", "origin", "git@github.com:example/repo.git")
        code, out, err = self.run_cli("init", "--mode", "external", "--url", str(ext))
        self.assertEqual(code, 0, out + err)
        cfg = json.loads((self.state / "config.json").read_text())
        entry = cfg["github.com/example/repo"]
        self.assertEqual(entry["mode"], "external")
        self.assertEqual(entry["url"], str(ext))
        self.assertEqual(entry["branch"], "quests/github-com-example-repo")
        gf.git(ext, "rev-parse", "--verify", "quests/github-com-example-repo")

    def test_take_refused_when_owned(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.assertEqual(self.run_cli("take", tid, "--session", "s-alpha")[0], 0)
        os.environ["QUESTS_SESSION_LABEL"] = "beta"
        code, out, err = self.run_cli("take", tid, "--session", "s-beta")
        self.assertEqual(code, 3)
        self.assertIn("alpha", out + err)
        # same session may re-claim
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.assertEqual(self.run_cli("take", tid, "--session", "s-alpha")[0], 0)

    def test_take_takes_over_stale_owner(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        sdir = self.state / "sessions"
        sdir.mkdir(parents=True)
        from quests import locate
        rk = locate.repo_key(self.repo)
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.run_cli("take", tid, "--session", "s-alpha")
        (sdir / "s-alpha.json").write_text(json.dumps(
            {"session": "s-alpha", "label": "alpha", "where": "local", "repo_key": rk,
             "state": "ended", "last_seen": "2026-01-01T00:00:00Z"}))
        os.environ["QUESTS_SESSION_LABEL"] = "beta"
        code, out, err = self.run_cli("take", tid, "--session", "s-beta")
        self.assertEqual(code, 0, out + err)
        code, out, _ = self.run_cli("show", tid)
        self.assertIn("taken over from alpha", out)

    def test_take_takes_over_dead_owners_blocked_ticket(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        from quests import locate
        rk = locate.repo_key(self.repo)
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.run_cli("take", tid, "--session", "s-alpha")
        self.assertEqual(self.run_cli("status", tid, "blocked", "--session", "s-alpha")[0], 0)
        sdir = self.state / "sessions"
        sdir.mkdir(parents=True)
        (sdir / "s-alpha.json").write_text(json.dumps(
            {"session": "s-alpha", "label": "alpha", "where": "local", "repo_key": rk,
             "state": "ended", "last_seen": "2026-01-01T00:00:00Z"}))
        os.environ["QUESTS_SESSION_LABEL"] = "beta"
        code, out, err = self.run_cli("take", tid, "--session", "s-beta")
        self.assertEqual(code, 0, out + err)
        self.assertIn("taken over from alpha", self.run_cli("show", tid)[1])

    def test_only_claims_exit_3_from_replayed_warnings(self):
        from unittest import mock
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        replay = ["claim on t999 by s-other lost to alpha"]
        real = cli.sync.submit

        def fake(ref, op):
            res = real(ref, op)
            res.warnings = list(res.warnings) + replay
            return res

        with mock.patch.object(cli.sync, "submit", fake):
            self.assertEqual(self.run_cli("note", tid, "hello", "--session", "s1")[0], 0)
            self.assertEqual(self.run_cli("take", tid, "--session", "s1")[0], 0)
            fake2 = lambda ref, op: type("R", (), {"synced": True, "warnings": [
                f"claim on {tid} by s2 lost to alpha"]})()
        with mock.patch.object(cli.sync, "submit", fake2):
            self.assertEqual(self.run_cli("take", tid, "--session", "s2")[0], 3)

    def test_take_without_session_exits_1(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        code, out, err = self.run_cli("take", out.strip().split()[0])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)

    def test_session_from_env(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        os.environ["CLAUDE_CODE_SESSION_ID"] = "abcdef123456"
        self.assertEqual(self.run_cli("take", tid)[0], 0)
        _, out, _ = self.run_cli("show", tid, "--json")
        self.assertEqual(json.loads(out)["owner"]["label"], "abcdef12")

    def test_add_side_quest_with_parent(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Parent work")
        parent = out.strip().split()[0]
        _, out, _ = self.run_cli("add", "Side quest", "--parent", parent)
        child = out.strip().split()[0]
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.run_cli("take", child, "--session", "s1")
        _, out, _ = self.run_cli("log", "--json", "--session", "s1")
        chain = json.loads(out)["sessions"][0]["chain"]
        self.assertEqual([c["title"] for c in chain], ["Parent work", "Side quest"])

    def test_status_note_link_drop(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        self.assertEqual(self.run_cli("note", tid, "line one\nline two")[0], 0)
        self.assertEqual(self.run_cli("link", tid, "https://example.com/x")[0], 0)
        self.assertEqual(self.run_cli("status", tid, "blocked")[0], 0)
        self.assertEqual(self.run_cli("status", tid, "bogus")[0], 1)
        _, out, _ = self.run_cli("show", tid, "--json")
        d = json.loads(out)
        self.assertEqual(d["status"], "blocked")
        self.assertIn("https://example.com/x", d["links"])
        self.assertTrue(any("line one / line two" in e["text"] for e in d["log"]))
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.run_cli("take", tid, "--session", "s1")
        self.assertEqual(self.run_cli("drop", tid)[0], 0)
        _, out, _ = self.run_cli("show", tid, "--json")
        self.assertEqual(json.loads(out)["status"], "todo")
        self.assertIsNone(json.loads(out)["owner"])

    def test_main_list_and_sync(self):
        self.init_same()
        self.run_cli("main", "add", "Example goal", "--link", "https://example.com/g")
        code, out, _ = self.run_cli("main", "list", "--json")
        self.assertEqual(json.loads(out)[0]["title"], "Example goal")
        self.assertEqual(self.run_cli("sync")[0], 0)

    def test_side_files_under_current_quest(self):
        self.init_same()
        self.run_cli("main", "add", "Example main quest")
        main_id = json.loads(self.run_cli("main", "list", "--json")[1])[0]["id"]
        _, out, _ = self.run_cli("add", "Parent work", "--main", main_id)
        parent = out.strip().split()[0]
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.assertEqual(self.run_cli("take", parent, "--session", "s1")[0], 0)
        code, out, err = self.run_cli("side", "Side quest", "--link", "https://example.com/s", "--session", "s1")
        self.assertEqual(code, 0, out + err)
        child = out.strip().split()[0]
        d = json.loads(self.run_cli("show", child, "--json")[1])
        self.assertEqual((d["parent"], d["goal"], d["status"]), (parent, main_id, "todo"))
        self.assertEqual(d["links"], ["https://example.com/s"])
        # the newest take wins, like the chain in the log
        self.run_cli("take", child, "--session", "s1")
        _, out, _ = self.run_cli("side", "Deeper", "--session", "s1", "--json")
        self.assertEqual(json.loads(out)["parent"], child)

    def test_side_without_current_quest_exits_2(self):
        self.init_same()
        code, out, err = self.run_cli("side", "Orphan", "--session", "s1")
        self.assertEqual(code, 2)
        self.assertIn("quest add", out + err)
        self.assertNotIn("Traceback", out + err)
        _, out, _ = self.run_cli("add", "Mine")
        self.run_cli("take", out.strip().split()[0], "--session", "s-other")
        self.assertEqual(self.run_cli("side", "Orphan", "--session", "s1")[0], 2)
        self.assertEqual(self.run_cli("side", "Orphan")[0], 2)  # no session at all

    def test_done_sets_status_and_points_back_to_parent(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Parent work")
        parent = out.strip().split()[0]
        os.environ["QUESTS_SESSION_LABEL"] = "alpha"
        self.run_cli("take", parent, "--session", "s1")
        _, out, _ = self.run_cli("side", "Side quest", "--session", "s1")
        child = out.strip().split()[0]
        self.run_cli("take", child, "--session", "s1")
        code, out, _ = self.run_cli("done", child, "--session", "s1")
        self.assertEqual(code, 0)
        self.assertIn(f"Back to: {parent} Parent work  (run: quest take {parent})", out)
        self.assertEqual(json.loads(self.run_cli("show", child, "--json")[1])["status"], "done")
        code, out, _ = self.run_cli("done", child, "--json")
        self.assertEqual(json.loads(out)["back_to"], {"id": parent, "title": "Parent work"})
        code, out, _ = self.run_cli("done", parent, "--session", "s1")
        self.assertEqual(code, 0)
        self.assertNotIn("Back to", out)
        code, out, _ = self.run_cli("done", child)
        self.assertNotIn("Back to", out)  # parent is done now

    def test_done_and_status_with_unknown_id_exit_2(self):
        self.init_same()
        for argv in (("done", "t-nope"), ("status", "t-nope", "done")):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 2)
            self.assertIn("no such quest: t-nope", out + err)

    def test_status_still_accepts_all_statuses(self):
        self.init_same()
        _, out, _ = self.run_cli("add", "Set up backups")
        tid = out.strip().split()[0]
        for st in ("todo", "in_progress", "blocked", "done", "dropped"):
            self.assertEqual(self.run_cli("status", tid, st)[0], 0)

    def test_unsynced_line_when_remote_unreachable(self):
        self.init_same()
        self.run_cli("sync")
        cfg = json.loads((self.state / "config.json").read_text())
        for v in cfg.values():
            v["url"] = str(self.tmp / "gone.git")
        (self.state / "config.json").write_text(json.dumps(cfg))
        code, out, _ = self.run_cli("add", "Offline task")
        self.assertEqual(code, 0)
        self.assertIn("(unsynced: will push on next sync)", out)

    def test_no_checkout_yet_prints_unsynced_exit_0(self):
        self.init_same()
        import shutil
        shutil.rmtree(self.state / "checkouts", ignore_errors=True)
        cfg = json.loads((self.state / "config.json").read_text())
        for v in cfg.values():
            v["url"] = str(self.tmp / "gone.git")
        (self.state / "config.json").write_text(json.dumps(cfg))
        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 0)
        self.assertIn("(unsynced, not fetched yet)", out)

    def add_ids(self, *titles, main=None):
        ids = []
        for t in titles:
            extra = ["--main", main] if main else []
            ids.append(json.loads(self.run_cli("add", t, "--session", "s1", "--json", *extra)[1])["id"])
        return ids

    def next_ids(self):
        return [n["id"] for n in json.loads(self.run_cli("log", "--json", "--next-limit", "50")[1])["next"]]

    def test_move_ticket_and_confirmation(self):
        self.init_same()
        gid = json.loads(self.run_cli("main", "add", "Camera work", "--json")[1])["id"]
        a, b, c = self.add_ids("Task a", "Task b", "Task c", main=gid)
        # Tickets made in one second tie on creation time, so fix the order explicitly first.
        for tid in (c, b):
            self.assertEqual(self.run_cli("move", tid, "--top")[0], 0)
        code, out, err = self.run_cli("move", a, "--top")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out.strip(), f"Moved {a} to #1 in Camera work")
        self.assertEqual(self.next_ids(), [a, b, c])
        self.assertEqual(self.run_cli("move", a, "--down")[0], 0)
        self.assertEqual(self.next_ids(), [b, a, c])
        self.assertEqual(self.run_cli("move", b, "--after", c)[0], 0)
        self.assertEqual(self.next_ids(), [a, c, b])
        self.assertEqual(self.run_cli("move", b, "--before", a)[0], 0)
        self.assertEqual(self.run_cli("move", c, "--bottom")[0], 0)
        self.assertEqual(self.next_ids(), [b, a, c])
        code, out, _ = self.run_cli("move", c, "--up", "--json")
        self.assertEqual(json.loads(out), {"id": c, "position": 2, "synced": True})

    def test_move_that_changes_nothing_says_so(self):
        self.init_same()
        gid = json.loads(self.run_cli("main", "add", "Camera work", "--json")[1])["id"]
        a, b = self.add_ids("Task a", "Task b", main=gid)
        for tid in (b, a):
            self.assertEqual(self.run_cli("move", tid, "--top")[0], 0)
        code, out, _ = self.run_cli("move", a, "--up")
        self.assertEqual((code, out.strip()), (0, f"{a} is already #1 in Camera work"))
        code, out, _ = self.run_cli("main", "move", gid, "--top")
        self.assertEqual((code, out.strip()), (0, "Main quest Camera work is already #1"))

    def test_move_ticket_without_main_quest_names_the_group(self):
        self.init_same()
        a, b = self.add_ids("Task a", "Task b")
        self.assertEqual(self.run_cli("move", a, "--top")[0], 0)  # creation times can tie
        out = self.run_cli("move", b, "--top")[1]
        self.assertEqual(out.strip(), f"Moved {b} to #1 in quests with no main quest")

    def test_move_errors(self):
        self.init_same()
        gid = json.loads(self.run_cli("main", "add", "Goal", "--json")[1])["id"]
        (a,) = self.add_ids("Task a", main=gid)
        (loose,) = self.add_ids("Loose task")
        code, out, _ = self.run_cli("move", "t-nope", "--top")
        self.assertEqual((code, out.strip()), (2, "quest: no such quest: t-nope"))
        self.assertEqual(self.run_cli("move", a, "--before", "t-nope")[0], 2)
        code, out, err = self.run_cli("move", a, "--before", loose)
        self.assertEqual(code, 1)
        self.assertIn("different main quest", out + err)
        self.assertEqual(self.run_cli("move", a)[0], 1)  # a position flag is required
        self.assertEqual(self.run_cli("move", a, "--top", "--bottom")[0], 1)
        code, out, _ = self.run_cli("main", "move", "g-nope", "--top")
        self.assertEqual((code, out.strip()), (2, "quest: no such main quest: g-nope"))

    def test_main_move(self):
        self.init_same()
        g1, g2, g3 = (json.loads(self.run_cli("main", "add", t, "--json")[1])["id"]
                      for t in ("One", "Two", "Three"))
        (t1,) = self.add_ids("In one", main=g1)
        (t3,) = self.add_ids("In three", main=g3)
        code, out, _ = self.run_cli("main", "move", g3, "--top")
        self.assertEqual((code, out.strip()), (0, "Moved main quest Three to #1"))
        self.assertEqual(self.next_ids(), [t3, t1])
        goals = json.loads(self.run_cli("main", "list", "--json")[1])
        self.assertEqual([g["id"] for g in goals], [g3, g1, g2])
        code, out, _ = self.run_cli("main", "move", g3, "--after", g1, "--json")
        self.assertEqual(json.loads(out), {"id": g3, "position": 2, "synced": True})

    def reject_pushes(self):
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

    def test_move_survives_a_rejected_push_like_done(self):
        self.init_same()
        a, b, c = self.add_ids("Task a", "Task b", "Task c")
        for tid in (c, b):  # creation times can tie, so fix the order first
            self.assertEqual(self.run_cli("move", tid, "--top")[0], 0)
        self.reject_pushes()
        code, out, _ = self.run_cli("done", a)
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("move", c, "--top")
        self.assertEqual(code, 0, out)
        self.assertIn(f"Moved {c} to #1", out)
        self.assertIn("(unsynced: will push on next sync)", out)

    def test_move_rejection_with_json_emits_an_error_document(self):
        self.init_same()
        gid = json.loads(self.run_cli("main", "add", "Goal", "--json")[1])["id"]
        (a,) = self.add_ids("Task a", main=gid)
        (loose,) = self.add_ids("Loose task")
        code, out, _ = self.run_cli("move", a, "--before", loose, "--json")
        self.assertEqual(code, 1)
        doc = json.loads(out)
        self.assertEqual(doc["id"], a)
        self.assertIn("different main quest", doc["error"])

    def test_log_shows_the_too_new_line_instead_of_unsynced(self):
        self.init_same()
        self.add_ids("Task a")
        self.make_too_new(7)
        self.run_cli("add", "Pending", "--session", "s1")  # refused: stays journaled or is not queued
        msg = store.too_new_message(7)
        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 0)
        self.assertIn(msg, out.splitlines())
        data = json.loads(self.run_cli("log", "--json")[1])
        self.assertEqual(data["format_error"], msg)

    def test_move_refused_on_too_new_log(self):
        self.init_same()
        (a,) = self.add_ids("Task a")
        self.make_too_new()
        code, out, _ = self.run_cli("move", a, "--top")
        self.assertEqual(code, 4)
        self.assertIn("needs a newer quests plugin", out)

    def make_too_new(self, n=store.FORMAT + 1):
        other = self.tmp / "newer"
        gf.git(self.tmp, "clone", "-q", "--branch", gf.BRANCH, str(self.origin), str(other))
        meta = json.loads((other / "board.json").read_text())
        meta["format"] = n
        store.write_meta(other, meta)
        gf.git(other, "add", "-A")
        gf.git(other, "commit", "-q", "-m", "bump format")
        gf.git(other, "push", "-q", "origin", f"HEAD:{gf.BRANCH}")

    def test_too_new_log_reads_but_refuses_writes(self):
        self.init_same()
        tid = json.loads(self.run_cli("add", "Existing task", "--session", "s1", "--json")[1])["id"]
        self.make_too_new(7)
        msg = ("this quest log needs a newer quests plugin (log format 7, this plugin supports "
               f"{store.FORMAT}); update dot-claude")
        self.assertEqual(self.run_cli("log")[0], 0)
        self.assertEqual(self.run_cli("sync")[0], 0)
        for argv in (("add", "New task"), ("main", "add", "Goal"), ("note", tid, "hi"),
                     ("status", tid, "done")):
            code, out, err = self.run_cli(*argv, "--session", "s1")
            self.assertEqual(code, 4, (argv, out, err))
            self.assertIn(msg, out)
        code, out, _ = self.run_cli("init", "--mode", "same")
        self.assertEqual(code, 4)
        self.assertIn(msg, out)
        self.assertIn("Existing task", self.run_cli("log")[1])

    def test_wrapper_is_executable_and_valid(self):
        self.assertTrue(BIN.stat().st_mode & stat.S_IXUSR)
        self.assertIn('quests_cli.py', BIN.read_text())


if __name__ == "__main__":
    unittest.main()
