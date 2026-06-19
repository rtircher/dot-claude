#!/usr/bin/env bash
#
# Claude Code on the web: environment setup script (generic, repo-agnostic).
#
# WHERE THIS RUNS: paste the contents into the "Setup script" field of the cloud
# environment at https://claude.ai/code. It is NOT auto-run from the repo; it lives
# here only so the script is versioned and reviewable. It runs ONCE as root on a
# fresh Ubuntu sandbox before Claude Code launches, and the result is cached.
#
# This script is byte-identical across every repo that uses the cloud-parity seed.
# It does two repo-agnostic things: fix apt so toolchain installs can run, and
# pre-warm the dot-claude marketplace CLONE (no install, no enable). Userspace
# repo-specific work (the plugin set, superpowers, a mise toolchain) is handled
# in-session by the committed seed (session-start.sh -> ensure-plugins.sh), the most
# reliable place: a fresh session re-clones the repo, so committed files are always
# present, whereas this setup phase is best-effort and cached. Repo-specific work
# that needs ROOT at container-build time (apt system packages, a native build
# toolchain) can't run in those non-root in-session hooks, so it lives in an
# OPTIONAL committed scripts/cloud-setup-local.sh that this script calls (step 3).

set -euo pipefail

echo "==> cloud-parity setup starting"

# 1. System deps the toolchain needs on a minimal Ubuntu image. The base image
#    pre-adds third-party PPAs (deadsnakes, ondrej/php) whose host is off the
#    Trusted network tier and returns HTTP 403, so apt-get update reports a partial
#    failure (exit 100). Disable those PPAs first, and keep update/install non-fatal
#    so a flaky repo can't abort the script (under set -e). A genuinely missing
#    package surfaces at its real use, not here.
rm -f /etc/apt/sources.list.d/*deadsnakes* \
      /etc/apt/sources.list.d/*ondrej* 2>/dev/null || true
apt-get update -y || echo "WARN: apt-get update had partial failures (unreachable pre-baked PPAs); continuing"
apt-get install -y --no-install-recommends git curl unzip xz-utils ca-certificates \
  || echo "WARN: apt-get install had failures; continuing (a real miss surfaces in a later step)"

# 2. Pre-warm the dot-claude marketplace CLONE so it is on disk before the session's
#    skill/hook registration snapshot. We add the marketplace (a harmless clone); we
#    do NOT install: install writes a user-scope global enable into
#    ~/.claude/settings.json, leaking plugins into every other repo on this cached
#    image. The repo's project-scope enabledPlugins does the enabling. Repo-specific
#    plugins (e.g. external superpowers) are fetched in-session by ensure-plugins.sh
#    from the repo's recipe list, so they never leak here.
claude_bin="$(command -v claude || true)"
echo "==> plugin pre-warm: whoami=$(whoami) HOME=${HOME:-?} claude=${claude_bin:-MISSING}"
if [ -n "${claude_bin}" ]; then
  # </dev/null: fail closed instead of hanging on a future interactive trust prompt
  # (there is no --yes flag). timeout: bound a slow cold github clone.
  timeout 180 claude plugin marketplace add rtircher/dot-claude </dev/null \
    || echo "WARN: 'marketplace add rtircher/dot-claude' failed; the in-session hook will retry"
  echo "==> marketplaces on disk after pre-warm:"
  ls -1 "${HOME:-}/.claude/plugins/marketplaces" 2>/dev/null | sed 's/^/  marketplace: /' || echo "  (no marketplaces dir)"
else
  echo "==> 'claude' not on PATH at setup time; skipping pre-warm (the in-session hook will clone)"
fi

# 3. Repo-specific root setup. Work that needs root at container-build time (apt
#    system packages, a native build toolchain, frozen installs) CAN'T run in the
#    non-root in-session hooks, so a repo puts it in an OPTIONAL committed script.
#    This is the setup-time, root, once-cached counterpart to the in-session
#    ensure-<tool>.sh convention. The repo is already checked out at $PWD here (the
#    setup phase runs in the repo root), so a present hook is run by path. A repo
#    that needs nothing ships none. Not guarded with `|| true`: a real failure in
#    repo setup (e.g. a missing apt package) should fail loudly, not cache a broken
#    image; the hook marks its own best-effort steps.
repo_setup="${PWD}/scripts/cloud-setup-local.sh"
if [ -f "${repo_setup}" ]; then
  echo "==> running repo-specific setup: scripts/cloud-setup-local.sh"
  bash "${repo_setup}"
else
  echo "==> no scripts/cloud-setup-local.sh; nothing repo-specific to install"
fi

echo "==> cloud-parity setup complete"
