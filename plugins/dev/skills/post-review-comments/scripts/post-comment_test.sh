#!/usr/bin/env bash
# post-comment.sh: repo derived from --remote (ssh, scp, https, ssh aliases),
# fail-closed on an unparseable remote, body-file check, 0/1/many line matches,
# the dry-run anchor check and the post-and-verify path. gh is stubbed and
# `git fetch` is a no-op, so nothing here touches the network; the gh stub fails
# the test run on `gh repo view`, the lookup this script must no longer make.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../../scaffold/tests/lib.sh
. "$here/../../../scaffold/tests/lib.sh"

work="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com
export HOME="$work/home"
mkdir -p "$HOME"

real_git="$(command -v git)"
bin="$work/bin"
mkdir -p "$bin"
cat >"$bin/git" <<EOF
#!/usr/bin/env bash
# fetch would reach the network; everything else is the real git.
if [ "\${1:-}" = fetch ]; then printf 'git %s\n' "\$*" >>"\$STUB_LOG"; exit 0; fi
exec "$real_git" "\$@"
EOF
cat >"$bin/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$STUB_LOG"
case "$*" in
  "pr view"*) printf '%s\n' "$GH_SHA" ;;
  *"/pulls/"*"/files"*) cat "$GH_PATCH" ;;
  *"pulls/comments/777"*) printf '%s\n' "$GH_HUNK_LAST" ;;
  *"/pulls/"*"/comments"*"POST"*) echo 777 ;;
  *) echo "gh stub: unexpected call: $*" >&2; exit 99 ;;
esac
EOF
chmod +x "$bin/git" "$bin/gh"
export STUB_LOG="$work/stub.log"
: >"$STUB_LOG"

repo="$work/proj"
"$real_git" init -q -b main "$repo"
printf 'alpha\nbeta\ngamma\nbeta2\n' >"$repo/f.txt"
"$real_git" -C "$repo" add -A
"$real_git" -C "$repo" commit -q -m base
export GH_SHA GH_PATCH="$work/patch" GH_HUNK_LAST
GH_SHA=$("$real_git" -C "$repo" rev-parse HEAD)
printf '@@ -0,0 +1,4 @@\n+alpha\n+beta\n+gamma\n+beta2\n' >"$GH_PATCH"
printf 'tag: body\n' >"$work/body.md"

pc() { # args... ; runs in the clone with the stubs first on PATH
  out=$(cd "$repo" && PATH="$bin:$PATH" bash "$here/post-comment.sh" "$@" 2>"$work/err"); rc=$?
  err=$(<"$work/err")
}
base=(--pr 7 --remote origin --path f.txt --body-file "$work/body.md" --dry-run)

# Repo from --remote, in every URL form.
for url in \
  git@github.com:acme/proj.git \
  git@github.com:acme/proj \
  git@github-personal:acme/proj.git \
  ssh://git@github.com/acme/proj.git \
  ssh://git@github.com:22/acme/proj.git \
  https://github.com/acme/proj.git \
  https://github.com/acme/proj \
  https://github.com/acme/proj/; do
  "$real_git" -C "$repo" remote remove origin 2>/dev/null
  "$real_git" -C "$repo" remote add origin "$url"
  pc "${base[@]}" --pattern '^alpha$'
  assert_contains "$out" "repos/acme/proj/pulls/7/comments" "repo from remote: $url"
  assert_eq "$rc" "0" "exit 0 for $url"
done

# The remote named by --remote is the one used, not origin.
"$real_git" -C "$repo" remote add fork git@github.com:me/proj-fork.git
pc --pr 7 --remote fork --path f.txt --body-file "$work/body.md" --dry-run --pattern '^alpha$'
assert_contains "$out" "repos/me/proj-fork/pulls/7/comments" "uses the --remote named, not origin"
assert_contains "$(<"$STUB_LOG")" "pr view 7 -R me/proj-fork" "head SHA looked up in the remote's repo"

# An explicit --repo skips the remote lookup.
pc "${base[@]}" --pattern '^alpha$' --repo other/thing
assert_contains "$out" "repos/other/thing/pulls/7/comments" "explicit --repo wins"

# Unparseable remotes fail closed with a clear message.
for url in /srv/git/proj.git https://github.com/proj git@github.com:proj.git; do
  "$real_git" -C "$repo" remote remove origin
  "$real_git" -C "$repo" remote add origin "$url"
  pc "${base[@]}" --pattern '^alpha$'
  assert_eq "$rc" "1" "unparseable remote exits 1: $url"
  assert_contains "$err" "cannot derive owner/repo from remote 'origin'" "unparseable remote message: $url"
done

pc "${base[@]}" --remote nosuch --pattern '^alpha$'
assert_eq "$rc" "1" "unknown remote exits 1"
assert_contains "$err" "no git remote named 'nosuch'" "unknown remote message"

# Missing body file is rejected before any lookup.
: >"$STUB_LOG"
pc --pr 7 --remote origin --path f.txt --pattern '^alpha$' --body-file "$work/nope.md" --dry-run
assert_eq "$rc" "1" "missing body file exits 1"
assert_contains "$err" "no such body file" "missing body file message"
assert_eq "$(<"$STUB_LOG")" "" "missing body file: no gh or fetch call"

# Line matching: 0, 1 and many matches at the pinned SHA.
"$real_git" -C "$repo" remote remove origin
"$real_git" -C "$repo" remote add origin git@github.com:acme/proj.git
pc "${base[@]}" --pattern '^nomatch$'
assert_eq "$rc" "1" "0 matches exits 1"
assert_contains "$err" "matched 0 lines of f.txt" "0 matches message"

pc "${base[@]}" --pattern '^beta'
assert_eq "$rc" "1" "2 matches exits 1"
assert_contains "$err" "matched 2 lines of f.txt" "many matches message"
assert_contains "$err" "4:beta2" "many matches listed"

pc "${base[@]}" --pattern '^gamma$'
assert_eq "$rc" "0" "1 match exits 0"
assert_contains "$out" "anchor: f.txt:3 @" "1 match anchors on line 3"
assert_contains "$out" "inside the diff hunk covering new lines 1-4" "dry-run anchor check passes"
assert_contains "$out" "dry-run, would run:" "dry-run prints the call"

# Dry run: the matched line outside every hunk is refused.
printf '@@ -0,0 +1,2 @@\n+alpha\n+beta\n' >"$GH_PATCH"
pc "${base[@]}" --pattern '^gamma$'
assert_eq "$rc" "1" "line outside the diff hunk exits 1"
assert_contains "$err" "outside every diff hunk" "outside-hunk message"
printf '@@ -0,0 +1,4 @@\n+alpha\n+beta\n+gamma\n+beta2\n' >"$GH_PATCH"

# Real post: verified via diff_hunk (exit 0) or reported misplaced (exit 3).
GH_HUNK_LAST='+gamma'
pc --pr 7 --remote origin --path f.txt --body-file "$work/body.md" --pattern '^gamma$'
assert_eq "$rc" "0" "post verified exits 0"
assert_contains "$out" "posted: comment 777 on f.txt:3" "post verified message"
GH_HUNK_LAST='+beta'
pc --pr 7 --remote origin --path f.txt --body-file "$work/body.md" --pattern '^gamma$'
assert_eq "$rc" "3" "misplaced comment exits 3"
assert_contains "$err" "delete it: gh api -X DELETE repos/acme/proj/pulls/comments/777" "misplaced: delete command printed"

assert_not_contains "$(<"$STUB_LOG")" "repo view" "never asks gh for the repo"

finish "post-comment"
