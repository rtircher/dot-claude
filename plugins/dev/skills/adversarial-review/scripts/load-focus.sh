#!/usr/bin/env bash
# Usage: load-focus.sh --base <ref> [--repo <dir>] [--gh <owner/repo>]
#
# Loads the `## Review focus` section for adversarial-review. Checks, in order,
# CLAUDE.local.md (untracked, read from disk at the repo root), AGENTS.md, then
# CLAUDE.md; the first file with the heading wins, with no concatenation.
# Tracked files are read at the base ref, never from the working tree unless the
# base cannot be fetched.
#
#   --base <ref>   git mode: a ref such as origin/dev (fetched when absent).
#                  --gh mode: the bare branch name, such as dev.
#   --repo <dir>   the cwd repo root (default: git toplevel of the cwd). Pass the
#                  original checkout, not a detached review worktree.
#   --gh <o/r>     no clone: read tracked files with `gh api`; CLAUDE.local.md is
#                  skipped.
#
# Output (read-only, no side effects beyond a possible `git fetch`):
#   focus: <CLAUDE.local.md|AGENTS.md|CLAUDE.md|none|unavailable (no clone)|read from working tree>
#   areas: <space-separated path prefixes>      (omitted when none declared)
#   migrations: <space-separated path prefixes> (omitted when none declared)
#   extra-lens: <name>                          (omitted when none declared)
#   ---
#   <the rest of the section, verbatim>
set -euo pipefail

base="" repo="" gh_repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="${2:?--base needs a value}"; shift 2 ;;
    --repo) repo="${2:?--repo needs a value}"; shift 2 ;;
    --gh) gh_repo="${2:?--gh needs a value}"; shift 2 ;;
    *) echo "usage: load-focus.sh --base <ref> [--repo <dir>] [--gh <owner/repo>]" >&2; exit 2 ;;
  esac
done
[ -n "$base" ] || { echo "usage: load-focus.sh --base <ref> [--repo <dir>] [--gh <owner/repo>]" >&2; exit 2; }
if [ -z "$gh_repo" ] && [ -z "$repo" ]; then repo=$(git rev-parse --show-toplevel); fi

# Prints the section body (after the heading, up to the next heading of the same
# or a higher level); exits 1 when the heading is absent.
section() {
  awk '
    !found && /^#+[ \t]+Review focus[ \t]*$/ { h = $0; sub(/[ \t].*/, "", h); level = length(h); found = 1; next }
    found {
      if (match($0, /^#+[ \t]/)) { h = $0; sub(/[ \t].*/, "", h); if (length(h) <= level) exit }
      print
    }
    END { exit found ? 0 : 1 }
  '
}

# Git mode: resolve the base once (fetching it when absent); when that fails,
# tracked files are read from the working tree instead.
on_disk_fallback=0
if [ -z "$gh_repo" ] && ! git -C "$repo" rev-parse --verify -q "$base^{commit}" >/dev/null; then
  git -C "$repo" fetch "${base%%/*}" "${base#*/}" >/dev/null 2>&1 || true
  git -C "$repo" rev-parse --verify -q "$base^{commit}" >/dev/null || on_disk_fallback=1
fi

read_tracked() { # file -> stdout, non-zero status when absent
  local f="$1"
  if [ -n "$gh_repo" ]; then
    gh api -H "Accept: application/vnd.github.raw" "repos/$gh_repo/contents/$f?ref=$base" 2>/dev/null
  elif [ "$on_disk_fallback" = 1 ]; then
    cat "$repo/$f" 2>/dev/null
  else
    git -C "$repo" show "$base:$f" 2>/dev/null
  fi
}

source_name="" body=""
if [ -z "$gh_repo" ] && [ -f "$repo/CLAUDE.local.md" ] && b=$(section <"$repo/CLAUDE.local.md"); then
  source_name="CLAUDE.local.md" body="$b"
fi
if [ -z "$source_name" ]; then
  for f in AGENTS.md CLAUDE.md; do
    if text=$(read_tracked "$f") && b=$(printf '%s\n' "$text" | section); then
      source_name="$f" body="$b"
      [ "$on_disk_fallback" = 1 ] && source_name="read from working tree"
      break
    fi
  done
fi

if [ -z "$source_name" ]; then
  if [ -n "$gh_repo" ]; then echo "focus: unavailable (no clone)"; else echo "focus: none"; fi
  echo "---"
  exit 0
fi

# Split Areas:/Migrations:/Extra lens: out of the prose; Areas: may continue on
# the following lines until a blank line, another key, or a bullet.
printf '%s\n' "$body" | awk -v src="$source_name" '
  function toks(s,   n, a, i, out) {
    gsub(/,/, " ", s); n = split(s, a, /[ \t]+/); out = ""
    for (i = 1; i <= n; i++) if (a[i] != "") out = out (out == "" ? "" : " ") a[i]
    return out
  }
  /^Areas:/ { inareas = 1; v = $0; sub(/^Areas:[ \t]*/, "", v); areas = areas " " toks(v); next }
  /^Migrations:/ { inareas = 0; v = $0; sub(/^Migrations:[ \t]*/, "", v); mig = mig " " toks(v); next }
  /^Extra lens:/ { inareas = 0; v = $0; sub(/^Extra lens:[ \t]*/, "", v); split(v, p, /[ \t]+/); lens = p[1]; next }
  inareas && $0 !~ /^[ \t]*$/ && $0 !~ /^[-*][ \t]/ { areas = areas " " toks($0); next }
  { inareas = 0; rest[++n] = $0 }
  END {
    print "focus: " src
    gsub(/^ +/, "", areas); gsub(/^ +/, "", mig)
    if (areas != "") print "areas: " areas
    if (mig != "") print "migrations: " mig
    if (lens != "") print "extra-lens: " lens
    print "---"
    s = 1; while (s <= n && rest[s] ~ /^[ \t]*$/) s++
    e = n; while (e >= s && rest[e] ~ /^[ \t]*$/) e--
    for (i = s; i <= e; i++) print rest[i]
    if (e - s + 1 > 40) print "load-focus: section is " (e - s + 1) " lines (over 40); passed whole" > "/dev/stderr"
  }
'
