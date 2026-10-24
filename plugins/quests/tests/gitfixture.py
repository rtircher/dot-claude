"""Hermetic git helpers: temp dirs, bare local remotes, isolated identity and state."""
from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

BRANCH = "claude/quests"


def git(cwd, *args, check=True):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr}")
    return p


@contextlib.contextmanager
def isolated(tmp: Path, state_name: str = "state"):
    """Set QUESTS_STATE_DIR and a git identity that never touches the real HOME config."""
    tmp = Path(tmp)
    cfg = tmp / "gitconfig"
    if not cfg.exists():
        cfg.write_text(
            "[user]\n\tname = Example User\n\temail = user@example.invalid\n"
            "[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n",
            encoding="utf-8",
        )
    state = tmp / state_name
    saved = dict(os.environ)
    os.environ["QUESTS_STATE_DIR"] = str(state)
    os.environ["GIT_CONFIG_GLOBAL"] = str(cfg)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["HOME"] = str(tmp / "home")
    for k in ("CLAUDE_QUESTS_REPO", "CLAUDE_BOARD_REPO", "BOARD_STATE_DIR", "GIT_SSH_COMMAND"):
        os.environ.pop(k, None)
    try:
        yield state
    finally:
        os.environ.clear()
        os.environ.update(saved)


def make_remote(tmp: Path, name: str = "remote.git", branch: str | None = BRANCH) -> Path:
    """Bare repo; with a branch, seeded with an orphan commit holding board.json."""
    tmp = Path(tmp)
    remote = tmp / name
    git(tmp, "init", "--bare", "-q", str(remote))
    if branch:
        seed = tmp / (name + ".seed")
        git(tmp, "init", "-q", str(seed))
        git(seed, "checkout", "-q", "--orphan", branch)
        (seed / "board.json").write_text('{"code_repo": "example/repo"}\n', encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "quests: init")
        git(seed, "push", "-q", str(remote), f"{branch}:refs/heads/{branch}")
    return remote


def make_code_repo(tmp: Path, origin: Path | str | None, name: str = "code") -> Path:
    tmp = Path(tmp)
    repo = tmp / name
    git(tmp, "init", "-q", str(repo))
    (repo / "README.md").write_text("Example project\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    if origin is not None:
        git(repo, "remote", "add", "origin", str(origin))
    return repo


def temp_dir():
    return tempfile.TemporaryDirectory()
