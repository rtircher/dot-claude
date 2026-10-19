#!/usr/bin/env bash
# handover-archive-sweep.sh: --dry-run moves nothing, the real run moves exactly
# the handovers whose branch exists, and it leaves pending, foreign-repo and
# shared-slot files alone. repo-key_test.sh covers the dry run from a jj workspace.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../scaffold/tests/lib.sh
. "$here/../scaffold/tests/lib.sh"

work="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com
export HOME="$work/home"
state="$HOME/.claude/state"
mkdir -p "$state/handover"

repo="$work/sw"
git init -q -b main "$repo"
git -C "$repo" commit -q --allow-empty -m initial
git -C "$repo" branch feat/done
git -C "$repo" branch feat/done2

h="$state/handover"
printf 'Repo: %s\nBranch: feat/done\n' "$repo" >"$h/sw-done-20260101T000000Z.md"
printf 'Repo: %s (checked out on the VM)\nBranch: feat/done2\n' "$repo" >"$h/sw-note-20260101T000000Z.md"
printf 'Repo: %s\nBranch: feat/pending\n' "$repo" >"$h/sw-pending-20260101T000000Z.md"
printf 'Repo: %s\n' "$repo" >"$h/sw-nobranch-20260101T000000Z.md"
printf 'Repo: /elsewhere/sw\nBranch: feat/done\n' >"$h/sw-foreign-20260101T000000Z.md"
printf 'Repo: %s\nBranch: feat/done\n' "$repo" >"$h/sw.md"

sweep() { (cd "$repo" && bash "$here/handover-archive-sweep.sh" "$@"); }

out=$(sweep --dry-run)
assert_contains "$out" "repo=sw archived=2 pending=2 other-repo=1 (dry run)" "dry run counts"
assert_eq "$(ls "$h" | wc -l | tr -d ' ')" "6" "dry run moves nothing"
assert_eq "$(ls "$state/handover-archive" | wc -l | tr -d ' ')" "0" "dry run archives nothing"

out=$(sweep)
assert_contains "$out" "repo=sw archived=2 pending=2 other-repo=1" "real run counts"
assert_not_contains "$out" "(dry run)" "real run is not labelled a dry run"
assert_contains "$out" "archived: $h/sw-done-20260101T000000Z.md -> $state/handover-archive/sw-done-20260101T000000Z-" "real run names the move"

# Archived: gone from handover/, present under a UTC-timestamped name, content intact.
assert_eq "$([ -e "$h/sw-done-20260101T000000Z.md" ] && echo present || echo gone)" "gone" "done handover left handover/"
assert_eq "$([ -e "$h/sw-note-20260101T000000Z.md" ] && echo present || echo gone)" "gone" "handover with a Repo: note left handover/"
done_arch=$(printf '%s\n' "$state"/handover-archive/sw-done-20260101T000000Z-*.md)
assert_contains "$done_arch" "-20" "archive name carries a timestamp"
assert_contains "$(basename "$done_arch")" "Z.md" "archive name ends with the UTC stamp"
assert_eq "$(<"$done_arch")" "$(printf 'Repo: %s\nBranch: feat/done' "$repo")" "archived content intact"
assert_eq "$(ls "$state/handover-archive" | wc -l | tr -d ' ')" "2" "exactly two archived"

# Untouched: pending branch, no Branch line, another repo's file, the shared slot.
for f in sw-pending-20260101T000000Z sw-nobranch-20260101T000000Z sw-foreign-20260101T000000Z sw; do
  assert_eq "$([ -e "$h/$f.md" ] && echo present || echo gone)" "present" "$f stays"
done

# Once the pending branch exists, the next run archives it; nothing else moves.
git -C "$repo" branch feat/pending
out=$(sweep)
assert_contains "$out" "repo=sw archived=1 pending=1 other-repo=1" "pending handover archived once its branch exists"
out=$(sweep)
assert_contains "$out" "repo=sw archived=0 pending=1 other-repo=1" "idempotent when nothing is ready"

finish "handover-archive-sweep"
