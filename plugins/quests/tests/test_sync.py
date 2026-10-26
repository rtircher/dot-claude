import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from quests import ops, store, sync
from quests.locate import QuestsRef
from tests import gitfixture as gf

T = "2026-10-18T09:00:00Z"


def ticket_op(tid, session="s1"):
    return {"op": "create_ticket", "at": T, "session": session, "id": tid,
            "title": "Set up backups", "goal": None, "parent": None, "links": []}


def note_op(tid, text, session="s1", at=T):
    return {"op": "note", "at": at, "session": session, "id": tid, "text": text}


class SyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        ctx = gf.isolated(self.tmp)
        self.state = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.remote = gf.make_remote(self.tmp)
        self.ref = QuestsRef("example.com/acme/widgets", "same", str(self.remote), "claude/quests")

    def remote_tickets(self):
        view = self.tmp / "view"
        shutil.rmtree(view, ignore_errors=True)
        gf.git(self.tmp, "clone", "-q", "--branch", "claude/quests", str(self.remote), str(view))
        return store.load_quests(view).tickets, view

    def machine(self, name):
        """Context manager switching QUESTS_STATE_DIR to another simulated machine."""
        import contextlib

        @contextlib.contextmanager
        def cm():
            old = os.environ["QUESTS_STATE_DIR"]
            os.environ["QUESTS_STATE_DIR"] = str(self.tmp / name)
            try:
                yield
            finally:
                os.environ["QUESTS_STATE_DIR"] = old

        return cm()

    def test_submit_pushes_and_clears_journal(self):
        res = sync.submit(self.ref, ticket_op("t-1"))
        self.assertTrue(res.synced)
        self.assertEqual(res.warnings, [])
        tickets, view = self.remote_tickets()
        self.assertIn("t-1", tickets)
        journal = self.state / "journal" / "example-com-acme-widgets.jsonl"
        self.assertEqual(journal.read_text(), "")
        log = gf.git(view, "log", "--format=%s").stdout.splitlines()
        self.assertEqual(log[0], "quests: create_ticket t-1")

    def test_noop_op_makes_no_commit(self):
        sync.submit(self.ref, ticket_op("t-1"))
        sync.submit(self.ref, ticket_op("t-1"))  # already exists: no file change
        _, view = self.remote_tickets()
        subjects = gf.git(view, "log", "--format=%s").stdout.splitlines()
        self.assertEqual(subjects.count("quests: create_ticket t-1"), 1)

    def test_warnings_are_returned(self):
        res = sync.submit(self.ref, {"op": "bogus", "at": T, "session": "s1"})
        self.assertTrue(res.synced)
        self.assertTrue(any("unknown op" in w for w in res.warnings))

    def test_two_clones_concurrent_notes_both_survive(self):
        sync.submit(self.ref, ticket_op("t-1"))
        with self.machine("m1"):
            sync.sync(self.ref)
            offline = self.remote.rename(self.tmp / "away.git")
            r1 = sync.submit(self.ref, note_op("t-1", "first machine note", "s1"))
            self.assertFalse(r1.synced)
            offline.rename(self.remote)
        with self.machine("m2"):
            r2 = sync.submit(self.ref, note_op("t-1", "second machine note", "s2"))
            self.assertTrue(r2.synced)
        with self.machine("m1"):
            self.assertTrue(sync.sync(self.ref).synced)
        tickets, _ = self.remote_tickets()
        texts = [e.text for e in tickets["t-1"].log]
        self.assertIn("first machine note", texts)
        self.assertIn("second machine note", texts)

    def test_two_local_sessions_share_lock(self):
        sync.submit(self.ref, ticket_op("t-0"))
        errors = []

        def worker(n):
            try:
                for i in range(20):
                    r = sync.submit(self.ref, ticket_op(f"t-{n}-{i}", f"s{n}"), timeout=30)
                    if not r.synced:
                        errors.append(r)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in (1, 2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        tickets, _ = self.remote_tickets()
        self.assertEqual(len(tickets), 41)

    def test_offline_keeps_journal_and_shows_pending(self):
        sync.submit(self.ref, ticket_op("t-1"))
        away = self.remote.rename(self.tmp / "away.git")
        res = sync.submit(self.ref, ticket_op("t-2"))
        self.assertFalse(res.synced)
        qlog = store.load_quests(sync.checkout_dir(self.ref))
        self.assertIn("t-2", qlog.tickets)
        journal = self.state / "journal" / "example-com-acme-widgets.jsonl"
        self.assertNotEqual(journal.read_text().strip(), "")
        # a second offline sync does not duplicate or lose anything
        self.assertFalse(sync.sync(self.ref).synced)
        self.assertIn("t-2", store.load_quests(sync.checkout_dir(self.ref)).tickets)
        away.rename(self.remote)
        self.assertTrue(sync.sync(self.ref).synced)
        self.assertEqual(journal.read_text(), "")
        tickets, _ = self.remote_tickets()
        self.assertEqual(set(tickets), {"t-1", "t-2"})

    def push_format(self, n):
        other = self.tmp / "fmt"
        gf.git(self.tmp, "clone", "-q", "--branch", "claude/quests", str(self.remote), str(other))
        store.write_meta(other, {"code_repo": "example/repo", "format": n})
        gf.git(other, "add", "-A")
        gf.git(other, "commit", "-q", "-m", "bump format")
        gf.git(other, "push", "-q", "origin", "HEAD:claude/quests")

    def test_too_new_remote_keeps_pending_op_unapplied(self):
        sync.submit(self.ref, ticket_op("t-1"))
        away = self.remote.rename(self.tmp / "away.git")
        self.assertFalse(sync.submit(self.ref, ticket_op("t-2")).synced)
        away.rename(self.remote)
        self.push_format(store.FORMAT + 1)
        res = sync.sync(self.ref)
        self.assertFalse(res.synced)
        self.assertEqual(res.too_new, store.FORMAT + 1)
        journal = self.state / "journal" / "example-com-acme-widgets.jsonl"
        self.assertIn("t-2", journal.read_text())
        self.assertNotIn("t-2", self.remote_tickets()[0])
        self.assertNotIn("t-2", store.load_quests(sync.checkout_dir(self.ref)).tickets)

    def test_too_new_remote_refuses_submit_and_reads_still_work(self):
        sync.submit(self.ref, ticket_op("t-1"))
        self.push_format(store.FORMAT + 1)
        res = sync.submit(self.ref, ticket_op("t-2"))
        self.assertEqual(res.too_new, store.FORMAT + 1)
        self.assertIn("t-2", (self.state / "journal" / "example-com-acme-widgets.jsonl").read_text())
        read = sync.sync(self.ref)  # nothing new to push for a reader once the journal is parked
        self.assertIn("t-1", store.load_quests(sync.checkout_dir(self.ref)).tickets)
        self.assertEqual(read.too_new, store.FORMAT + 1)

    def test_clone_failure_keeps_journal(self):
        away = self.remote.rename(self.tmp / "away.git")
        res = sync.submit(self.ref, ticket_op("t-1"))
        self.assertFalse(res.synced)
        self.assertEqual(res.warnings, ["quests remote unreachable"])
        journal = self.state / "journal" / "example-com-acme-widgets.jsonl"
        self.assertNotEqual(journal.read_text().strip(), "")
        away.rename(self.remote)
        self.assertTrue(sync.sync(self.ref).synced)
        self.assertIn("t-1", self.remote_tickets()[0])

    def test_push_rejection_retries(self):
        sync.submit(self.ref, ticket_op("t-1"))
        real = sync.run_git
        raced = []

        def racing(args, cwd, timeout=None):
            if args[0] == "push" and not raced:
                raced.append(1)
                other = self.tmp / "other"
                gf.git(self.tmp, "clone", "-q", "--branch", "claude/quests", str(self.remote), str(other))
                ops.apply_op(other, ticket_op("t-other", "s9"))
                gf.git(other, "add", "-A")
                gf.git(other, "commit", "-q", "-m", "quests: create_ticket t-other")
                gf.git(other, "push", "-q", "origin", "HEAD:claude/quests")
            return real(args, cwd, timeout)

        with mock.patch.object(sync, "run_git", racing):
            res = sync.submit(self.ref, ticket_op("t-2"))
        self.assertTrue(res.synced)
        self.assertEqual(raced, [1])
        tickets, _ = self.remote_tickets()
        self.assertEqual(set(tickets), {"t-1", "t-2", "t-other"})

    def test_non_rejection_push_failure_does_not_retry(self):
        real = sync.run_git
        pushes = []

        def failing(args, cwd, timeout=None):
            if args[0] == "push":
                pushes.append(1)
                return subprocess.CompletedProcess(args, 128, "", "fatal: unable to access remote")
            return real(args, cwd, timeout)

        with mock.patch.object(sync, "run_git", failing):
            res = sync.submit(self.ref, ticket_op("t-1"))
        self.assertFalse(res.synced)
        self.assertEqual(len(pushes), 1)

    def test_push_that_lands_then_times_out_is_cleared_on_next_sync(self):
        real = sync.run_git

        def lands_then_times_out(args, cwd, timeout=None):
            p = real(args, cwd, timeout)
            if args[0] == "push":
                raise subprocess.TimeoutExpired(args, timeout)
            return p

        def push_times_out(args, cwd, timeout=None):
            if args[0] == "push":
                raise subprocess.TimeoutExpired(args, timeout)
            return real(args, cwd, timeout)

        with mock.patch.object(sync, "run_git", lands_then_times_out):
            self.assertFalse(sync.submit(self.ref, ticket_op("t-1")).synced)
        self.assertIn("t-1", self.remote_tickets()[0])
        with mock.patch.object(sync, "run_git", push_times_out):
            self.assertTrue(sync.sync(self.ref).synced)
        journal = self.state / "journal" / "example-com-acme-widgets.jsonl"
        self.assertEqual(journal.read_text(), "")

    def test_push_runs_to_its_floor_after_the_deadline_passed(self):
        real = sync.run_git
        budgets = []

        def slow_fetch(args, cwd, timeout=None):
            if args[0] == "fetch":
                p = real(args, cwd, timeout)
                time.sleep(1.2)
                return p
            if args[0] == "push":
                budgets.append(timeout)
            return real(args, cwd, timeout)

        sync.sync(self.ref)  # clone outside the measured run
        with mock.patch.object(sync, "run_git", slow_fetch):
            res = sync.submit(self.ref, ticket_op("t-1"), timeout=1, push_min=3)
        self.assertTrue(res.synced)
        self.assertEqual(budgets, [3])

    def test_commit_identity_fallback_only_without_user_email(self):
        cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        cfg.write_text("[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n")
        sync.submit(self.ref, ticket_op("t-1"))
        _, view = self.remote_tickets()
        self.assertEqual(gf.git(view, "log", "-1", "--format=%ae").stdout.strip(), "quests@users.noreply.invalid")

    def test_user_identity_used_when_configured(self):
        sync.submit(self.ref, ticket_op("t-1"))
        _, view = self.remote_tickets()
        self.assertEqual(gf.git(view, "log", "-1", "--format=%ae").stdout.strip(), "user@example.invalid")

    def test_reused_checkout_is_repointed_at_ref_url(self):
        sync.submit(self.ref, ticket_op("t-1"))
        moved = self.remote.rename(self.tmp / "moved.git")
        self.assertFalse(sync.sync(self.ref).synced)
        new_ref = QuestsRef(self.ref.key, "same", str(moved), self.ref.branch)
        self.assertTrue(sync.submit(new_ref, ticket_op("t-2")).synced)
        url = gf.git(sync.checkout_dir(new_ref), "config", "remote.origin.url").stdout.strip()
        self.assertEqual(url, str(moved))

    def test_hooks_do_not_run_in_checkout(self):
        hooks = self.tmp / "hooks"
        hooks.mkdir()
        marker = self.tmp / "hook-ran"
        for name in ("post-checkout", "pre-commit", "post-commit"):
            (hooks / name).write_text(f"#!/bin/sh\ntouch {marker}\n")
            (hooks / name).chmod(0o755)
        cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        cfg.write_text(cfg.read_text() + f"[core]\n\thooksPath = {hooks}\n")
        self.assertTrue(sync.submit(self.ref, ticket_op("t-1")).synced)
        self.assertFalse(marker.exists())

    def test_lock_wait_outlasts_default_hold(self):
        import inspect

        timeout = inspect.signature(sync.sync).parameters["timeout"].default
        self.assertGreater(sync.LOCK_WAIT, timeout + sync.PUSH_MIN)

    def test_lock_busy_raises(self):
        import fcntl

        path = self.state / "locks" / "example-com-acme-widgets.lock"
        path.parent.mkdir(parents=True)
        with open(path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            with mock.patch.object(sync, "LOCK_WAIT", 0.2):
                with self.assertRaises(sync.QuestsBusy):
                    sync.sync(self.ref)

    def test_deadline_bounds_fetch_and_clone(self):
        # The push is exempt: it runs to its floor (test_push_runs_to_its_floor_after_the_deadline_passed).
        calls = []
        real = sync.run_git

        def slow(args, cwd, timeout=None):
            if args[0] not in ("fetch", "clone"):
                return real(args, cwd, timeout)
            calls.append(timeout)
            raise subprocess.TimeoutExpired(args, timeout)

        sync.submit(self.ref, ticket_op("t-1"))
        with mock.patch.object(sync, "run_git", slow):
            t0 = time.monotonic()
            res = sync.sync(self.ref, timeout=0.5)
        self.assertFalse(res.synced)
        self.assertLess(time.monotonic() - t0, 2)
        self.assertTrue(all(c is None or c <= 0.5 for c in calls))

    def test_git_env_policy(self):
        from quests import gitutil

        env = gitutil.git_env()
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["LC_ALL"], "C")
        self.assertIn("BatchMode=yes", env["GIT_SSH_COMMAND"])
        os.environ["GIT_SSH_COMMAND"] = "ssh -i custom"
        self.assertEqual(gitutil.git_env()["GIT_SSH_COMMAND"], "ssh -i custom")


if __name__ == "__main__":
    unittest.main()
