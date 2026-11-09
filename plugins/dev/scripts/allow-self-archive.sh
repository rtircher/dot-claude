#!/usr/bin/env bash
# PreToolUse hook for mcp__ccd_session_mgmt__archive_session: allow a session
# to archive itself (/dev:done is the consent); archiving any other session falls
# through to the normal permission flow. A bare allow rule can't match on
# session_id, so it would cover other sessions too.
set -euo pipefail

sid=$(jq -r '.tool_input.session_id // ""' 2>/dev/null) || sid=""

if [[ "$sid" == "self" ]]; then
  jq -cn '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",permissionDecisionReason:"session archiving itself (/dev:done)"}}'
fi
exit 0
