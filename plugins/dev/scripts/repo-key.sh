#!/usr/bin/env bash
# Usage: repo-key.sh            prints KEY <repo-key> and ROOT <main repo root>
#        . repo-key.sh; repo_key_resolve   sets REPO_KEY and REPO_ROOT
# The handover key is the basename of the MAIN repo, so every git worktree and
# jj workspace of a project shares one handover. A jj workspace has no .git (git
# fails there), so its main repo comes from the .jj/repo pointer file instead.
# Outside any repo: KEY default, ROOT empty. Reads only; never runs jj.
# Also defines handover_repo and repo_owns_handover for the scripts that source it.

repo_key_resolve() {
  REPO_ROOT="" REPO_KEY=default
  local dir ptr common
  dir=$(pwd -P 2>/dev/null) || return 0
  # Nearest marker wins, so a git worktree nested inside a jj checkout still
  # resolves through git.
  while [[ "$dir" == /?* ]]; do
    [[ -e "$dir/.git" ]] && break
    if [[ -f "$dir/.jj/repo" ]]; then
      # Secondary workspace: the pointer names <main>/.jj/repo, relative to .jj/.
      # A dangling pointer stays `default`; git would only find an unrelated
      # repo further up.
      ptr=$(<"$dir/.jj/repo")
      [[ "$ptr" == /* ]] || ptr="$dir/.jj/$ptr"
      REPO_ROOT=$(cd "$(dirname "$ptr")/.." 2>/dev/null && pwd -P) || { REPO_ROOT=""; return 0; }
      break
    fi
    if [[ -d "$dir/.jj/repo" ]]; then
      # Main jj checkout without .git (not colocated).
      REPO_ROOT=$dir
      break
    fi
    dir=$(dirname "$dir")
  done
  if [[ -z "$REPO_ROOT" ]]; then
    common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
    REPO_ROOT=$(dirname "$common")
  fi
  REPO_KEY=$(basename "$REPO_ROOT")
}

# handover_repo <file>: prints the file's `Repo:` value, empty when it has none.
handover_repo() { awk '/^Repo: /{sub(/^Repo: /,""); print; exit}' "$1"; }

# repo_owns_handover <file>: true when the file's `Repo:` line names REPO_ROOT.
# A <key>-*.md name can belong to a repo whose key extends this one (`dot` vs
# `dot-files`); only the Repo: line tells them apart. Hand-written Repo: lines
# sometimes carry trailing notes after the path.
repo_owns_handover() {
  local repo
  repo=$(handover_repo "$1")
  [[ -n "$REPO_ROOT" && ("$repo" == "$REPO_ROOT" || "$repo" == "$REPO_ROOT "*) ]]
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  repo_key_resolve
  printf 'KEY\t%s\nROOT\t%s\n' "$REPO_KEY" "$REPO_ROOT"
fi
