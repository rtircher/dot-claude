#!/usr/bin/env bash
#
# ensure-plugins: in-session clone of the marketplace plugins this repo needs, the
# fallback for when the setup-script pre-warm didn't land them. Run DETACHED from the
# SessionStart hook (which explains when that happens); the harness lazy-registers a
# plugin mid-session once its clone lands.
#
# The plugin set is data, not code: it reads scripts/cloud-parity-recipes (one
# recipe per line), so this script is byte-identical across repos and a repo that
# wants nothing simply ships no recipe file. Idempotent and concurrency-safe without
# a lock: each recipe runs only when its clone is absent, and claude's marketplace
# add / install are themselves idempotent.

set -uo pipefail

command -v claude >/dev/null 2>&1 || exit 0
plugins_dir="${HOME:-}/.claude/plugins"
[ -d "$plugins_dir" ] || exit 0

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
recipes="$repo_root/scripts/cloud-parity-recipes"
[ -f "$recipes" ] || { echo "ensure-plugins: no recipe file ($recipes); nothing to do"; exit 0; }

# present <path-glob>: true only if a clone matching the glob holds at least one
# regular file. An interrupted clone leaves a bare directory; treating that as
# present would skip the retry forever. Capture the value rather than test the
# pipeline exit (head closing the pipe makes find's SIGPIPE non-zero under pipefail).
present() {
  local hit
  hit="$(find "$plugins_dir" -maxdepth 8 -path "$1" -type f -print 2>/dev/null | head -1 || true)"
  [ -n "$hit" ]
}

# tmo <seconds> <cmd...>: bound a slow/hung cold clone with timeout when present;
# run directly otherwise, so a missing timeout never skips the command.
tmo() {
  if command -v timeout >/dev/null 2>&1; then timeout "$1" "${@:2}"; else "${@:2}"; fi
}

# Globs that locate a clone on disk from a recipe argument. These are loose substring
# matches against the real layout (cache/<repo-or-market>/<plugin>/...); distinct
# plugin/marketplace names never collide, but a name that is a substring of another
# would (acceptable for the author's known set).
marketplace_glob() { printf '*%s*' "${1##*/}"; }                     # owner/repo -> *repo*
install_glob() { printf '*%s*%s*' "${1#*@}" "${1%@*}"; }             # plugin@market -> *market*plugin*

while read -r verb arg _rest || [ -n "$verb" ]; do
  case "$verb" in
    ''|\#*) continue ;;
    marketplace-add)
      present "$(marketplace_glob "$arg")" && continue
      echo "ensure-plugins: marketplace $arg absent; adding"
      tmo 180 claude plugin marketplace add "$arg" </dev/null \
        || echo "ensure-plugins: 'marketplace add $arg' failed"
      ;;
    install)
      present "$(install_glob "$arg")" && continue
      market="${arg#*@}"
      echo "ensure-plugins: $arg absent; updating $market index then installing"
      tmo 120 claude plugin marketplace update "$market" </dev/null \
        || echo "ensure-plugins: 'marketplace update $market' failed"
      tmo 180 claude plugin install "$arg" </dev/null \
        || echo "ensure-plugins: 'install $arg' failed"
      ;;
    *)
      echo "ensure-plugins: unknown recipe verb '$verb' (line: $verb $arg)" ;;
  esac
done < "$recipes"

echo "ensure-plugins: done"
