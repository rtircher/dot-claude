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
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [[ -n "$common" ]]; then
  root=$(dirname "$common")
  key=$(basename "$root")
else
  root=""
  key=default
fi
printf 'KEY\t%s\nROOT\t%s\n' "$key" "$root"

origin=""
if [[ -n "$common" ]]; then
  url=$(git ls-remote --get-url origin 2>/dev/null || true)
  # git echoes the remote name back when it has no URL.
  if [[ -n "$url" && "$url" != "origin" ]]; then
    origin=$(printf '%s' "$url" | sed -E 's#/+$##; s#\.git$##; s#^.*[:/]([^:/]+/[^:/]+)$#\1#')
  fi
fi
printf 'ORIGIN\t%s\n' "$origin"

# Newest state file: <key>.md plus the per-respawn <key>-*.md files.
shopt -s nullglob
local_files=("$state/handover/$key.md" "$state/handover/$key"-*.md)
existing=()
for f in "${local_files[@]}"; do [[ -f "$f" ]] && existing+=("$f"); done
if ((${#existing[@]})); then
  printf 'LOCAL\t%s\n' "$(ls -t "${existing[@]}" | awk 'NR==1')"
  exit 0
fi

if [[ -n "$origin" ]]; then
  if ((fetch)); then
    git fetch origin '+refs/heads/handover/*:refs/remotes/origin/handover/*' >/dev/null 2>&1 || true
  fi
  found=0
  while IFS=$'\t' read -r ref date; do
    [[ -n "$ref" ]] || continue
    found=1
    doc=$(git ls-tree -r --name-only "$ref" -- docs/handovers/ | awk 'NR==1' || true)
    task=""
    if [[ -n "$doc" ]]; then
      task=$(git show "$ref:$doc" | awk '/^## Task & goal/{f=1;next} f&&NF{print;exit}' || true)
    fi
    printf 'BRANCH\t%s\t%s\t%s\t%s\n' "$ref" "$date" "${doc:--}" "$task"
  done < <(git for-each-ref --sort=-committerdate \
             --format='%(refname:short)%09%(committerdate:iso8601)' refs/remotes/origin/handover/)
  if ((found)); then exit 0; fi
fi

archived=("$state/handover-archive/$key"-*.md)
if ((${#archived[@]})); then
  # Timestamped names sort lexically; the last is newest.
  printf 'ARCHIVE\t%s\n' "$(printf '%s\n' "${archived[@]}" | sort | tail -n 1)"
  exit 0
fi
echo NONE
