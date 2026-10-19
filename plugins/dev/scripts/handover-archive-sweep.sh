#!/usr/bin/env bash
# Usage: handover-archive-sweep.sh [--dry-run]
# Archives already-consumed per-respawn handovers for the current repo: each
# ~/.claude/state/handover/<repo-key>-*.md whose `Branch:` already exists as a
# branch (that respawn has forked) moves to
# ~/.claude/state/handover-archive/<name>-<UTC ts>.md. Handovers whose branch is
# not there yet are still pending and stay. The shared <repo-key>.md slot belongs
# to /dev:handover and is never touched. --dry-run prints what would move.
set -euo pipefail

dry=0
[[ "${1:-}" == "--dry-run" ]] && dry=1

common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) \
  || { echo "handover-archive-sweep: not in a git repo" >&2; exit 2; }
root=$(dirname "$common")
key=$(basename "$root")

state="$HOME/.claude/state"
mkdir -p "$state/handover" "$state/handover-archive"

# One listing instead of a per-file branch lookup.
branches=$(git for-each-ref --format='%(refname:short)' refs/heads)

shopt -s nullglob
moved=0 kept=0 other=0
for f in "$state/handover/$key"-*.md; do
  # The prefix can belong to another repo (`dot` vs `dot-files`): match Repo:.
  repo=$(awk '/^Repo: /{sub(/^Repo: /,""); print; exit}' "$f")
  # Hand-written Repo: lines sometimes carry trailing notes after the path.
  if [[ "$repo" != "$root" && "$repo" != "$root "* ]]; then other=$((other + 1)); continue; fi
  branch=$(awk '/^Branch: /{sub(/^Branch: /,""); print; exit}' "$f")
  if [[ -n "$branch" ]] && grep -Fxq -- "$branch" <<<"$branches"; then
    dest="$state/handover-archive/$(basename "$f" .md)-$(date -u +%Y%m%dT%H%M%SZ).md"
    if ((dry)); then
      echo "would archive: $f -> $dest (branch $branch exists)"
    else
      mv -n -- "$f" "$dest"
      echo "archived: $f -> $dest"
    fi
    moved=$((moved + 1))
  else
    kept=$((kept + 1))
  fi
done
mode=""
if ((dry)); then mode=" (dry run)"; fi
echo "repo=$key archived=$moved pending=$kept other-repo=$other$mode"
