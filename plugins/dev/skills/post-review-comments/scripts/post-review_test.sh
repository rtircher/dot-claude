#!/usr/bin/env bash
# post-review.sh: repo from --remote, plan and file validation, 0/1/many line
# matches (RIGHT at the head SHA, LEFT at the base SHA), the pending-review
# refusal, the dry run, and the create / verify / submit path with its delete-on-
# mismatch exit 3. gh is stubbed and `git fetch` is a no-op, so nothing here
# touches the network or posts anything.
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
  "pr view"*baseRefOid*) printf '%s\n' "$GH_BASE" ;;
  "pr view"*) printf '%s\n' "$GH_SHA" ;;
  "api user"*) echo me ;;
  *"reviews/555/comments"*) cat "$GH_COMMENTS" ;;
  *"reviews/555/events"*) [ "${GH_FAIL_SUBMIT:-0}" = 1 ] && exit 1; echo '{"html_url":"https://example.test/r/555"}' ;;
  *"reviews/555"*DELETE*) : ;;
  *"/pulls/"*"/reviews"*POST*) cat >"$GH_REQ"; echo '{"id":555}' ;;
  *"/pulls/"*"/reviews"*) printf '%s' "$GH_PENDING" ;;
  *) echo "gh stub: unexpected call: $*" >&2; exit 99 ;;
esac
EOF
chmod +x "$bin/git" "$bin/gh"
export STUB_LOG="$work/stub.log"
: >"$STUB_LOG"

repo="$work/proj"
"$real_git" init -q -b main "$repo"
printf 'alpha\nbeta\ngone\nbeta2\n' >"$repo/f.txt"
"$real_git" -C "$repo" add -A
"$real_git" -C "$repo" commit -q -m base
export GH_SHA GH_BASE GH_PENDING="" GH_REQ="$work/req.json" GH_COMMENTS="$work/comments.json"
GH_BASE=$("$real_git" -C "$repo" rev-parse HEAD)
printf 'alpha\nbeta\nnew line\nbeta2\n' >"$repo/f.txt"
"$real_git" -C "$repo" commit -q -am head
GH_SHA=$("$real_git" -C "$repo" rev-parse HEAD)
"$real_git" -C "$repo" remote add origin git@github.com:acme/proj.git

printf 'tag: new\n' >"$work/b1.md"
printf 'tag: ctx\n' >"$work/b2.md"
printf 'tag: deleted\n' >"$work/b3.md"
printf 'summary\n' >"$work/summary.md"
cat >"$work/plan.json" <<JSON
[{"path":"f.txt","pattern":"^new line$","body_file":"$work/b1.md"},
 {"path":"f.txt","pattern":"^alpha$","body_file":"$work/b2.md","side":"RIGHT"},
 {"path":"f.txt","pattern":"^gone$","body_file":"$work/b3.md","side":"LEFT"}]
JSON
cat >"$work/comments_ok.json" <<JSON
[{"path":"f.txt","body":"tag: new\n","diff_hunk":"@@ -1,4 +1,4 @@\n alpha\n beta\n-gone\n+new line"},
 {"path":"f.txt","body":"tag: ctx","diff_hunk":"@@ -1,4 +1,4 @@\n alpha"},
 {"path":"f.txt","body":"tag: deleted","diff_hunk":"@@ -1,4 +1,4 @@\n alpha\n beta\n-gone"}]
JSON
cp "$work/comments_ok.json" "$GH_COMMENTS"

pr() { # args... ; runs in the clone with the stubs first on PATH
  out=$(cd "$repo" && PATH="$bin:$PATH" bash "$here/post-review.sh" "$@" 2>"$work/err"); rc=$?
  err=$(<"$work/err")
}
base=(--pr 7 --remote origin --plan "$work/plan.json" --summary-file "$work/summary.md")

# Repo from --remote, in every URL form; --repo wins.
for url in git@github.com:acme/proj.git ssh://git@github.com:22/acme/proj.git https://github.com/acme/proj/; do
  "$real_git" -C "$repo" remote set-url origin "$url"
  pr "${base[@]}" --dry-run
  assert_contains "$out" "POST repos/acme/proj/pulls/7/reviews" "repo from remote: $url"
  assert_eq "$rc" "0" "dry-run exits 0 for $url"
done
pr "${base[@]}" --dry-run --repo other/thing
assert_contains "$out" "POST repos/other/thing/pulls/7/reviews" "explicit --repo wins"

"$real_git" -C "$repo" remote set-url origin /srv/git/proj.git
pr "${base[@]}" --dry-run
assert_eq "$rc" "1" "unparseable remote exits 1"
assert_contains "$err" "cannot derive owner/repo from remote 'origin'" "unparseable remote message"
"$real_git" -C "$repo" remote set-url origin git@github.com:acme/proj.git
pr "${base[@]}" --remote nosuch --dry-run
assert_eq "$rc" "1" "unknown remote exits 1"
assert_contains "$err" "no git remote named 'nosuch'" "unknown remote message"

# Input validation happens before any gh call.
: >"$STUB_LOG"
pr --pr 7 --remote origin --plan "$work/nope.json" --dry-run
assert_contains "$err" "no such plan file" "missing plan message"
echo '{"not":"a list"}' >"$work/bad.json"
pr --pr 7 --remote origin --plan "$work/bad.json" --dry-run
assert_contains "$err" "plan must be a non-empty JSON list" "malformed plan message"
echo '[{"path":"f.txt","pattern":"x","body_file":"'"$work"'/nope.md"}]' >"$work/nobody.json"
pr --pr 7 --remote origin --plan "$work/nobody.json" --dry-run
assert_contains "$err" "no such body file" "missing body file message"
pr "${base[@]}" --summary-file "$work/nope.md" --dry-run
assert_contains "$err" "no such summary file" "missing summary file message"
assert_eq "$(<"$STUB_LOG")" "" "validation failures: no gh or fetch call"

# Line matching: 0 and many matches, RIGHT at head, LEFT at base.
for p in '^nomatch$:0' '^beta:2'; do
  echo '[{"path":"f.txt","pattern":"'"${p%%:*}"'","body_file":"'"$work"'/b1.md"}]' >"$work/one.json"
  pr --pr 7 --remote origin --plan "$work/one.json" --dry-run
  assert_eq "$rc" "1" "${p%%:*}: exits 1"
  assert_contains "$err" "matched ${p##*:} lines of f.txt" "${p%%:*}: match count message"
done
echo '[{"path":"f.txt","pattern":"^gone$","body_file":"'"$work"'/b1.md"}]' >"$work/one.json"
pr --pr 7 --remote origin --plan "$work/one.json" --dry-run
assert_eq "$rc" "1" "a deleted line is not found on RIGHT"

# Dry run: anchors, request body, no writes.
: >"$STUB_LOG"
pr "${base[@]}" --dry-run
assert_eq "$rc" "0" "dry-run exits 0"
assert_contains "$out" "anchor: f.txt:3 RIGHT @" "dry-run: added line anchored on its head line"
assert_contains "$out" "anchor: f.txt:1 RIGHT @" "dry-run: context line anchored"
assert_contains "$out" "anchor: f.txt:3 LEFT @" "dry-run: deleted line anchored in the base"
assert_contains "$out" "\"commit_id\": \"$GH_SHA\"" "dry-run: request pins the head SHA"
assert_not_contains "$out" '"event"' "dry-run: request has no event"
assert_not_contains "$(<"$STUB_LOG")" "POST" "dry-run: no write call"
assert_not_contains "$(<"$STUB_LOG")" "DELETE" "dry-run: no delete call"

# An existing pending review refuses, naming its id, with no writes.
GH_PENDING=$'4242\n'
: >"$STUB_LOG"
pr "${base[@]}"
assert_eq "$rc" "1" "pending review exits 1"
assert_contains "$err" "review id 4242" "pending review id named"
assert_not_contains "$(<"$STUB_LOG")" "POST" "pending review: no write call"
GH_PENDING=""

# Real post: created PENDING, verified, submitted.
: >"$STUB_LOG"
pr "${base[@]}"
assert_eq "$rc" "0" "post verified exits 0"
assert_contains "$out" "posted: review 555, 3 comments" "post message"
assert_contains "$out" "url: https://example.test/r/555" "html_url printed"
assert_eq "$(jq -c '[.comments[] | [.line, .side]]' "$GH_REQ")" '[[3,"RIGHT"],[1,"RIGHT"],[3,"LEFT"]]' "request lines and sides"
assert_eq "$(jq -r 'has("event")' "$GH_REQ")" "false" "create request has no event"
assert_eq "$(jq -r '.body' "$GH_REQ")" "summary" "summary is the review body"
assert_contains "$(<"$STUB_LOG")" "reviews/555/events --method POST -f event=COMMENT" "submitted as COMMENT"
assert_not_contains "$(<"$STUB_LOG")" "DELETE" "clean post deletes nothing"

# A misplaced comment: review deleted, never submitted, exit 3.
jq '.[1].diff_hunk = "@@ -1,4 +1,4 @@\n alpha\n beta"' "$work/comments_ok.json" >"$GH_COMMENTS"
: >"$STUB_LOG"
pr "${base[@]}"
assert_eq "$rc" "3" "misplaced comment exits 3"
assert_contains "$err" "entry 2 f.txt:1 RIGHT: WRONG" "misplaced entry reported"
assert_contains "$err" "entry 1 f.txt:3 RIGHT: ok" "correct entries reported too"
assert_contains "$(<"$STUB_LOG")" "reviews/555 --method DELETE" "misplaced: pending review deleted"
assert_not_contains "$(<"$STUB_LOG")" "events" "misplaced: never submitted"

# A LEFT comment on a context line is wrong too (needs a '-' line).
jq '.[2].diff_hunk = "@@ -1,4 +1,4 @@\n alpha\n beta\n gone"' "$work/comments_ok.json" >"$GH_COMMENTS"
pr "${base[@]}"
assert_eq "$rc" "3" "LEFT comment on a non-deleted line exits 3"

# A missing comment (path+body not found) is a mismatch.
jq 'del(.[0])' "$work/comments_ok.json" >"$GH_COMMENTS"
pr "${base[@]}"
assert_eq "$rc" "3" "missing comment exits 3"
assert_contains "$err" "expected 3 comments, review has 2" "missing comment message"

# A failed submit deletes the pending review, exit 3.
cp "$work/comments_ok.json" "$GH_COMMENTS"
: >"$STUB_LOG"
GH_FAIL_SUBMIT=1 pr "${base[@]}"
assert_eq "$rc" "3" "failed submit exits 3"
assert_contains "$(<"$STUB_LOG")" "reviews/555 --method DELETE" "failed submit: pending review deleted"

finish "post-review"
