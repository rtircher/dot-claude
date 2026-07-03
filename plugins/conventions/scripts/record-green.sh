#!/usr/bin/env bash
# Run a test command and, on success, record the worktree fingerprint that
# require-green-tests.py checks before allowing `git commit` in opted-in repos.
#
# Usage: record-green.sh <test command...>   (run from anywhere inside the repo)
#
# The fingerprint is the tree hash of the full worktree (tracked + untracked,
# gitignore respected), computed through a throwaway index so the real index
# and staging state are never touched and never affect the hash.
set -u

repo=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "record-green: not inside a git repository" >&2
  exit 64
}

if [ $# -eq 0 ]; then
  echo "record-green: usage: record-green.sh <test command...>" >&2
  exit 64
fi

"$@"
status=$?
if [ "$status" -ne 0 ]; then
  echo "record-green: test command failed (exit $status); fingerprint not recorded" >&2
  exit "$status"
fi

state_dir="${HOME}/.claude/state/green-tests"
mkdir -p "$state_dir"

tmp_index=$(mktemp)
trap 'rm -f "$tmp_index"' EXIT
rm -f "$tmp_index" # git must create the index itself; an empty file is not a valid index

GIT_INDEX_FILE="$tmp_index" git -C "$repo" add -A || exit 70
tree=$(GIT_INDEX_FILE="$tmp_index" git -C "$repo" write-tree) || exit 70

key=$(printf '%s' "$repo" | shasum -a 256 | cut -d' ' -f1)
printf '%s\n' "$tree" >"$state_dir/$key"
echo "record-green: tests green, fingerprint $tree recorded for $repo"
