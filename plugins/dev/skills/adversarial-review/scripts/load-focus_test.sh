#!/usr/bin/env bash
# load-focus.sh: source precedence, base-ref reads, the working-tree fallback,
# fenced-block handling and --gh mode (stubbed gh: a 404 means absent, any other
# failure must fail closed).
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

lf="$here/load-focus.sh"
run() { out=$(bash "$lf" "$@" 2>"$work/err"); rc=$?; err=$(<"$work/err"); }

# --- git mode --------------------------------------------------------------
repo="$work/proj"
git init -q -b main "$repo"
cat >"$repo/AGENTS.md" <<'EOF'
# Proj

## Review focus

Areas: src/api/ src/web/,
  src/core/
Migrations: db/migrations/
Extra lens: security

- check the thing

```sh
# a comment, not a heading
echo hi
```

Last line.

## Other

not part of focus
EOF
printf '# Claude\n\n## Review focus\n\nclaude md focus\n' >"$repo/CLAUDE.md"
git -C "$repo" add -A
git -C "$repo" commit -q -m base
git -C "$repo" update-ref refs/remotes/origin/dev HEAD

# The working tree drifts after the base: the base content must win.
printf '# Proj\n\n## Review focus\n\ndrifted\n' >"$repo/AGENTS.md"

run --base origin/dev --repo "$repo"
assert_eq "$rc" "0" "git mode: exit 0"
assert_contains "$out" "focus: AGENTS.md" "git mode: AGENTS.md wins over CLAUDE.md"
assert_contains "$out" "areas: src/api/ src/web/ src/core/" "git mode: areas continue over lines and commas"
assert_contains "$out" "migrations: db/migrations/" "git mode: migrations parsed"
assert_contains "$out" "extra-lens: security" "git mode: extra lens parsed"
assert_contains "$out" "- check the thing" "git mode: prose kept after ---"
assert_not_contains "$out" "drifted" "git mode: reads the base, not the working tree"
assert_not_contains "$out" "not part of focus" "git mode: stops at the next same-level heading"
assert_contains "$out" "# a comment, not a heading" "fenced '#' line stays inside the section"
assert_contains "$out" "Last line." "text after a fenced block is kept"

# CLAUDE.local.md (untracked, from disk) beats tracked files.
printf '## Review focus\n\nlocal focus\n' >"$repo/CLAUDE.local.md"
run --base origin/dev --repo "$repo"
assert_contains "$out" "focus: CLAUDE.local.md" "CLAUDE.local.md wins"
assert_contains "$out" "local focus" "CLAUDE.local.md body used"
assert_not_contains "$out" "Last line." "no concatenation across files"
rm "$repo/CLAUDE.local.md"

# A fenced "## Review focus" is not a heading; the CLAUDE.md section is used.
repo2="$work/fenced"
git init -q -b main "$repo2"
printf '# A\n\n```md\n## Review focus\nfake\n```\n' >"$repo2/AGENTS.md"
printf '# C\n\n## Review focus\n\nreal\n' >"$repo2/CLAUDE.md"
git -C "$repo2" add -A
git -C "$repo2" commit -q -m base
git -C "$repo2" update-ref refs/remotes/origin/dev HEAD
run --base origin/dev --repo "$repo2"
assert_contains "$out" "focus: CLAUDE.md" "heading inside a fence is ignored"
assert_not_contains "$out" "fake" "fenced heading body not used"

# No heading anywhere.
repo3="$work/none"
git init -q -b main "$repo3"
printf '# Nothing here\n' >"$repo3/AGENTS.md"
git -C "$repo3" add -A
git -C "$repo3" commit -q -m base
git -C "$repo3" update-ref refs/remotes/origin/dev HEAD
run --base origin/dev --repo "$repo3"
assert_eq "$out" "$(printf 'focus: none\n---')" "no heading: focus none"

# Base ref that cannot be resolved or fetched: tracked files come from disk.
printf '# Disk\n\n## Review focus\n\non disk\n' >"$repo3/AGENTS.md"
run --base origin/missing --repo "$repo3"
assert_eq "$rc" "0" "unresolvable base: exit 0"
assert_contains "$out" "focus: read from working tree" "unresolvable base: working-tree fallback"
assert_contains "$out" "on disk" "unresolvable base: disk content"

# --- --gh mode (stubbed gh) ------------------------------------------------
bin="$work/bin"
mkdir -p "$bin"
cat >"$bin/gh" <<'EOF'
#!/usr/bin/env bash
# GH_AGENTS / GH_CLAUDE: "404", "403", "net", or a file whose content is served.
printf '%s\n' "$*" >>"$GH_LOG"
case "$*" in
  *contents/AGENTS.md*) v="$GH_AGENTS" ;;
  *contents/CLAUDE.md*) v="$GH_CLAUDE" ;;
  *) echo "gh stub: unexpected call: $*" >&2; exit 99 ;;
esac
case "$v" in
  404) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
  403) echo "gh: API rate limit exceeded (HTTP 403)" >&2; exit 1 ;;
  net) echo 'error connecting to api.github.com' >&2; exit 1 ;;
  *) cat "$v" ;;
esac
EOF
chmod +x "$bin/gh"
export GH_LOG="$work/gh.log"
printf '# Remote\n\n## Review focus\n\nremote focus\n' >"$work/remote-claude.md"
printf '# Remote\n\nno focus\n' >"$work/remote-nofocus.md"

gh_run() { : >"$GH_LOG"; out=$(PATH="$bin:$PATH" bash "$lf" --gh acme/proj --base dev 2>"$work/err"); rc=$?; err=$(<"$work/err"); }

export GH_AGENTS=404 GH_CLAUDE="$work/remote-claude.md"
gh_run
assert_eq "$rc" "0" "gh: 404 on AGENTS.md falls through, exit 0"
assert_contains "$out" "focus: CLAUDE.md" "gh: CLAUDE.md used after an AGENTS.md 404"
assert_contains "$(<"$GH_LOG")" "ref=dev" "gh: reads at the base branch"

export GH_AGENTS=404 GH_CLAUDE=404
gh_run
assert_eq "$rc" "0" "gh: both 404: exit 0"
assert_eq "$out" "$(printf 'focus: unavailable (no clone)\n---')" "gh: both 404: unavailable (no clone)"

export GH_AGENTS="$work/remote-nofocus.md" GH_CLAUDE=404
gh_run
assert_eq "$rc" "0" "gh: file without the heading: exit 0"
assert_contains "$out" "focus: unavailable (no clone)" "gh: file without the heading is not focus"

export GH_AGENTS=403 GH_CLAUDE="$work/remote-claude.md"
gh_run
assert_eq "$rc" "3" "gh: rate limit on AGENTS.md fails closed"
assert_eq "$out" "" "gh: rate limit prints no focus"
assert_contains "$err" "cannot read AGENTS.md from acme/proj@dev" "gh: stderr names the file"
assert_contains "$err" "HTTP 403" "gh: stderr carries the reason"

export GH_AGENTS=404 GH_CLAUDE=net
gh_run
assert_eq "$rc" "3" "gh: network failure on CLAUDE.md fails closed"
assert_contains "$err" "error connecting" "gh: network reason on stderr"

finish "load-focus"
