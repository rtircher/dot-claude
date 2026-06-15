#!/usr/bin/env bash
#
# SessionStart hook: print personal working-style conventions to stdout, which
# Claude Code injects into every session's context (local AND cloud sessions).
#
# Confirmed behavior (docs/en/hooks): "Any text your hook script prints to
# stdout is added as context for Claude." No JSON envelope needed for a hook
# that only loads context.
#
# ${CLAUDE_PLUGIN_ROOT} is the plugin's install dir — required because plugins
# run from a cache location, so relative paths would not resolve.
set -euo pipefail

conventions="${CLAUDE_PLUGIN_ROOT}/conventions.md"
if [ -f "$conventions" ]; then
  cat "$conventions"
else
  # Don't hard-fail SessionStart if the plugin cache is incomplete — warn on
  # stderr (not injected) and exit clean so the session still starts.
  echo "WARN: conventions.md not found at ${conventions}; conventions not injected." >&2
fi
