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

# shellcheck source=repo-key.sh
. "$(dirname "${BASH_SOURCE[0]}")/repo-key.sh"
repo_key_resolve
[[ -n "$REPO_ROOT" ]] || { echo "handover-archive-sweep: not in a repo" >&2; exit 2; }
root=$REPO_ROOT key=$REPO_KEY

state="$HOME/.claude/state"
mkdir -p "$state/handover" "$state/handover-archive"

# One listing instead of a per-file branch lookup. Against the main root: a jj
# workspace has no .git, and a colocated repo exports its bookmarks there.
branches=$(git -C "$root" for-each-ref --format='%(refname:short)' refs/heads)

shopt -s nullglob
moved=0 kept=0 other=0
for f in "$state/handover/$key"-*.md; do
  if ! repo_owns_handover "$f"; then other=$((other + 1)); continue; fi
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
