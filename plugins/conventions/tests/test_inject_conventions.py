"""Tests for inject-conventions.sh region filtering.

Run: python3 -m unittest discover -s plugins/conventions/tests
"""
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(PLUGIN, "scripts", "inject-conventions.sh")

GIT_BULLET = "Never push or commit to the default branch"
MAIN_ONLY_BULLET = "Fixed routing by role"


def run(*args, skip_git=None):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN}
    env.pop("DOT_CLAUDE_CONVENTIONS_SKIP_GIT", None)
    if skip_git is not None:
        env["DOT_CLAUDE_CONVENTIONS_SKIP_GIT"] = skip_git
    out = subprocess.run([SCRIPT, *args], env=env, capture_output=True, text=True, check=True).stdout
    if args == ("--subagent",):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]
    return out


class InjectConventionsTest(unittest.TestCase):
    def test_default_injects_git_block_and_no_markers(self):
        for text in (run(), run("--subagent")):
            self.assertIn(GIT_BULLET, text)
            self.assertNotIn("<!--", text)

    def test_skip_git_drops_only_the_git_block(self):
        for text in (run(skip_git="1"), run("--subagent", skip_git="1")):
            self.assertNotIn(GIT_BULLET, text)
            self.assertNotIn("Meaningful branch and worktree names", text)
            self.assertNotIn("<!--", text)
            self.assertIn("Simplicity first", text)

    def test_skip_git_requires_exactly_one(self):
        self.assertIn(GIT_BULLET, run(skip_git="0"))
        self.assertIn(GIT_BULLET, run(skip_git=""))

    def test_main_session_region_stays_main_only(self):
        self.assertIn(MAIN_ONLY_BULLET, run())
        self.assertNotIn(MAIN_ONLY_BULLET, run("--subagent"))


if __name__ == "__main__":
    unittest.main()
