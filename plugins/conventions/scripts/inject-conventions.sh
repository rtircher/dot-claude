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

cat "${CLAUDE_PLUGIN_ROOT}/conventions.md"
