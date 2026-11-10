"""Unit tests for the delegation gate.

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


class BulkRead(unittest.TestCase):
    def test_read(self):
        self.assertTrue(gate.is_bulk_read("Read", {"file_path": "x"}))
        self.assertTrue(gate.is_bulk_read("Read", {"file_path": "x", "limit": 500}))
        self.assertFalse(gate.is_bulk_read("Read", {"file_path": "x", "offset": 10, "limit": 100}))

    def test_grep(self):
        self.assertTrue(gate.is_bulk_read("Grep", {"pattern": "x", "output_mode": "content"}))
        self.assertFalse(gate.is_bulk_read("Grep", {"pattern": "x", "output_mode": "content", "head_limit": 20}))
        self.assertFalse(gate.is_bulk_read("Grep", {"pattern": "x"}))

    def test_bash_and_glob_are_never_bulk(self):
        # Bash output is truncated by the harness; a shape test only caught narrow lookups.
        for cmd in ("cat f", "git diff", "grep -rn foo .", "jj log -r '@'", None):
            with self.subTest(cmd=cmd):
                self.assertFalse(gate.is_bulk_read("Bash", {"command": cmd}))
        self.assertFalse(gate.is_bulk_read("Glob", {"pattern": "**/*.py"}))


class DeepMainLoop(unittest.TestCase):
    """Parent transcript deep past the arm band, with 3 prior bulk round-trips."""

    def setUp(self):
        usage = {"input_tokens": 10, "cache_read_input_tokens": 228_000,
                 "cache_creation_input_tokens": 0}
        lines = [{"type": "user", "message": {"content": "look around"}}]
        for i in range(4):
            lines.append({"type": "assistant", "message": {
                "model": "claude-sonnet-5", "usage": usage,
                "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read",
                             "input": {"file_path": "f"}}]}})
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x"}]}})
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(json.dumps(l) for l in lines) + "\n")

    def tearDown(self):
        os.unlink(self.path)

    def run_gate(self, tool_name="Read", tool_input=None, window="250000", **extra):
        payload = {"tool_name": tool_name, "tool_input": tool_input or {"file_path": "f"},
                   "transcript_path": self.path, **extra}
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DELEGATION_GATE", "CONTEXT_WATCH"))}
        env["CONTEXT_WATCH_WINDOW"] = window
        return subprocess.run([sys.executable, SCRIPT], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, check=True).stdout

    def test_main_loop_is_denied(self):
        self.assertIn('"deny"', self.run_gate())

    def test_arms_at_first_configured_band(self):
        with open(os.path.join(HERE, "..", "context-budget.json")) as f:
            first_band = min(json.load(f)["bands"])
        just_below = str(228_010 * 100 // (first_band - 1))  # (first_band - 2)% context
        self.assertEqual(self.run_gate(window=just_below), "")

    def test_subagent_is_exempt(self):
        self.assertEqual(self.run_gate(agent_id="a919ff86", agent_type="dev:coder"), "")

    def test_bash_is_never_denied(self):
        self.assertEqual(self.run_gate("Bash", {"command": "cat f"}), "")


if __name__ == "__main__":
    unittest.main()
