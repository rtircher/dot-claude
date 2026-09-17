"""Unit tests for the delegation-gate Bash detector.

Run: python3 -m unittest discover -s plugins/conventions/tests
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "delegation-gate.py")
spec = importlib.util.spec_from_file_location("delegation_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

# Real offenders lifted from a transcript audit (each landed 10k+ chars in
# main context) plus the plain forms they reduce to.
BULK = [
    "cat foo.py",
    "cd /home/me/repo && git diff 9a5d5d4e00 e0459e131d -- atlas/src/atlas/grpc_services/token.py",
    "S=/tmp/scratch; cat $S/findings.md",
    "echo '--- state ---'; cat ~/.claude/state/agents-channel/state.json",
    "jj log -r 'divergent()' --no-graph -T 'change_id.short() ++ \" \" ++ description.first_line() ++ \"\\n\"'",
    'for n in 9385 9386; do echo "=== PR $n ==="; gh pr view $n; done',
    "git show 3025603f9f",
    "git diff --stat a b && git diff a b -- dataform/scripts/import_usage_csv.py",
    "grep -rn -i -B2 -A4 'refresh.rpc' ~/.claude/state/handover-archive/",
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


if __name__ == "__main__":
    unittest.main()
