#!/usr/bin/env bash
#
# Prints conventions.md for Claude Code to inject as context.
#
# Claude Code keeps at most 10,000 characters of one hook's output in context
# (past that the model gets a 2KB preview and a file path), so the main session's
# text is split across two SessionStart hook calls, each under the cap:
#
# SessionStart (no args): the file minus the `main-session-only` region, as plain
# stdout. Marker lines are never printed.
#
# SessionStart (--orchestration): only the `main-session-only` region (model
# routing, delegation), under a heading of its own.
#
# SubagentStart (--subagent): the same text as no args, since subagents never get
# the orchestration region. Subagent hooks only take context through the JSON
# hookSpecificOutput envelope, so the text is wrapped in one. Which agents get it
# is decided in hooks.json: the SubagentStart entry's `matcher` is a regex over
# `agent_type`, so this script never sees a dispatch for an unmatched agent and
# emits the envelope unconditionally.
#
# Per-user opt-out: with DOT_CLAUDE_CONVENTIONS_SKIP_GIT=1 (settings.json `env`
# reaches hooks), the `git-workflow` region is dropped from both injections, for
# users whose own instructions already cover branch, push and commit rules.
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

mode="${1:-}"
case "$mode" in
  ""|--subagent|--orchestration) ;;
  *) echo "usage: $0 [--subagent|--orchestration]" >&2; exit 2 ;;
esac
orchestration=0
[ "$mode" = "--orchestration" ] && orchestration=1

skip_git=0
[ "${DOT_CLAUDE_CONVENTIONS_SKIP_GIT:-}" = "1" ] && skip_git=1

filter() {
  awk -v orchestration="$orchestration" -v skip_git="$skip_git" '
    BEGIN {
      if (orchestration) {
        print "# Working conventions: orchestration (main session only)"
        print ""
        print "## Model selection, continued"
        print ""
      }
    }
    /^<!-- main-session-only: start -->$/ { in_region = 1; next }
    /^<!-- main-session-only: end -->$/   { in_region = 0; next }
    /^<!-- git-workflow: start -->$/      { in_git = 1; next }
    /^<!-- git-workflow: end -->$/        { in_git = 0; next }
    in_region != orchestration            { next }
    in_git && skip_git                    { next }
    { print }
  ' "$conventions"
}

if [ "$mode" = "--subagent" ]; then
  filter | python3 -c 'import json, sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": sys.stdin.read()}}))'
else
  filter
fi
