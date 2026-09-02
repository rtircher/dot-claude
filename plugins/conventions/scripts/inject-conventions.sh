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
# wrapped in one. The hook's stdin JSON ({hook_event_name, agent_id, agent_type})
# gates who gets it: agents not in SUBAGENT_ALLOWLIST get empty stdout.
#
# ${CLAUDE_PLUGIN_ROOT} is the plugin's install dir; plugins run from a cache
# location, so relative paths would not resolve.
set -euo pipefail

# Only agents that write or judge code get the subset; the ~3.4k tokens per dispatch
# are wasted on Explore, Plan, lens reviewers and the like. Plugin agents are listed
# in both the qualified (dev:coder) and bare (coder) spellings.
SUBAGENT_ALLOWLIST="general-purpose dev:coder coder dev:researcher researcher dev:reviewer reviewer"

conventions="${CLAUDE_PLUGIN_ROOT}/conventions.md"
if [ ! -f "$conventions" ]; then
  # Don't hard-fail the hook if the plugin cache is incomplete: warn on stderr
  # (not injected) and exit clean so the session still starts.
  echo "WARN: conventions.md not found at ${conventions}; conventions not injected." >&2
  exit 0
fi

subagent=0
[ "${1:-}" = "--subagent" ] && subagent=1

if [ "$subagent" = 1 ]; then
  # Missing or malformed stdin yields an empty type, which no allowlist entry matches.
  agent_type=$(python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("agent_type", ""))
except Exception:
    pass' 2>/dev/null || true)
  allowed=0
  for t in $SUBAGENT_ALLOWLIST; do
    if [ "$t" = "$agent_type" ]; then
      allowed=1
    fi
  done
  if [ "$allowed" = 0 ]; then
    exit 0
  fi
fi

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
