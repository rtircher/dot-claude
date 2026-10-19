import json
import tempfile
import unittest
from pathlib import Path

from board import locate
from board.locate import BoardRef
from tests import gitfixture as gf


class LocateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        ctx = gf.isolated(self.tmp)
        self.state = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def test_repo_key_normalizes_ssh_and_https(self):
        a = gf.make_code_repo(self.tmp, "git@example.com:acme/widgets.git", "a")
        b = gf.make_code_repo(self.tmp, "https://user@example.com/acme/widgets.git", "b")
        c = gf.make_code_repo(self.tmp, "ssh://git@example.com/acme/widgets/", "c")
        self.assertEqual(locate.repo_key(a), "example.com/acme/widgets")
        self.assertEqual(locate.repo_key(b), "example.com/acme/widgets")
        self.assertEqual(locate.repo_key(c), "example.com/acme/widgets")

    def test_repo_key_without_origin_is_local_hash(self):
        r = gf.make_code_repo(self.tmp, None)
        key = locate.repo_key(r)
        self.assertRegex(key, r"^local-[0-9a-f]{10}$")
        self.assertEqual(key, locate.repo_key(r))

    def test_repo_key_none_outside_git(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertIsNone(locate.repo_key(plain))
        self.assertIsNone(locate.resolve(plain))

    def test_negative_resolve_is_cached_and_cleared(self):
        from unittest import mock
        code = gf.make_code_repo(self.tmp, gf.make_remote(self.tmp, branch=None))
        self.assertIsNone(locate.resolve(code))
        with mock.patch.object(locate, "run_git") as rg:
            self.assertIsNone(locate.resolve(code))
            self.assertTrue(all(c.args[0][0] != "ls-remote" for c in rg.call_args_list))
        locate.clear_negative(locate.repo_key(code))
        with mock.patch.object(locate, "_remote_has_branch", return_value=False) as probe:
            self.assertIsNone(locate.resolve(code))
            self.assertTrue(probe.called)

    def test_slug(self):
        self.assertEqual(locate.slug("Example.com/Acme/widgets"), "example-com-acme-widgets")

    def test_state_dir_default_and_env(self):
        self.assertEqual(locate.state_dir(), self.state)

    def test_resolve_order_config_then_env_then_same(self):
        remote = gf.make_remote(self.tmp)
        code = gf.make_code_repo(self.tmp, remote)
        key = locate.repo_key(code)
        ext = gf.make_remote(self.tmp, "ext.git", branch=f"board/{locate.slug(key)}")
        import os

        # same-repo board exists on origin
        ref = locate.resolve(code)
        self.assertEqual((ref.mode, ref.branch, ref.url), ("same", "claude/board", str(remote)))
        # env beats same (discovery persists, so clear the saved entry between steps)
        (self.state / "config.json").unlink()
        os.environ["CLAUDE_BOARD_REPO"] = str(ext)
        ref = locate.resolve(code)
        self.assertEqual((ref.mode, ref.url, ref.branch), ("external", str(ext), f"board/{locate.slug(key)}"))
        # config beats env
        os.environ["CLAUDE_BOARD_REPO"] = str(ext)
        saved = BoardRef(key, "external", "/somewhere/else.git", "board/custom")
        locate.save_config(saved)
        self.assertEqual(locate.resolve(code), saved)
        cfg = json.loads((self.state / "config.json").read_text())
        self.assertIn(key, cfg)

    def test_env_without_branch_on_remote_falls_through_to_same(self):
        import os

        remote = gf.make_remote(self.tmp)
        code = gf.make_code_repo(self.tmp, remote)
        empty = gf.make_remote(self.tmp, "empty.git", branch=None)
        os.environ["CLAUDE_BOARD_REPO"] = str(empty)
        self.assertEqual(locate.resolve(code).mode, "same")

    def test_env_without_branch_and_no_same_board_is_none(self):
        import os

        code = gf.make_code_repo(self.tmp, gf.make_remote(self.tmp, branch=None))
        os.environ["CLAUDE_BOARD_REPO"] = str(gf.make_remote(self.tmp, "empty.git", branch=None))
        self.assertIsNone(locate.resolve(code))

    def test_resolve_persists_and_works_offline(self):
        remote = gf.make_remote(self.tmp)
        code = gf.make_code_repo(self.tmp, remote)
        first = locate.resolve(code)
        remote.rename(self.tmp / "gone.git")
        self.assertEqual(locate.resolve(code), first)

    def test_repo_key_lowercases_host_only(self):
        r = gf.make_code_repo(self.tmp, "https://GitHub.com/Acme/Widgets.git")
        self.assertEqual(locate.repo_key(r), "github.com/Acme/Widgets")

    def test_same_mode_local_branch_without_origin(self):
        code = gf.make_code_repo(self.tmp, None)
        self.assertIsNone(locate.resolve(code))
        gf.git(code, "branch", "claude/board")
        ref = locate.resolve(code)
        self.assertEqual(ref.mode, "same")
        self.assertEqual(Path(ref.url), (code / ".git").resolve())

    def test_same_mode_uses_cached_remote_ref_before_network(self):
        remote = gf.make_remote(self.tmp)
        code = gf.make_code_repo(self.tmp, remote)
        gf.git(code, "fetch", "-q", "origin")
        remote.rename(self.tmp / "gone.git")  # unreachable now
        self.assertEqual(locate.resolve(code).mode, "same")

    def test_no_board_returns_none(self):
        remote = gf.make_remote(self.tmp, branch=None)
        code = gf.make_code_repo(self.tmp, remote)
        self.assertIsNone(locate.resolve(code))


if __name__ == "__main__":
    unittest.main()
