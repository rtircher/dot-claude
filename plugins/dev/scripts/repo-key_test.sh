#!/usr/bin/env bash
# Handover key resolution across a plain repo, a git worktree, a jj workspace
# (no .git, only a .jj/repo pointer) and no repo, plus the two scripts that
# consume it. The jj layout is built by hand, so jj need not be installed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../scaffold/tests/lib.sh
. "$here/../scaffold/tests/lib.sh"

work="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com
export HOME="$work/home"
mkdir -p "$HOME"

key_in() { (cd "$1" && bash "$here/repo-key.sh"); }

# Colocated main checkout: .git and a .jj/repo directory side by side.
main="$work/proj"
git init -q -b main "$main"
git -C "$main" commit -q --allow-empty -m initial
git -C "$main" remote add origin git@github.com:acme/proj.git
git -C "$main" branch feat/done
mkdir -p "$main/.jj/repo" "$main/sub/dir"

expected=$(printf 'KEY\tproj\nROOT\t%s' "$main")
assert_eq "$(key_in "$main")" "$expected" "main checkout"
assert_eq "$(key_in "$main/sub/dir")" "$expected" "subdirectory of the main checkout"

git -C "$main" worktree add -q "$work/wt" -b wt-branch
assert_eq "$(key_in "$work/wt")" "$expected" "git worktree keys to its main repo"

git -C "$main" worktree add -q "$main/.claude/worktrees/nested" -b nested
assert_eq "$(key_in "$main/.claude/worktrees/nested")" "$expected" \
  "git worktree inside the jj checkout resolves through git"

# Secondary jj workspace: the pointer is relative to the workspace's .jj/.
ws="$work/workspaces/proj-1234/feature"
mkdir -p "$ws/.jj" "$ws/pkg"
printf '%s' "../../../../proj/.jj/repo" > "$ws/.jj/repo"
assert_eq "$(key_in "$ws")" "$expected" "jj workspace follows a relative pointer"
assert_eq "$(key_in "$ws/pkg")" "$expected" "subdirectory of a jj workspace"

abs="$work/workspaces/proj-1234/abs"
mkdir -p "$abs/.jj"
printf '%s\n' "$main/.jj/repo" > "$abs/.jj/repo"
assert_eq "$(key_in "$abs")" "$expected" "jj workspace follows an absolute pointer"

dangling="$work/workspaces/proj-1234/dangling"
mkdir -p "$dangling/.jj"
printf '%s' "$work/gone/.jj/repo" > "$dangling/.jj/repo"
assert_eq "$(key_in "$dangling")" "$(printf 'KEY\tdefault\nROOT\t')" "dangling pointer falls back to default"

plain_jj="$work/jjonly"
mkdir -p "$plain_jj/.jj/repo"
assert_eq "$(key_in "$plain_jj")" "$(printf 'KEY\tjjonly\nROOT\t%s' "$plain_jj")" \
  "non-colocated jj checkout"

mkdir -p "$work/norepo"
assert_eq "$(key_in "$work/norepo")" "$(printf 'KEY\tdefault\nROOT\t')" "outside a repo"

# Consumers run from the jj workspace, where git alone finds nothing.
state="$HOME/.claude/state/handover"
mkdir -p "$state"
printf 'Repo: %s\nBranch: main\n' "$main" > "$state/proj.md"
out=$(cd "$ws" && bash "$here/find-handover.sh" --no-fetch)
assert_contains "$out" "ORIGIN	acme/proj" "find-handover reads origin through the main root"
assert_contains "$out" "LOCAL	$state/proj.md" "find-handover finds the repo's handover"

printf 'Repo: %s\nBranch: feat/done\n' "$main" > "$state/proj-done-20260101T000000Z.md"
printf 'Repo: %s\nBranch: feat/pending\n' "$main" > "$state/proj-pending-20260101T000000Z.md"
out=$(cd "$ws" && bash "$here/handover-archive-sweep.sh" --dry-run)
assert_contains "$out" "would archive: $state/proj-done-" "sweep sees the bookmark-backed branch"
assert_contains "$out" "repo=proj archived=1 pending=1" "sweep keeps the pending handover"

finish "repo-key"
