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

# Claude Code (2.1.327, constant `threshold` in its hook-output persister) keeps
# at most 10,000 characters of one hook's output in context; past that, the model
# sees a 2KB preview and a file path. Each injection must stay under it, with
# headroom for edits.
HOOK_OUTPUT_CAP = 10_000
HEADROOM = 1_000

GIT_BULLET = "Never push or commit to the default branch"
MAIN_ONLY_BULLET = "Fixed routing by role"
# Git-only rules that the opt-out drops.
GATED_RULES = (GIT_BULLET, "Git history hygiene", "Meaningful branch and worktree names")
# Rules that sit beside the git rules but are not git workflow; the opt-out must keep them.
UNGATED_RULES = (
    "Commits are authored as the human",
    "Claude <noreply@anthropic.com>",
    "Never add an AI",
    "Never cite commit short-hashes",
    "verify merge status",
    "never remove the worktree the session runs inside",
)


def run(*args, skip_git=None):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN}
    env.pop("DOT_CLAUDE_CONVENTIONS_SKIP_GIT", None)
    if skip_git is not None:
        env["DOT_CLAUDE_CONVENTIONS_SKIP_GIT"] = skip_git
    out = subprocess.run([SCRIPT, *args], env=env, capture_output=True, text=True, check=True).stdout
    if "--subagent" in args:
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]
    return out


class InjectConventionsTest(unittest.TestCase):
    def test_default_injects_git_block_and_no_markers(self):
        for text in (run(), run("--subagent")):
            self.assertIn(GIT_BULLET, text)
            self.assertNotIn("<!--", text)

    def test_skip_git_drops_only_the_git_block(self):
        for text in (run(skip_git="1"), run("--subagent", skip_git="1")):
            for rule in GATED_RULES:
                self.assertNotIn(rule, text)
            self.assertNotIn("<!--", text)
            self.assertIn("Simplicity first", text)

    def test_skip_git_keeps_the_non_git_rules(self):
        for text in (run(skip_git="1"), run("--subagent", skip_git="1")):
            for rule in UNGATED_RULES:
                self.assertIn(rule, text)

    def test_default_injects_the_non_git_rules(self):
        for text in (run(), run("--subagent")):
            for rule in UNGATED_RULES:
                self.assertIn(rule, text)

    def test_skip_git_requires_exactly_one(self):
        self.assertIn(GIT_BULLET, run(skip_git="0"))
        self.assertIn(GIT_BULLET, run(skip_git=""))

    def test_main_session_region_is_its_own_injection(self):
        self.assertIn(MAIN_ONLY_BULLET, run("--orchestration"))
        self.assertNotIn(MAIN_ONLY_BULLET, run())
        self.assertNotIn(MAIN_ONLY_BULLET, run("--subagent"))
        self.assertNotIn("<!--", run("--orchestration"))

    def test_every_injection_fits_under_the_hook_output_cap(self):
        for args in ((), ("--orchestration",), ("--subagent",)):
            for skip_git in (None, "1"):
                size = len(run(*args, skip_git=skip_git))
                self.assertLess(size, HOOK_OUTPUT_CAP - HEADROOM, f"{args} skip_git={skip_git}: {size} chars")

    def test_main_session_parts_together_carry_every_line(self):
        with open(os.path.join(PLUGIN, "conventions.md")) as f:
            source = [l for l in f.read().splitlines() if l.strip() and not l.startswith("<!--")]
        injected = set((run() + run("--orchestration")).splitlines())
        self.assertEqual([l for l in source if l not in injected], [])

    def test_session_start_runs_both_main_session_parts(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]["SessionStart"]
        commands = [h["command"] for entry in hooks for h in entry["hooks"]]
        self.assertTrue(any(c.endswith("inject-conventions.sh") for c in commands), commands)
        self.assertTrue(any(c.endswith("inject-conventions.sh --orchestration") for c in commands), commands)


if __name__ == "__main__":
    unittest.main()
