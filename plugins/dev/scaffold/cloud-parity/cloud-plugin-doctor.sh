#!/usr/bin/env bash
#
# cloud-plugin-doctor: report whether the marketplace plugins this repo relies on
# are actually present/loadable in the current session. Driven by the same
# scripts/cloud-parity-recipes file ensure-plugins.sh uses, so the check list never
# hardcodes a plugin set. Informational only: always exits 0.

set -uo pipefail

claude_dir="${HOME:-}/.claude/plugins"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
recipes="$repo_root/scripts/cloud-parity-recipes"

found() { [ -d "$claude_dir" ] && [ -n "$(find "$claude_dir" -maxdepth 8 -path "$1" -type f -print 2>/dev/null | head -1)" ]; }
marketplace_glob() { printf '*%s*' "${1##*/}"; }
install_glob() { printf '*%s*%s*' "${1#*@}" "${1%@*}"; }
# Mirror of ensure-plugins.sh: reject a recipe arg with a glob metachar before it
# reaches a find -path glob, so the doctor's verdict agrees with what gets cloned.
valid_token() { case "$1" in ''|*[!A-Za-z0-9._/@-]*) return 1 ;; *) return 0 ;; esac; }

missing=0
check() { if found "$2"; then printf "  [ok]      %s\n" "$1"; else printf "  [MISSING] %s\n" "$1"; missing=$((missing + 1)); fi; }

echo "== cloud-plugin-doctor =="
echo

echo "Environment (the facts the plugin pre-warm depends on):"
printf "  whoami = %s\n" "$(whoami)"
printf "  HOME   = %s\n" "${HOME:-<unset>}"
claude_bin="$(command -v claude || true)"
if [ -n "$claude_bin" ]; then
  printf "  claude = %s (%s)\n" "$claude_bin" "$(claude --version 2>/dev/null | head -1)"
else
  printf "  claude = MISSING from PATH\n"
fi
echo

if [ ! -f "$recipes" ]; then
  echo "No recipe file ($recipes): this repo declares no cloud plugins. Nothing to check."
  exit 0
fi

echo "Plugin clones on disk (under $claude_dir), from $recipes:"
while read -r verb arg _rest || [ -n "$verb" ]; do
  case "$verb" in
    ''|\#*) continue ;;
    marketplace-add)
      valid_token "$arg" || { echo "  [warn] skipping recipe with invalid token '$arg'"; continue; }
      check "marketplace $arg" "$(marketplace_glob "$arg")"
      # Paired with session-start.sh's conventions backstop, which keys off the same
      # conventions.md path; keep both in sync if the conventions plugin moves it.
      case "$arg" in
        */dot-claude) check "conventions.md (conventions hook can fire; backstop stays silent)" '*conventions*conventions.md' ;;
      esac
      ;;
    install)
      valid_token "$arg" || { echo "  [warn] skipping recipe with invalid token '$arg'"; continue; }
      check "external $arg" "$(install_glob "$arg")" ;;
  esac
done < "$recipes"
echo

if [ -n "$claude_bin" ]; then
  echo "claude plugin list (authoritative enabled/disabled view):"
  claude plugin list 2>/dev/null | sed 's/^/  /' || echo "  (claude plugin list failed)"
else
  echo "claude plugin list: skipped (claude not on PATH)"
fi
echo

if [ "$missing" = 0 ]; then
  echo "Verdict: all expected plugin clones are present. If a skill is still missing"
  echo "         it's an enablement issue, not a missing clone; check the list above."
else
  echo "Verdict: one or more clones are MISSING. The SessionStart hook runs"
  echo "         scripts/ensure-plugins.sh (detached) to re-fetch them in-session;"
  echo "         check \$TMPDIR/plugin-prewarm.log. On a cold cloud session, also"
  echo "         confirm the setup script was pasted into the environment."
fi
