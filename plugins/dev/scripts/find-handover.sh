#!/usr/bin/env bash
# Usage: find-handover.sh [--no-fetch]
# Locates this repo's latest handover for /dev:takeover and prints tab-separated
# lines, first field the tag:
#   KEY <repo-key>   ROOT <main repo root>   ORIGIN <owner/repo, normalized>
#   LOCAL <path>                       newest state file (stops the search)
#   BRANCH <ref> <date> <doc path> <task line>   branch-carried, newest first
#   ARCHIVE <path>                     newest archived handover (last resort)
#   NONE                               nothing anywhere
# Reads only; the one write is `git fetch` of handover/* branches (skip: --no-fetch).
set -euo pipefail

fetch=1
[[ "${1:-}" == "--no-fetch" ]] && fetch=0

state="$HOME/.claude/state"
# shellcheck source=repo-key.sh
. "$(dirname "${BASH_SOURCE[0]}")/repo-key.sh"
repo_key_resolve
root=$REPO_ROOT key=$REPO_KEY
printf 'KEY\t%s\nROOT\t%s\n' "$key" "$root"

# git runs against the main root: a jj workspace has no .git of its own.
origin=""
if [[ -n "$root" ]]; then
  url=$(git -C "$root" ls-remote --get-url origin 2>/dev/null || true)
  # git echoes the remote name back when it has no URL.
  if [[ -n "$url" && "$url" != "origin" ]]; then
    origin=$(printf '%s' "$url" | sed -E 's#/+$##; s#\.git$##; s#^.*[:/]([^:/]+/[^:/]+)$#\1#')
  fi
fi
printf 'ORIGIN\t%s\n' "$origin"

# <key>-*.md also matches a repo whose key extends this one (`proj-x.md` for
# `proj`). A Repo: line decides: keep the file only if it names this repo.
# With none, or outside a repo where no sibling key exists, the name decides:
# every <key>-* name this repo writes ends in a UTC stamp, which rules out the
# other repo's plain handover, and takeover's Repo check warns on the rest. A
# bare <key>-<ts>.md (/dev:handover's archive of <key>.md) is this repo's
# whatever its Repo: says.
ts='[0-9]{8}T[0-9]{6}Z'
ours() {
  local rest=${1##*/}
  rest=${rest#"$key"-}
  [[ "$rest" =~ ^$ts\.md$ ]] && return 0
  if [[ -n "$root" && -n "$(handover_repo "$1")" ]]; then
    repo_owns_handover "$1"
  else
    [[ "$rest" =~ ^.+-$ts\.md$ ]]
  fi
}

# Newest state file: <key>.md plus the per-respawn <key>-<slug>-<ts>.md files.
shopt -s nullglob
existing=()
[[ -f "$state/handover/$key.md" ]] && existing+=("$state/handover/$key.md")
for f in "$state/handover/$key"-*.md; do ours "$f" && existing+=("$f"); done
if ((${#existing[@]})); then
  printf 'LOCAL\t%s\n' "$(ls -t "${existing[@]}" | awk 'NR==1')"
  exit 0
fi

if [[ -n "$origin" ]]; then
  if ((fetch)); then
    git -C "$root" fetch origin '+refs/heads/handover/*:refs/remotes/origin/handover/*' >/dev/null 2>&1 || true
  fi
  found=0
  while IFS=$'\t' read -r ref date; do
    [[ -n "$ref" ]] || continue
    found=1
    doc=$(git -C "$root" ls-tree -r --name-only "$ref" -- docs/handovers/ | awk 'NR==1' || true)
    task=""
    if [[ -n "$doc" ]]; then
      task=$(git -C "$root" show "$ref:$doc" | awk '/^## Task & goal/{f=1;next} f&&NF{print;exit}' || true)
    fi
    printf 'BRANCH\t%s\t%s\t%s\t%s\n' "$ref" "$date" "${doc:--}" "$task"
  done < <(git -C "$root" for-each-ref --sort=-committerdate \
             --format='%(refname:short)%09%(committerdate:iso8601)' refs/remotes/origin/handover/)
  if ((found)); then exit 0; fi
fi

# Archives are <key>-<ts>.md (/dev:handover) and <key>-<slug>-<ts>-<ts>.md (the
# respawn sweep).
archived=()
for f in "$state/handover-archive/$key"-*.md; do ours "$f" && archived+=("$f"); done
if ((${#archived[@]})); then
  # Newest by mtime, as LOCAL (mv keeps it); names sort by slug before stamp.
  printf 'ARCHIVE\t%s\n' "$(ls -t "${archived[@]}" | awk 'NR==1')"
  exit 0
fi
echo NONE
