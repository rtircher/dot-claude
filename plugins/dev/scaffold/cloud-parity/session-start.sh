#!/usr/bin/env bash
#
# SessionStart hook: inject a short repo pulse, ensure the pre-commit hook is wired,
# back-stop the conventions plugin if it didn't load, and detach the plugin rescue.
# Hook stdout is added to Claude's context as additionalContext. Wired via
# .claude/settings.json -> hooks.SessionStart. Failures are swallowed so a broken
# hook never blocks a session. Byte-identical across repos.

set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Ensure the pre-commit hook is active when the repo ships one. core.hooksPath is
# shared across worktrees (it lives in the common .git/config), so this is a no-op
# once set, but it guarantees a fresh clone is covered without a manual install.
if [ -x "$repo_root/scripts/git-hooks/pre-commit" ] \
   && [ -z "$(git -C "$repo_root" config --get core.hooksPath 2>/dev/null)" ]; then
  git -C "$repo_root" config core.hooksPath scripts/git-hooks 2>/dev/null || true
fi

branch=$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
status=$(git -C "$repo_root" status --short 2>/dev/null | head -20)
recent=$(git -C "$repo_root" log -5 --oneline --no-decorate 2>/dev/null)
worktrees=$(git -C "$repo_root" worktree list 2>/dev/null | tail -n +2)

printf "## Repo pulse\n\n"
printf "Branch: \`%s\`\n\n" "$branch"
if [ -n "$status" ]; then
  printf "Working tree (truncated to 20):\n\`\`\`\n%s\n\`\`\`\n\n" "$status"
else
  printf "Working tree: clean\n\n"
fi
if [ -n "$recent" ]; then
  printf "Recent commits:\n\`\`\`\n%s\n\`\`\`\n\n" "$recent"
fi
if [ -n "$worktrees" ]; then
  printf "Other worktrees:\n\`\`\`\n%s\n\`\`\`\n" "$worktrees"
fi

# Conventions backstop. The shared conventions normally arrive via the
# conventions@dot-claude plugin's own SessionStart hook. In cloud, that plugin's
# clone can land after the session's hook-registration snapshot, so the plugin hook
# never fires and the session would silently run without the conventions. Emit a
# pointer plus the few cross-project bits ONLY when the plugin's conventions.md is
# absent on disk (so we never double-inject when the plugin did load). File-level
# detection for the repo target: point to AGENTS.md when the repo ships one.
conv_present=""
if [ -d "${HOME:-}/.claude/plugins" ]; then
  conv_present=$(find "${HOME}/.claude/plugins" -maxdepth 8 -name conventions.md -path '*conventions*' 2>/dev/null | head -1)
fi
if [ -z "$conv_present" ]; then
  printf "\n## Conventions backstop (conventions plugin not loaded)\n\n"
  if [ -f "$repo_root/AGENTS.md" ]; then
    printf "The shared conventions plugin isn't on disk this session, so its SessionStart injection won't fire. **Read AGENTS.md for this repo's working practices** (always present in the clone).\n\n"
  else
    printf "The shared conventions plugin isn't on disk this session, so its SessionStart injection won't fire.\n\n"
  fi
  printf "Cross-project reminders that live only in the plugin:\n"
  printf -- "- Refer to models by unversioned alias (\`opus\`/\`sonnet\`/\`haiku\`), never a version-pinned id; pick the model per task.\n"
  printf -- "- Pin language runtimes/tools via a committed \`.mise.toml\` (single source of truth for local dev, CI, and cloud setup).\n"
  printf -- "- TDD-first; adversarial review before committing; never push or commit to main without explicit approval.\n"
fi

prewarm_log="${TMPDIR:-/tmp}/plugin-prewarm.log"

# Surface a prior detached rescue's failures. ensure-plugins.sh runs detached with its
# output only in $prewarm_log, so a fully-failed prewarm (e.g. github unreachable)
# otherwise leaves the session with no in-context signal. Read the PRIOR run's log here,
# before the rescue below overwrites it. Best-effort; never blocks the session.
if [ -f "$prewarm_log" ] && grep -q "failed" "$prewarm_log" 2>/dev/null; then
  printf "\n## Cloud-parity prewarm had failures\n\n"
  printf "The previous session's plugin rescue logged a failure, so some marketplace/plugin clones may be missing. See \`%s\`, or run \`scripts/cloud-plugin-doctor.sh\`.\n\n" "$prewarm_log"
fi

# Plugin pre-warm rescue. The setup-script pre-warm only runs if claude is on PATH at
# setup time, which it is NOT in some cloud environments. Re-attempt the clones in-
# session via the recipe-driven ensure-plugins.sh (idempotent; logs to a file, never
# our stdout). Run DETACHED so it never blocks session start; setsid gives it a real
# new session that survives a process-group teardown mid-fetch, with a nohup fallback.
if command -v claude >/dev/null 2>&1 && [ -x "$repo_root/scripts/ensure-plugins.sh" ]; then
  if command -v setsid >/dev/null 2>&1; then
    setsid -f bash "$repo_root/scripts/ensure-plugins.sh" </dev/null >"$prewarm_log" 2>&1 || true
  else
    ( nohup bash "$repo_root/scripts/ensure-plugins.sh" </dev/null >"$prewarm_log" 2>&1 & ) 2>/dev/null || true
  fi
fi
