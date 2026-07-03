#!/usr/bin/env python3
"""PreToolUse hook on Bash: deny `git commit` in a repo that opted into the
green-tests gate until the current worktree fingerprint matches the one
recorded by record-green.sh at the last successful test run.

Opt-in: a `.claude/require-green-tests` file at the repo root whose content is
the repo's canonical full-suite command (it is echoed in the deny message).
Repos without that file are untouched.

The gate is deterministic where skill/instruction compliance is not: the deny
fires on the tool call itself, so a commit on an unverified tree cannot slip
through however the conversation went. Fail-open on infrastructure errors
(missing git, unreadable state) so a broken hook never wedges commits.

The fingerprint is the tree hash of the full worktree (tracked + untracked,
gitignore respected) computed through a throwaway index, so `git add` and other
staging-only changes do not invalidate a green run; editing any file does.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile

STATE_DIR = os.path.expanduser("~/.claude/state/green-tests")
OPTIN_RELPATH = os.path.join(".claude", "require-green-tests")

# git global options that consume a following argument.
GIT_OPTS_WITH_ARG = {"-C", "-c", "--exec-path", "--git-dir", "--work-tree", "--namespace"}


def parse_git_commit(command: str) -> tuple[bool, str | None]:
    """Whether the command runs `git commit`, and any `git -C <dir>` it targets.

    Token-scans instead of regexing the raw string so a commit anywhere in a
    `&&` chain is caught while `-m "git commit fix"` (one token) is not.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unparseable quoting: fall back to a coarse substring check.
        return ("git commit" in command, None)
    i = 0
    while i < len(tokens):
        if tokens[i] == "git":
            c_dir = None
            j = i + 1
            while j < len(tokens):
                tok = tokens[j]
                if tok in GIT_OPTS_WITH_ARG:
                    if tok == "-C" and j + 1 < len(tokens):
                        c_dir = tokens[j + 1]
                    j += 2
                    continue
                if tok.startswith("-C") and len(tok) > 2:
                    c_dir = tok[2:]
                    j += 1
                    continue
                if tok.startswith("-"):
                    j += 1
                    continue
                if tok == "commit":
                    return (True, c_dir)
                break  # some other git subcommand
        i += 1
    return (False, None)


def repo_root(path: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def worktree_fingerprint(repo: str) -> str | None:
    fd, tmp_index = tempfile.mkstemp(prefix="green-tests-index-")
    os.close(fd)
    os.unlink(tmp_index)  # git must create the index itself
    env = {**os.environ, "GIT_INDEX_FILE": tmp_index}
    try:
        add = subprocess.run(["git", "-C", repo, "add", "-A"], env=env,
                             capture_output=True, timeout=120)
        if add.returncode != 0:
            return None
        tree = subprocess.run(["git", "-C", repo, "write-tree"], env=env,
                              capture_output=True, text=True, timeout=60)
        return tree.stdout.strip() if tree.returncode == 0 else None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp_index)
        except OSError:
            pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return 0
    command = ti.get("command") or ""

    is_commit, c_dir = parse_git_commit(command)
    if not is_commit:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    target = os.path.join(cwd, c_dir) if c_dir and not os.path.isabs(c_dir) else (c_dir or cwd)
    repo = repo_root(target)
    if not repo:
        return 0

    optin_path = os.path.join(repo, OPTIN_RELPATH)
    if not os.path.isfile(optin_path):
        return 0  # repo has not opted in

    try:
        test_command = open(optin_path, encoding="utf-8").read().strip() or "the repo's test suite"
    except OSError:
        test_command = "the repo's test suite"

    current = worktree_fingerprint(repo)
    if current is None:
        return 0  # fail open: never wedge commits on hook infrastructure errors

    key = hashlib.sha256(repo.encode()).hexdigest()
    recorded = None
    try:
        with open(os.path.join(STATE_DIR, key), encoding="utf-8") as f:
            recorded = f.read().strip()
    except OSError:
        pass

    if recorded == current:
        return 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "<conventions plugin root>")
    reason = (
        "This repo requires a green test run on the exact tree being committed "
        "(.claude/require-green-tests), and none is recorded for the current "
        "worktree. Run the suite through the recording wrapper, then retry the "
        f"commit:\n\n  {plugin_root}/scripts/record-green.sh {test_command}\n\n"
        "Run it from the repo root. If tests fail, fix them first; do not "
        "bypass the gate by committing elsewhere."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
