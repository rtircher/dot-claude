#!/usr/bin/env bash
#
# Prints conventions.md for Claude Code to inject as context.
#
# SessionStart (no args): the whole file as plain stdout, which Claude Code adds
# to the main session's context. Marker lines are never printed.
#
# SubagentStart (--subagent): the file minus the `main-session-only` region
# (model routing, delegation), which only the orchestrator uses. Subagent hooks
# only take context through the JSON hookSpecificOutput envelope, so the text is
# wrapped in one. Which agents get it is decided in hooks.json: the SubagentStart
# entry's `matcher` is a regex over `agent_type`, so this script never sees a
# dispatch for an unmatched agent and emits the envelope unconditionally.
#
# ${CLAUDE_PLUGIN_ROOT} is the plugin's install dir; plugins run from a cache
# location, so relative paths would not resolve.
set -euo pipefail

conventions="${CLAUDE_PLUGIN_ROOT}/conventions.md"
if [ ! -f "$conventions" ]; then
  # Don't hard-fail the hook if the plugin cache is incomplete: warn on stderr
  # (not injected) and exit clean so the session still starts.
  echo "WARN: conventions.md not found at ${conventions}; conventions not injected." >&2
  exit 0
fi

subagent=0
[ "${1:-}" = "--subagent" ] && subagent=1

filter() {
  awk -v skip_region="$subagent" '
    /^<!-- main-session-only: start -->$/ { in_region = 1; next }
    /^<!-- main-session-only: end -->$/   { in_region = 0; next }
    in_region && skip_region              { next }
    { print }
  ' "$conventions"
}

if [ "$subagent" = 1 ]; then
  filter | python3 -c 'import json, sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": sys.stdin.read()}}))'
else
  filter
fi
