import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quests import cli, hooks, locate, migrate
from tests import gitfixture as gf

OLD = "claude/board"
NEW = "claude/quests"


def tip(repo, branch):
    p = gf.git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    return p.stdout.strip() or None


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        ctx = gf.isolated(self.tmp)
        self.state = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        for k in ("QUESTS_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "QUESTS_SESSION_LABEL",
                  "QUESTS_WHERE", "CLAUDE_CODE_REMOTE", "CLAUDE_ENV_FILE"):
            os.environ.pop(k, None)
        self.old_state = self.tmp / "home" / ".claude" / "state" / "board"
        self.origin = gf.make_remote(self.tmp, "origin.git", branch=OLD)
        self.repo = gf.make_code_repo(self.tmp, self.origin)
        self.key = locate.repo_key(self.repo)

    def run_cli(self, *argv, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), cwd=cwd or self.repo)
        return code, out.getvalue(), err.getvalue()

    def test_creates_branch_at_same_commit_and_leaves_old_alone(self):
        old = tip(self.origin, OLD)
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(tip(self.origin, NEW), old)
        self.assertEqual(tip(self.origin, OLD), old)
        self.assertIn(f"Created {NEW} at {old[:7]}", out)
        self.assertIn(f"{OLD} was left untouched", out)
        # the new branch is a working quest log now
        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cli("add", "Example task", "--session", "s1")[0], 0)
        self.assertNotEqual(tip(self.origin, NEW), old)
        self.assertEqual(tip(self.origin, OLD), old)

    def test_is_idempotent(self):
        old = tip(self.origin, OLD)
        self.run_cli("migrate")
        code, out, _ = self.run_cli("migrate")
        self.assertEqual(code, 0)
        self.assertIn(f"{NEW} already exists; nothing to do.", out)
        self.assertNotIn("Created", out)
        self.assertEqual((tip(self.origin, NEW), tip(self.origin, OLD)), (old, old))

    def test_existing_new_branch_is_never_touched(self):
        seed = self.tmp / "seed"
        gf.git(self.tmp, "init", "-q", str(seed))
        gf.git(seed, "checkout", "-q", "--orphan", "n")
        (seed / "board.json").write_text('{"schema": 1, "code_repo": "other"}\n')
        gf.git(seed, "add", "-A")
        gf.git(seed, "commit", "-q", "-m", "quests: init")
        gf.git(seed, "push", "-q", str(self.origin), f"n:refs/heads/{NEW}")
        new, old = tip(self.origin, NEW), tip(self.origin, OLD)
        self.assertNotEqual(new, old)
        code, out, _ = self.run_cli("migrate")
        self.assertEqual(code, 0)
        self.assertIn("already exists", out)
        self.assertEqual((tip(self.origin, NEW), tip(self.origin, OLD)), (new, old))

    def test_nothing_to_migrate(self):
        origin = gf.make_remote(self.tmp, "plain.git", branch=None)
        repo = gf.make_code_repo(self.tmp, origin, name="plain")
        code, out, _ = self.run_cli("migrate", cwd=repo)
        self.assertEqual(code, 0)
        self.assertIn("No old board found", out)
        self.assertIsNone(tip(origin, NEW))

    def test_branch_without_marker_is_left_alone(self):
        origin = gf.make_remote(self.tmp, "foreign.git", branch=None)
        seed = self.tmp / "fseed"
        gf.git(self.tmp, "init", "-q", str(seed))
        (seed / "x.txt").write_text("unrelated\n")
        gf.git(seed, "add", "-A")
        gf.git(seed, "commit", "-q", "-m", "unrelated")
        gf.git(seed, "push", "-q", str(origin), f"HEAD:refs/heads/{OLD}")
        repo = gf.make_code_repo(self.tmp, origin, name="foreign")
        code, out, _ = self.run_cli("migrate", cwd=repo)
        self.assertEqual(code, 0)
        self.assertIn("left alone", out)
        self.assertIsNone(tip(origin, NEW))

    def test_unreachable_remote_is_refused_with_exit_4(self):
        gf.git(self.repo, "remote", "set-url", "origin", str(self.tmp / "gone.git"))
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 4)
        self.assertNotIn("Traceback", out + err)

    def test_repo_without_origin_migrates_locally(self):
        repo = gf.make_code_repo(self.tmp, None, name="solo")
        gf.git(repo, "fetch", "-q", str(self.origin), f"{OLD}:{OLD}")
        old = tip(repo, OLD)
        code, out, err = self.run_cli("migrate", cwd=repo)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(tip(repo, NEW), old)
        self.assertEqual(tip(repo, OLD), old)
        self.assertEqual(self.run_cli("log", cwd=repo)[0], 0)

    def test_external_board_and_config_entry(self):
        slug = locate.slug(self.key)
        ext = gf.make_remote(self.tmp, "ext.git", branch=f"board/{slug}")
        old = tip(ext, f"board/{slug}")
        plain = gf.make_remote(self.tmp, "plain.git", branch=None)
        gf.git(self.repo, "remote", "set-url", "origin", str(plain))
        key = locate.repo_key(self.repo)
        self.old_state.mkdir(parents=True)
        (self.old_state / "config.json").write_text(json.dumps(
            {key: {"mode": "external", "url": str(ext), "branch": f"board/{slug}"}}))
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(tip(ext, f"quests/{slug}"), old)
        self.assertEqual(tip(ext, f"board/{slug}"), old)
        entry = json.loads((self.state / "config.json").read_text())[key]
        self.assertEqual((entry["mode"], entry["url"], entry["branch"]),
                         ("external", str(ext), f"quests/{slug}"))
        # the old config file is untouched
        self.assertIn(f"board/{slug}", (self.old_state / "config.json").read_text())

    def test_external_board_found_through_the_old_env_var(self):
        plain = gf.make_remote(self.tmp, "plain.git", branch=None)
        gf.git(self.repo, "remote", "set-url", "origin", str(plain))
        slug = locate.slug(locate.repo_key(self.repo))
        ext = gf.make_remote(self.tmp, "ext.git", branch=f"board/{slug}")
        os.environ["CLAUDE_BOARD_REPO"] = str(ext)
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(tip(ext, f"quests/{slug}"), tip(ext, f"board/{slug}"))

    def test_other_repos_old_style_entries_are_rewritten_once_migrated_else_skipped(self):
        other = gf.make_remote(self.tmp, "other.git", branch=OLD)
        self.old_state.mkdir(parents=True)
        good = {"mode": "same", "url": str(other), "branch": OLD}
        bad = {"mode": "same", "url": str(self.tmp / "gone.git"), "branch": OLD}
        fine = {"mode": "same", "url": "x", "branch": NEW}
        (self.old_state / "config.json").write_text(json.dumps(
            {"example.com/acme/good": good, "example.com/acme/bad": bad, "example.com/acme/fine": fine}))
        self.run_cli("migrate")
        cfg = json.loads((self.state / "config.json").read_text())
        self.assertEqual(cfg["example.com/acme/good"], dict(good, branch=NEW))
        self.assertEqual(tip(other, NEW), tip(other, OLD))
        self.assertNotIn("example.com/acme/bad", cfg)
        self.assertEqual(cfg["example.com/acme/fine"], fine)
        self.assertEqual(cfg[self.key]["branch"], NEW)
        self.assertFalse(any(locate.is_old_branch(e["branch"]) for e in cfg.values()))
        self.run_cli("migrate")  # idempotent
        self.assertEqual(json.loads((self.state / "config.json").read_text()), cfg)

    def test_old_style_config_entry_is_never_used_as_is(self):
        self.state.mkdir(parents=True)
        entry = {"mode": "same", "url": str(self.origin), "branch": OLD}
        (self.state / "config.json").write_text(json.dumps({self.key: entry}))
        self.assertIsNone(locate.resolve(self.repo))
        self.assertEqual(self.run_cli("log")[0], 2)
        old = tip(self.origin, OLD)
        lines = hooks.session_start({"session_id": "s1", "cwd": str(self.repo)})
        self.assertTrue(any("migrated the old board" in l for l in lines), lines)
        self.assertEqual(tip(self.origin, NEW), old)
        ref = locate.resolve(self.repo)
        self.assertEqual(ref.branch, NEW)
        self.assertEqual(self.run_cli("add", "Example task", "--session", "s1")[0], 0)
        self.assertEqual(tip(self.origin, OLD), old)

    def test_offline_first_run_retries_and_is_not_cached(self):
        import time
        gone = str(self.tmp / "gone.git")
        gf.git(self.repo, "remote", "set-url", "origin", gone)
        key = locate.repo_key(self.repo)
        self.old_state.mkdir(parents=True)
        (self.old_state / "config.json").write_text(json.dumps(
            {key: {"mode": "same", "url": gone, "branch": OLD}}))
        want = ["Quests: couldn't reach the remote to check for an existing board; will retry next session."]
        for sid in ("s1", "s2"):
            t0 = time.monotonic()
            self.assertEqual(hooks.session_start({"session_id": sid, "cwd": str(self.repo)}), want)
            self.assertLess(time.monotonic() - t0, 8)
        self.assertFalse((self.state / "negative.json").exists() and
                         key in json.loads((self.state / "negative.json").read_text()))
        self.assertFalse((self.state / "migrate-attempts.json").exists())

    def test_session_start_does_not_push_a_moved_journal(self):
        jdir = self.old_state / "journal"
        jdir.mkdir(parents=True)
        op = {"op": "create_ticket", "at": "2026-01-01T00:00:00Z", "session": "s0",
              "id": "t-jrnl1", "title": "Carried journal task", "goal": None, "parent": None, "links": []}
        (jdir / f"{locate.slug(self.key)}.jsonl").write_text(json.dumps(op) + "\n")
        old = tip(self.origin, OLD)
        lines = hooks.session_start({"session_id": "s1", "cwd": str(self.repo)})
        self.assertTrue(any("Carried journal task" in l or "Quests:" in l for l in lines))
        self.assertEqual(tip(self.origin, NEW), old)  # not pushed from the hook
        self.run_cli("sync")  # the next normal sync pushes it
        self.assertNotEqual(tip(self.origin, NEW), old)
        self.assertIn("t-jrnl1", self.run_cli("show", "t-jrnl1")[1])

    def test_init_refuses_when_a_marked_old_branch_exists(self):
        old = tip(self.origin, OLD)
        code, out, err = self.run_cli("init", "--mode", "same")
        self.assertEqual(code, 4)
        self.assertIn("an old board exists on claude/board; run `quest migrate`", out + err)
        self.assertIsNone(tip(self.origin, NEW))
        self.assertEqual(tip(self.origin, OLD), old)

    def test_concurrent_submit_does_not_lose_moved_ops(self):
        import threading
        from quests import sync
        self.assertEqual(self.run_cli("init", "--mode", "same")[0], 4)
        self.run_cli("migrate")
        ref = locate.resolve(self.repo)
        slug = locate.slug(self.key)
        jdir = self.old_state / "journal"
        jdir.mkdir(parents=True)
        ops = [{"op": "create_ticket", "at": "2026-01-01T00:00:00Z", "session": "s0",
                "id": f"t-old{i}", "title": f"Old {i}", "goal": None, "parent": None, "links": []}
               for i in range(5)]
        (jdir / f"{slug}.jsonl").write_text("".join(json.dumps(o) + "\n" for o in ops))
        errors = []

        def submit(i):
            try:
                op = dict(ops[0], id=f"t-new{i}", title=f"New {i}")
                sync.submit(ref, op, lock_wait=30)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=migrate.migrate_state)] + \
                  [threading.Thread(target=submit, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        sync.sync(ref)
        from quests import store
        have = set(store.load_quests(sync.checkout_dir(ref)).tickets)
        self.assertEqual(have, {f"t-old{i}" for i in range(5)} | {f"t-new{i}" for i in range(4)})

    def test_pending_journal_moves_and_replays_on_next_sync(self):
        jdir = self.old_state / "journal"
        jdir.mkdir(parents=True)
        slug = locate.slug(self.key)
        op = {"op": "create_ticket", "at": "2026-01-01T00:00:00Z", "session": "s0",
              "id": "t-jrnl1", "title": "Carried journal task", "goal": None, "parent": None, "links": []}
        (jdir / f"{slug}.jsonl").write_text(json.dumps(op) + "\n")
        (jdir / "empty.jsonl").write_text("\n")
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        self.assertIn("Moved 1 pending journal entry", out)
        self.assertEqual((self.old_state / "journal" / f"{slug}.jsonl").read_text(), "")
        self.assertFalse((self.state / "journal" / "empty.jsonl").exists())
        self.assertIn("t-jrnl1", (self.state / "journal" / f"{slug}.jsonl").read_text())
        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 0)
        _, out, _ = self.run_cli("show", "t-jrnl1")
        self.assertIn("Carried journal task", out)
        self.run_cli("migrate")  # nothing left to move
        self.assertEqual((self.state / "journal" / f"{slug}.jsonl").read_text(), "")

    def test_auto_migrate_on_session_start(self):
        old = tip(self.origin, OLD)
        lines = hooks.session_start({"session_id": "s1", "cwd": str(self.repo)})
        self.assertEqual(tip(self.origin, NEW), old)
        self.assertEqual(tip(self.origin, OLD), old)
        self.assertTrue(any(l.startswith(f"Quests: migrated the old board to {NEW}") for l in lines), lines)
        self.assertEqual(lines[0], "Quests: example/repo")
        again = hooks.session_start({"session_id": "s2", "cwd": str(self.repo)})
        self.assertFalse(any("migrated" in l for l in again), again)
        self.assertEqual(tip(self.origin, NEW), old)

    def test_auto_migrate_failure_prints_hint_and_carries_on(self):
        err = migrate.MigrateError("push refused", found=True)
        with mock.patch.object(migrate, "migrate_branch", side_effect=err) as m:
            lines = hooks.session_start({"session_id": "s1", "cwd": str(self.repo)})
            self.assertEqual(len(lines), 1)
            self.assertIn("quest migrate", lines[0])
            self.assertEqual(m.call_count, 1)
            again = hooks.session_start({"session_id": "s2", "cwd": str(self.repo)})
            self.assertEqual(again, lines)
            self.assertEqual(m.call_count, 1)  # tried once, not on every session start
        self.assertIsNone(tip(self.origin, NEW))
        self.assertIn("push refused", (self.state / "hook-errors.log").read_text())

    def test_auto_migrate_unexpected_error_never_fails_the_session(self):
        with mock.patch.object(migrate, "migrate", side_effect=RuntimeError("boom")):
            lines = hooks.session_start({"session_id": "s1", "cwd": str(self.repo)})
        self.assertEqual(len(lines), 1)

    def test_no_old_board_keeps_the_plain_hint(self):
        origin = gf.make_remote(self.tmp, "plain.git", branch=None)
        repo = gf.make_code_repo(self.tmp, origin, name="plain")
        lines = hooks.session_start({"session_id": "s1", "cwd": str(repo)})
        self.assertEqual(lines, [hooks.NO_QUESTS])


if __name__ == "__main__":
    unittest.main()
