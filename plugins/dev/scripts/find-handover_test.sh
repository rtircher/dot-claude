#!/usr/bin/env bash
# find-handover.sh outcomes: NONE, ARCHIVE, BRANCH (fetched and not, newest first,
# with and without a doc) and LOCAL precedence. repo-key_test.sh covers the key
# and ROOT resolution and the LOCAL early exit from a jj workspace.
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
mkdir -p "$state/handover" "$state/handover-archive"

fh() { (cd "$1" && shift && bash "$here/find-handover.sh" "$@"); }

# Nothing anywhere: no origin, no state.
git init -q -b main "$work/nohand"
git -C "$work/nohand" commit -q --allow-empty -m initial
assert_eq "$(fh "$work/nohand" --no-fetch)" \
  "$(printf 'KEY\tnohand\nROOT\t%s\nORIGIN\t\nNONE' "$work/nohand")" "no handover anywhere: NONE with empty ORIGIN"

# Archive only: the newest file wins by mtime (mv keeps it), whatever the slug.
git init -q -b main "$work/arch"
git -C "$work/arch" commit -q --allow-empty -m initial
a="$state/handover-archive"
printf 'Repo: %s\n' "$work/arch" >"$a/arch-b-20260101T000000Z-20260102T000000Z.md"
printf 'Repo: %s\n' "$work/arch" >"$a/arch-a-20260301T000000Z-20260302T000000Z.md"
touch -d '2026-01-01' "$a/arch-b-20260101T000000Z-20260102T000000Z.md"
touch -d '2026-03-01' "$a/arch-a-20260301T000000Z-20260302T000000Z.md"
: >"$a/other-20260401T000000Z.md"
# Repo arch-x shares the `arch-` prefix: its archived handover and archived
# respawn are newest but belong to arch-x.
printf 'Repo: %s\n' "$work/arch-x" >"$a/arch-x-20260501T000000Z.md"
printf 'Repo: %s\n' "$work/arch-x" >"$a/arch-x-fix-20260501T000000Z-20260502T000000Z.md"
out=$(fh "$work/arch" --no-fetch)
assert_contains "$out" "ARCHIVE	$a/arch-a-20260301T000000Z-20260302T000000Z.md" "newest archive by mtime, not by slug"
assert_not_contains "$out" "other-2026" "another repo's archive ignored"
assert_not_contains "$out" "arch-x-" "archives of a repo whose key extends this one ignored"
# /dev:handover archives <key>.md as <key>-<ts>.md, a name only this repo writes,
# so it counts whatever its Repo: says (a worktree path, here).
printf 'Repo: %s\n' "$work/arch/.claude/worktrees/wt" >"$a/arch-20260401T000000Z.md"
touch -d '2026-04-01' "$a/arch-20260401T000000Z.md"
out=$(fh "$work/arch" --no-fetch)
assert_contains "$out" "ARCHIVE	$a/arch-20260401T000000Z.md" "a newer <key>-<ts>.md archive beats an older slug archive"

# Branch-carried handovers on origin: a bare origin with two handover/* branches.
git init -q -b main "$work/seed"
git -C "$work/seed" commit -q --allow-empty -m initial
mkdir -p "$work/seed/docs/handovers"
printf '# H\n\n## Task & goal\n\nFix the thing\n\n## Next\n' >"$work/seed/docs/handovers/h.md"
git -C "$work/seed" add -A
GIT_COMMITTER_DATE="2026-01-01T00:00:00Z" git -C "$work/seed" commit -q -m "older handover"
git -C "$work/seed" branch handover/one
git -C "$work/seed" reset -q --hard HEAD~1
GIT_COMMITTER_DATE="2026-02-01T00:00:00Z" git -C "$work/seed" commit -q --allow-empty -m "newer, no doc"
git -C "$work/seed" branch handover/two
mkdir -p "$work/acme"
git clone -q --bare "$work/seed" "$work/acme/br.git"
git clone -q "$work/acme/br.git" "$work/br"
# A clone already maps every remote branch; drop them so only a fetch can bring them.
git -C "$work/br" update-ref -d refs/remotes/origin/handover/one
git -C "$work/br" update-ref -d refs/remotes/origin/handover/two
printf 'Repo: %s\n' "$work/br" >"$state/handover-archive/br-x-20260101T000000Z-20260102T000000Z.md"

out=$(fh "$work/br" --no-fetch)
assert_contains "$out" "ORIGIN	acme/br" "origin normalised to owner/repo"
assert_not_contains "$out" "BRANCH" "--no-fetch does not fetch handover branches"
assert_contains "$out" "ARCHIVE	" "--no-fetch falls through to the archive"

out=$(fh "$work/br")
assert_eq "$(printf '%s\n' "$out" | grep -c '^BRANCH')" "2" "fetch finds both handover branches"
assert_eq "$(printf '%s\n' "$out" | grep '^BRANCH' | awk -F'\t' 'NR==1{print $2}')" "origin/handover/two" "newest branch first"
assert_contains "$out" "BRANCH	origin/handover/two	2026-02-01" "newest branch carries its commit date"
assert_contains "$out" "origin/handover/two	2026-02-01 00:00:00 +0000	-	" "branch without a doc prints - and no task"
assert_contains "$out" "docs/handovers/h.md	Fix the thing" "branch with a doc prints its path and task line"
assert_not_contains "$out" "ARCHIVE" "branches win over the archive"

# A local state file wins over branches and the archive, and the newest file
# wins, a note after its Repo: path included.
printf 'Repo: %s\n' "$work/br" >"$state/handover/br.md"
printf 'Repo: %s (note)\n' "$work/br" >"$state/handover/br-respawn-20260301T000000Z.md"
touch -d '2026-01-01' "$state/handover/br.md"
touch -d '2026-03-01' "$state/handover/br-respawn-20260301T000000Z.md"
out=$(fh "$work/br" --no-fetch)
assert_contains "$out" "LOCAL	$state/handover/br-respawn-20260301T000000Z.md" "newest local state file"
assert_not_contains "$out" "BRANCH" "LOCAL stops the search before branches"
assert_not_contains "$out" "ARCHIVE" "LOCAL stops the search before the archive"

# Repo proj-x shares the `proj-` prefix. Its plain handover (proj-x.md) and its
# respawn handover (proj-x-<slug>-<ts>.md) are newer than proj.md but are not
# proj's, so proj.md wins.
git init -q -b main "$work/proj"
git -C "$work/proj" commit -q --allow-empty -m initial
h="$state/handover"
printf 'Repo: %s\n' "$work/proj" >"$h/proj.md"
printf 'Repo: %s\n' "$work/proj-x" >"$h/proj-x.md"
touch -d '2026-01-01' "$h/proj.md"
touch -d '2026-02-01' "$h/proj-x.md"
out=$(fh "$work/proj" --no-fetch)
assert_contains "$out" "LOCAL	$h/proj.md" "another repo's plain handover sharing the key prefix never wins"
printf 'Repo: %s\nBranch: feat/fix\n' "$work/proj-x" >"$h/proj-x-fix-20260301T000000Z.md"
touch -d '2026-03-01' "$h/proj-x-fix-20260301T000000Z.md"
out=$(fh "$work/proj" --no-fetch)
assert_contains "$out" "LOCAL	$h/proj.md" "another repo's respawn handover sharing the key prefix never wins"

# Respawn handovers alone, no <key>.md. Repo: decides first, so a matching file
# counts without the exact stamp; with no Repo: line a stamped name still counts
# and takeover's Repo check warns.
git init -q -b main "$work/resp"
git -C "$work/resp" commit -q --allow-empty -m initial
printf 'Repo: %s\nBranch: feat/fix\n' "$work/resp" >"$h/resp-fix-20260101T000000Z.md"
touch -d '2026-01-01' "$h/resp-fix-20260101T000000Z.md"
out=$(fh "$work/resp" --no-fetch)
assert_contains "$out" "LOCAL	$h/resp-fix-20260101T000000Z.md" "a respawn handover is found with no <key>.md"
printf 'Repo: %s\n' "$work/resp" >"$h/resp-notes-20260821.md"
touch -d '2026-02-01' "$h/resp-notes-20260821.md"
out=$(fh "$work/resp" --no-fetch)
assert_contains "$out" "LOCAL	$h/resp-notes-20260821.md" "a matching Repo: counts without the exact stamp"
printf 'Branch: feat/old\n' >"$h/resp-old-20260301T000000Z.md"
touch -d '2026-03-01' "$h/resp-old-20260301T000000Z.md"
out=$(fh "$work/resp" --no-fetch)
assert_contains "$out" "LOCAL	$h/resp-old-20260301T000000Z.md" "a stamped name with no Repo: line still counts"

# Outside a repo (KEY default, empty ROOT) no sibling key can collide, so a
# stamped name counts whatever its Repo: says.
mkdir -p "$work/norepo"
printf 'Repo: /somewhere\n' >"$h/default-fix-20260101T000000Z.md"
out=$(fh "$work/norepo" --no-fetch)
assert_contains "$out" "LOCAL	$h/default-fix-20260101T000000Z.md" "outside a repo a stamped default-* handover counts"

finish "find-handover"
