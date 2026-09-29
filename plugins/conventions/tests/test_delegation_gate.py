"""Unit tests for the delegation-gate Bash detector.

Run: python3 -m unittest discover -s plugins/conventions/tests
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "delegation-gate.py")
spec = importlib.util.spec_from_file_location("delegation_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

# Bulk-read shapes that land 10k+ chars in main context, plus the plain forms
# they reduce to.
BULK = [
    "cat foo.py",
    "cd /home/me/repo && git diff 9a5d5d4e00 e0459e131d -- src/app/auth/token.py",
    "S=/tmp/scratch; cat $S/findings.md",
    "echo '--- state ---'; cat ~/.cache/app/state.json",
    "jj log -r 'divergent()' --no-graph -T 'change_id.short() ++ \" \" ++ description.first_line() ++ \"\\n\"'",
    'for n in 101 102; do echo "=== PR $n ==="; gh pr view $n; done',
    "git show 3025603f9f",
    "git diff --stat a b && git diff a b -- scripts/import_data.py",
    "grep -rn -i -B2 -A4 'refresh_token' ~/notes/archive/",
    "rg foo src/",
    "cat f | sort | uniq",
    "sed -n '1,400p' f",
    "find . -name '*.py'",
    "git log",
    "git diff",
    "cat -n file.py",
    "grep -n foo f",
    "cat f 2>/dev/null | grep -v '^#'",
]

NOT_BULK = [
    "git diff --stat",
    "git diff --name-only a b",
    "git log --oneline -n 20",
    "git log -5",
    "git show -s --format=%h abc",
    "jj log",
    "jj log -n 10",
    "jj log -r 'trunk()..@' -n 20",
    "jj log -r x --stat",
    "jj rebase -s a -d b",
    "git status",
    "cat f | head -50",
    "cat f 2>&1 | tail -20",
    "git diff a b | wc -l",
    "grep -c foo f",
    "grep -l foo -r src",
    "grep -rl foo src",
    "grep -q foo f && echo yes",
    "rg -l foo",
    "rg --files-with-matches foo",
    "gh pr view 1 --json title -q .title",
    "gh pr create --base dev --title x",
    "sed -i 's/a/b/' f",
    "sed -n '10,60p' f",
    "sed -n 42p f",
    "cat > f <<'EOF'\ncat everything\nEOF",
    "python3 - <<'EOF'\ncat = open('x').read()\nEOF",
    "cat f | python3 x.py",
    "cat a b > merged.txt",
    "find . -name x -delete",
    "find . -name '*.pyc' -exec rm {} +",
    "find . -name '*.py' | wc -l",
    "ls -la",
    "wc -l f",
    "head -50 f",
    "tail -20 f",
    "echo hi",
    "cd /repo && npm test",
    "grep 'a;b' f | head -5",
    "",
]


class BashDetector(unittest.TestCase):
    def test_bulk(self):
        for cmd in BULK:
            with self.subTest(cmd=cmd):
                self.assertTrue(gate.bash_is_bulk_read(cmd))

    def test_not_bulk(self):
        for cmd in NOT_BULK:
            with self.subTest(cmd=cmd):
                self.assertFalse(gate.bash_is_bulk_read(cmd))

    def test_unparseable_input_fails_open(self):
        self.assertFalse(gate.bash_is_bulk_read(None))
        self.assertFalse(gate.bash_is_bulk_read(42))

    def test_unterminated_quote_still_judged(self):
        # shlex gives up; the whitespace fallback still sees `cat <file>`.
        self.assertTrue(gate.bash_is_bulk_read("cat 'unterminated"))


class OtherTools(unittest.TestCase):
    def test_read(self):
        self.assertTrue(gate.is_bulk_read("Read", {"file_path": "x"}))
        self.assertTrue(gate.is_bulk_read("Read", {"file_path": "x", "limit": 500}))
        self.assertFalse(gate.is_bulk_read("Read", {"file_path": "x", "offset": 10, "limit": 100}))

    def test_grep(self):
        self.assertTrue(gate.is_bulk_read("Grep", {"pattern": "x", "output_mode": "content"}))
        self.assertFalse(gate.is_bulk_read("Grep", {"pattern": "x", "output_mode": "content", "head_limit": 20}))
        self.assertFalse(gate.is_bulk_read("Grep", {"pattern": "x"}))

    def test_bash_dispatch(self):
        self.assertTrue(gate.is_bulk_read("Bash", {"command": "cat f"}))
        self.assertFalse(gate.is_bulk_read("Glob", {"pattern": "**/*.py"}))


class SubagentExemption(unittest.TestCase):
    """Parent transcript deep past the arm band, with 3 prior bulk round-trips."""

    def setUp(self):
        usage = {"input_tokens": 10, "cache_read_input_tokens": 228_000,
                 "cache_creation_input_tokens": 0}
        lines = [{"type": "user", "message": {"content": "look around"}}]
        for i in range(4):
            lines.append({"type": "assistant", "message": {
                "model": "claude-sonnet-5", "usage": usage,
                "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash",
                             "input": {"command": "cat f"}}]}})
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x"}]}})
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(json.dumps(l) for l in lines) + "\n")

    def tearDown(self):
        os.unlink(self.path)

    def run_gate(self, **extra):
        payload = {"tool_name": "Bash", "tool_input": {"command": "cat f"},
                   "transcript_path": self.path, **extra}
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DELEGATION_GATE", "CONTEXT_WATCH"))}
        env["CONTEXT_WATCH_WINDOW"] = "250000"
        return subprocess.run([sys.executable, SCRIPT], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, check=True).stdout

    def test_main_loop_is_denied(self):
        self.assertIn('"deny"', self.run_gate())

    def test_subagent_is_exempt(self):
        self.assertEqual(self.run_gate(agent_id="a919ff86", agent_type="dev:coder"), "")


if __name__ == "__main__":
    unittest.main()
