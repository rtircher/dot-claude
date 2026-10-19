import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from board import hooks, locate
from tests import gitfixture as gf

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "lib" / "board_hooks.py"
BOARD = ROOT / "bin" / "board"


class HooksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        ctx = gf.isolated(self.tmp)
        self.state = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        for k in ("BOARD_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "BOARD_SESSION_LABEL",
                  "BOARD_WHERE", "CLAUDE_CODE_REMOTE", "CLAUDE_ENV_FILE", "CLAUDE_PLUGIN_ROOT"):
            os.environ.pop(k, None)
        self.origin = gf.make_remote(self.tmp, "origin.git", branch=None)
        self.repo = gf.make_code_repo(self.tmp, self.origin)

    def hook(self, event, payload, **env):
        e = dict(os.environ)
        e.update(env)
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, str(ENTRY), event], input=json.dumps(payload),
                           capture_output=True, text=True, env=e, timeout=30)
        self.elapsed = time.monotonic() - t0
        return p

    def init_board(self):
        e = dict(os.environ)
        p = subprocess.run([str(BOARD), "init", "--mode", "same"], cwd=self.repo,
                           capture_output=True, text=True, env=e)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = subprocess.run([str(BOARD), "add", "Set up backups", "--session", "x"], cwd=self.repo,
                           capture_output=True, text=True, env=e)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def heartbeat(self, sid):
        return json.loads((self.state / "sessions" / f"{sid}.json").read_text())

    def test_session_label(self):
        repo = self.repo
        self.assertEqual(hooks.session_label(repo), "main")
        gf.git(repo, "checkout", "-q", "-b", "team/utm-backups-a095ad")
        self.assertEqual(hooks.session_label(repo), "utm-backups")
        gf.git(repo, "checkout", "-q", "--detach")
        self.assertEqual(hooks.session_label(repo), "code")

    def test_session_start_no_repo_prints_one_line_exit_0(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(plain)})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(),
                         'Board: none for this repo (say "set up a board" to create one).')
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        self.assertIsNone(self.heartbeat("s1")["repo_key"])

    def test_session_start_summary_and_heartbeat(self):
        self.init_board()
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(self.repo)})
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines[0].startswith("Board: "), p.stdout)
        self.assertNotIn("unsynced", lines[0])
        self.assertIn("Set up backups", p.stdout)
        self.assertIn("Claim a ticket before starting work; file side quests with `board add --parent`.", p.stdout)
        self.assertIn(f"Board CLI: {BOARD}; session: s1", p.stdout)  # no CLAUDE_ENV_FILE
        self.assertLessEqual(len(lines), 25)
        hb = self.heartbeat("s1")
        self.assertEqual((hb["state"], hb["where"], hb["session"]), ("active", "local", "s1"))
        self.assertEqual(hb["repo_key"], locate.repo_key(self.repo))

    def test_session_start_offline_within_timeout(self):
        self.init_board()
        self.origin.rename(self.tmp / "gone.git")
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(self.repo)})
        self.assertEqual(p.returncode, 0)
        self.assertTrue(p.stdout.startswith("Board: "), p.stdout)
        self.assertIn("(unsynced)", p.stdout.splitlines()[0])
        self.assertIn("Set up backups", p.stdout)
        self.assertLess(self.elapsed, 8)

    def test_session_start_sync_worst_case_fits_hook_timeout(self):
        from unittest import mock

        self.init_board()
        declared = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        limit = declared["hooks"]["SessionStart"][0]["hooks"][0]["timeout"]
        seen = {}

        def capture(ref, timeout=5, lock_wait=None, push_min=hooks.sync.PUSH_MIN):
            seen.update(timeout=timeout, lock_wait=lock_wait, push_min=push_min)
            return hooks.sync.SyncResult(False, [])

        with mock.patch.object(hooks.sync, "sync", capture):
            hooks._summary_text(locate.resolve(self.repo), "s1")
        # fetch may use the whole timeout, then the push gets its floor; the 3 s slack covers
        # python startup, the heartbeat, local git in the checkout and rendering the summary
        self.assertLessEqual(seen["lock_wait"] + seen["timeout"] + seen["push_min"], limit - 3)

    def test_session_start_writes_env_file(self):
        self.init_board()
        envf = self.tmp / "envfile"
        root = self.tmp / "plug root"
        p = self.hook("session-start", {"session_id": "s 1", "cwd": str(self.repo)},
                      CLAUDE_ENV_FILE=str(envf), CLAUDE_PLUGIN_ROOT=str(root))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Board CLI:", p.stdout)
        sh = subprocess.run(["bash", "-c", f'. "{envf}"; echo "$BOARD_SESSION_ID|$BOARD_WHERE|$PATH"'],
                            capture_output=True, text=True).stdout
        sid, wh, path = sh.strip().split("|", 2)
        self.assertEqual((sid, wh), ("s 1", "local"))
        self.assertTrue(path.startswith(f"{root}/bin:"), path)
        self.assertIn("BOARD_SESSION_LABEL", envf.read_text())

    def test_cloud_prints_cli_line_even_with_env_file(self):
        self.init_board()
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(self.repo)},
                      CLAUDE_ENV_FILE=str(self.tmp / "e"), CLAUDE_CODE_REMOTE="true")
        self.assertIn("Board CLI:", p.stdout)
        self.assertEqual(self.heartbeat("s1")["where"], "cloud")

    def test_prompt_emits_additional_context_json(self):
        p = self.hook("prompt", {"session_id": "s1", "cwd": str(self.repo),
                                 "prompt": "park it for now"})
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertTrue(out["additionalContext"].startswith("Board cue: the user is parking something."))
        p = self.hook("prompt", {"session_id": "s1", "cwd": str(self.repo), "prompt": "btw how?"})
        self.assertIn("answer the btw first", json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"])
        p = self.hook("prompt", {"session_id": "s1", "cwd": str(self.repo), "prompt": "hello"})
        self.assertEqual(p.stdout, "")
        self.assertEqual(self.heartbeat("s1")["state"], "active")

    def test_hook_swallows_exceptions(self):
        self.init_board()
        bad = self.tmp / "bad"
        gf.git(self.tmp, "clone", "-q", "--branch", gf.BRANCH, str(self.origin), str(bad))
        (bad / "board.json").write_text("{not json", encoding="utf-8")
        gf.git(bad, "commit", "-qam", "corrupt")
        gf.git(bad, "push", "-q", "origin", gf.BRANCH)
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(self.repo)})
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        self.assertTrue((self.state / "hook-errors.log").exists())
        self.assertEqual(p.stdout.splitlines()[0].split(" (")[1], "unreadable; see hook-errors.log)")
        self.assertTrue(p.stdout.startswith("Board: "))

    def test_write_failures_do_not_hide_summary(self):
        self.init_board()
        (self.state / "sessions").write_text("file, not dir")
        bad_env = self.tmp / "envdir"
        bad_env.mkdir()
        p = self.hook("session-start", {"session_id": "s1", "cwd": str(self.repo)},
                      CLAUDE_ENV_FILE=str(bad_env))
        self.assertEqual(p.returncode, 0)
        self.assertIn("Set up backups", p.stdout)
        self.assertIn("Board CLI:", p.stdout)
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        self.assertTrue((self.state / "hook-errors.log").exists())

    def test_empty_session_id_skips_env_exports(self):
        self.init_board()
        envf = self.tmp / "envfile"
        self.hook("session-start", {"cwd": str(self.repo)}, CLAUDE_ENV_FILE=str(envf))
        self.assertFalse(envf.exists())

    def test_import_failure_exits_0(self):
        shim = self.tmp / "shim"
        (shim / "lib" / "board").mkdir(parents=True)
        (shim / "lib" / "board" / "__init__.py").write_text("")
        (shim / "lib" / "board" / "hooks.py").write_text("raise ImportError('boom')\n")
        (shim / "lib" / "board_hooks.py").write_text(ENTRY.read_text())
        p = subprocess.run([sys.executable, str(shim / "lib" / "board_hooks.py"), "prompt"],
                           input="{}", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        self.assertIn("boom", (self.state / "hook-errors.log").read_text())

    def test_garbage_stdin_exit_0(self):
        p = subprocess.run([sys.executable, str(ENTRY), "prompt"], input="nope",
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)

    def test_stop_and_end_update_heartbeat_state(self):
        payload = {"session_id": "s1", "cwd": str(self.repo)}
        self.hook("prompt", dict(payload, prompt="x"))
        self.assertEqual(self.heartbeat("s1")["state"], "active")
        self.assertEqual(self.hook("stop", payload).returncode, 0)
        self.assertEqual(self.heartbeat("s1")["state"], "waiting")
        self.assertEqual(self.hook("end", payload).returncode, 0)
        self.assertEqual(self.heartbeat("s1")["state"], "ended")


class SkillTest(unittest.TestCase):
    def test_skill_frontmatter(self):
        path = ROOT / "skills" / "tickets" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("\n---\n", 1)[0].splitlines()[1:]
        fields = dict(line.split(": ", 1) for line in front if ": " in line)
        self.assertEqual(fields.get("name"), "tickets")
        self.assertTrue(fields.get("description", "").strip())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for body in (text, readme):
            self.assertNotIn("\u2014", body)
            self.assertNotIn("\u2013", body)
            self.assertNotIn("/Users/", body)


if __name__ == "__main__":
    unittest.main()
