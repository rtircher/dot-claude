#!/usr/bin/env bash
# handover-autoload.sh: a fresh plain handover injects on `clear` only; stale,
# respawn, BRANCH and NONE inject nothing; every failure exits 0 silently.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../scaffold/tests/lib.sh
. "$here/../scaffold/tests/lib.sh"

work="$(cd "$(mktemp -d)" && pwd -P)"
trap 'chmod -R u+rw "$work" 2>/dev/null; rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com
export HOME="$work/home"
unset HANDOVER_AUTOLOAD_MAX_AGE_MIN
state="$HOME/.claude/state"
mkdir -p "$state/handover" "$state/handover-archive"

# hook <dir> <source> [script]: run the hook from <dir> with SessionStart stdin;
# sets out, err and rc.
hook() {
  local script="${3:-$here/handover-autoload.sh}"
  out=$(cd "$1" && printf '{"session_id":"s","hook_event_name":"SessionStart","source":"%s","cwd":"%s"}' "$2" "$1" \
    | bash "$script" 2>"$work/stderr")
  rc=$?
  err=$(<"$work/stderr")
}
# age <file> <seconds>: set the file's mtime that many seconds in the past.
age() { python3 -c 'import os, sys, time; t = time.time() - int(sys.argv[2]); os.utime(sys.argv[1], (t, t))' "$1" "$2"; }
ctx() { printf '%s' "$out" | python3 -c 'import json, sys; print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])'; }
event() { printf '%s' "$out" | python3 -c 'import json, sys; print(json.load(sys.stdin)["hookSpecificOutput"]["hookEventName"])'; }
silent() { # <msg>: exit 0, nothing on stdout or stderr
  assert_eq "$rc" "0" "$1: exit 0"
  assert_eq "$out" "" "$1: no output"
  assert_eq "$err" "" "$1: nothing on stderr"
}

git init -q -b main "$work/proj"
git -C "$work/proj" commit -q --allow-empty -m initial
handover="$state/handover/proj.md"
printf '# Session handover\nRepo: %s\nBranch: feat/x\n\n## Next steps\nMARKER-NEXT-STEP\n' "$work/proj" >"$handover"

# Fresh plain handover after /clear: injects the body plus the takeover steps.
age "$handover" 60
before=$(cksum <"$handover")
hook "$work/proj" clear
assert_eq "$rc" "0" "fresh handover: exit 0"
assert_eq "$(event)" "SessionStart" "fresh handover: SessionStart envelope"
text=$(ctx)
assert_contains "$text" "MARKER-NEXT-STEP" "fresh handover: body injected"
assert_contains "$text" "$handover" "fresh handover: names the state file"
assert_contains "$text" "steps 2, 4 and 5 of $(cd "$here/.." && pwd)/commands/takeover.md" "fresh handover: points at takeover's steps"
assert_contains "$text" "rename" "fresh handover: says to skip the rename"
assert_eq "$err" "" "fresh handover: nothing on stderr"
assert_eq "$(cksum <"$handover")" "$before" "state file left untouched"
assert_eq "$(find "$state/handover-archive" -type f | wc -l | tr -d ' ')" "0" "nothing archived"

# From a git worktree of the same repo: one key, so the handover still loads.
git -C "$work/proj" worktree add -q "$work/proj-wt" -b wt
hook "$work/proj-wt" clear
assert_contains "$(ctx)" "MARKER-NEXT-STEP" "worktree of the repo: handover injected"

# Only `clear` acts; a new or resumed session never picks a handover up on its own.
for src in startup resume compact fork; do
  hook "$work/proj" "$src"
  silent "source $src"
done

# Freshness guard: default 15 minutes, overridable, 0 turns it off.
age "$handover" 1200
hook "$work/proj" clear
silent "stale handover (20 min)"
HANDOVER_AUTOLOAD_MAX_AGE_MIN=30 hook "$work/proj" clear
assert_contains "$(ctx)" "MARKER-NEXT-STEP" "window widened to 30 min: injected"
age "$handover" 60
HANDOVER_AUTOLOAD_MAX_AGE_MIN=0 hook "$work/proj" clear
silent "window 0: off"
HANDOVER_AUTOLOAD_MAX_AGE_MIN=abc hook "$work/proj" clear
assert_contains "$(ctx)" "MARKER-NEXT-STEP" "non-numeric window falls back to the default"
HANDOVER_AUTOLOAD_MAX_AGE_MIN=08 hook "$work/proj" clear
assert_contains "$(ctx)" "MARKER-NEXT-STEP" "leading-zero window read as decimal"

# A handover over the 10,000-character context cap is pointed at, not inlined:
# Claude Code would cut it to a preview and never ask Claude to read the rest.
cp "$handover" "$work/handover.bak"
python3 -c 'import sys; open(sys.argv[1], "a").write("x" * 12000)' "$handover"
hook "$work/proj" clear
text=$(ctx)
assert_eq "$(( ${#text} < 10000 ))" "1" "oversized handover: context under the cap"
assert_not_contains "$text" "MARKER-NEXT-STEP" "oversized handover: body not inlined"
assert_contains "$text" "$handover" "oversized handover: names the file to read"
assert_contains "$text" "steps 2, 4 and 5" "oversized handover: still carries the steps"
cp "$work/handover.bak" "$handover"
age "$handover" 60

# A newer respawn handover belongs to the session respawn started.
respawn="$state/handover/proj-slug-20260101T000000Z.md"
printf 'Repo: %s\n\n## Respawn\nBase commit: abc\n' "$work/proj" >"$respawn"
hook "$work/proj" clear
silent "newest LOCAL is a respawn handover"
rm "$respawn"

# Unreadable state file (root reads it anyway).
if [ "$(id -u)" != 0 ]; then
  chmod 000 "$handover"
  hook "$work/proj" clear
  silent "unreadable state file"
  chmod 644 "$handover"
fi

# NONE: no handover for this repo.
git init -q -b main "$work/empty"
git -C "$work/empty" commit -q --allow-empty -m initial
hook "$work/empty" clear
silent "NONE"

# BRANCH: a handover/* branch on origin, already mapped by the clone.
git init -q -b main "$work/seed"
git -C "$work/seed" commit -q --allow-empty -m initial
git -C "$work/seed" branch handover/one
mkdir -p "$work/acme"
git clone -q --bare "$work/seed" "$work/acme/br.git"
git clone -q "$work/acme/br.git" "$work/br"
hook "$work/br" clear
silent "BRANCH"
# Never fetches: an unmapped handover branch stays unmapped.
git -C "$work/br" update-ref -d refs/remotes/origin/handover/one
hook "$work/br" clear
silent "BRANCH unmapped"
assert_eq "$(git -C "$work/br" for-each-ref refs/remotes/origin/handover/ | wc -l | tr -d ' ')" "0" "hook does not fetch"

# Malformed stdin.
out=$(cd "$work/proj" && printf 'not json' | bash "$here/handover-autoload.sh" 2>"$work/stderr")
rc=$? err=$(<"$work/stderr")
silent "malformed stdin"

# find-handover.sh failing.
mkdir -p "$work/broken"
cp "$here/handover-autoload.sh" "$work/broken/"
printf '#!/usr/bin/env bash\necho boom >&2\nexit 3\n' >"$work/broken/find-handover.sh"
hook "$work/proj" clear "$work/broken/handover-autoload.sh"
silent "find-handover.sh fails"

# python3 failing (stdin parse and JSON encode both need it).
mkdir -p "$work/bin"
printf '#!/usr/bin/env bash\necho nope >&2\nexit 1\n' >"$work/bin/python3"
chmod +x "$work/bin/python3"
PATH="$work/bin:$PATH" hook "$work/proj" clear
silent "python3 fails"

finish "handover-autoload"
