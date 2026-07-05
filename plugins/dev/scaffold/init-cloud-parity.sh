#!/usr/bin/env bash
#
# init-cloud-parity: vendor the canonical cloud-parity seed from dot-claude into a
# target repo, and (with --check) verify a repo's vendored copies have not drifted
# from the live canonical seed. Runs LOCALLY (plugins are unreliable in a fresh
# cloud session); standalone bash, no plugin load required.
#
# Usage:
#   init-cloud-parity [TARGET_REPO]          vendor/refresh the seed into TARGET_REPO (default: cwd's git root)
#   init-cloud-parity --check [TARGET_REPO]  report drift vs the live canonical seed + recipe consistency; non-zero exit on drift
#
# The scaffold owns ONLY .claude/settings.json's extraKnownMarketplaces + a
# touch-if-absent SessionStart hook entry; it never edits enabledPlugins,
# permissions, or other hooks. The recipe file and any ensure-<tool>.sh are
# repo-authored: a starter recipe file is written only when absent.
#
# Layout: every cloud-parity artifact lives under .claude/cloud/ (the seed scripts,
# the authored recipe list, and the optional repo hooks). A repo vendored under the
# pre-.claude/cloud layout (scripts/*, .claude/cloud-setup.sh) is moved on its next
# vendor by migrate_legacy; --check flags any leftover.

set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"           # plugins/dev/scaffold
seed_dir="$source_dir/cloud-parity"
CLOUD_DIR=".claude/cloud"
RECIPES_REL="$CLOUD_DIR/cloud-parity-recipes"
HOOK_CMD="$CLOUD_DIR/session-start.sh"
LEGACY_HOOK_CMD="scripts/claude-hooks/session-start.sh"

# Map a canonical seed file to its destination path inside a consumer repo.
declare -a SEED_FILES=(
  "cloud-setup.sh:$CLOUD_DIR/cloud-setup.sh"
  "session-start.sh:$CLOUD_DIR/session-start.sh"
  "ensure-plugins.sh:$CLOUD_DIR/ensure-plugins.sh"
  "cloud-plugin-doctor.sh:$CLOUD_DIR/cloud-plugin-doctor.sh"
)

# Pre-.claude/cloud vendored locations, for one-time migration and --check leftover
# detection. Two classes: seed copies (deleted; re-vendored under $CLOUD_DIR fresh)
# and authored data ("legacy:new", moved to preserve repo-authored content).
declare -a LEGACY_SEED_COPIES=(
  ".claude/cloud-setup.sh"
  "scripts/claude-hooks/session-start.sh"
  "scripts/ensure-plugins.sh"
  "scripts/cloud-plugin-doctor.sh"
)
declare -a LEGACY_AUTHORED=(
  "scripts/cloud-parity-recipes:$RECIPES_REL"
  "scripts/cloud-setup-local.sh:$CLOUD_DIR/cloud-setup-local.sh"
)

die() { echo "init-cloud-parity: $*" >&2; exit 1; }

dot_claude_sha() { git -C "$source_dir" rev-parse HEAD 2>/dev/null || echo "unknown"; }

# stamp_copy <src> <dst> <sha>: copy src to dst, inserting the provenance line. It
# goes on line 2 when line 1 is a shebang (every current seed), else line 1, so a
# future non-shebang seed is never corrupted.
stamp_copy() {
  local src="$1" dst="$2" sha="$3"
  local stamp="# vendored from dot-claude @ ${sha}. Re-sync with /dev:init-cloud-parity; do not edit here"
  mkdir -p "$(dirname "$dst")"
  if head -1 "$src" | grep -q '^#!'; then
    { head -1 "$src"; printf '%s\n' "$stamp"; tail -n +2 "$src"; } > "$dst"
  else
    { printf '%s\n' "$stamp"; cat "$src"; } > "$dst"
  fi
  chmod +x "$dst"
}

# Move a repo off the pre-.claude/cloud layout: authored files are moved (content
# preserved), seed copies are deleted (re-vendored fresh under $CLOUD_DIR). The stale
# SessionStart hook entry is rewritten by merge_settings. Idempotent: a repo already
# on the new layout has no legacy files, so this is a silent no-op.
migrate_legacy() {
  local target="$1" pair legacy new did=0
  mkdir -p "$target/$CLOUD_DIR"
  for pair in "${LEGACY_AUTHORED[@]}"; do
    legacy="$target/${pair%%:*}"; new="$target/${pair#*:}"
    [ -f "$legacy" ] || continue
    if [ -f "$new" ]; then
      rm -f "$legacy"; echo "  migrated: removed legacy ${pair%%:*} (kept existing ${pair#*:})"
    else
      mkdir -p "$(dirname "$new")"; mv "$legacy" "$new"
      echo "  migrated: moved ${pair%%:*} -> ${pair#*:}"
    fi
    did=1
  done
  for legacy in "${LEGACY_SEED_COPIES[@]}"; do
    if [ -f "$target/$legacy" ]; then
      rm -f "$target/$legacy"; echo "  migrated: removed legacy $legacy (re-vendored under $CLOUD_DIR/)"; did=1
    fi
  done
  # Prune the now-empty legacy hook dir; leave scripts/ itself (repos use it).
  rmdir "$target/scripts/claude-hooks" 2>/dev/null || true
  if [ "$did" -eq 1 ]; then echo "  (migrated pre-.claude/cloud layout into $CLOUD_DIR/)"; fi
  return 0
}

vendor() {
  local target="$1" sha; sha="$(dot_claude_sha)"
  local pair src dst
  migrate_legacy "$target"
  for pair in "${SEED_FILES[@]}"; do
    src="$seed_dir/${pair%%:*}"; dst="$target/${pair#*:}"
    [ -f "$src" ] || die "missing canonical seed file: $src"
    stamp_copy "$src" "$dst" "$sha"
    echo "  vendored ${pair#*:}"
  done

  local recipes="$target/$RECIPES_REL"
  if [ -f "$recipes" ]; then
    echo "  kept existing $RECIPES_REL (authored data)"
  else
    mkdir -p "$(dirname "$recipes")"
    cp "$seed_dir/cloud-parity-recipes.template" "$recipes"
    echo "  wrote starter $RECIPES_REL (edit to match this repo's plugins)"
  fi

  merge_settings "$target"
  echo
  echo "Done. Next:"
  echo "  - Edit $RECIPES_REL to list this repo's plugins."
  echo "  - Add matching enabledPlugins entries to .claude/settings.json (the scaffold"
  echo "    does not touch enabledPlugins). Run --check to confirm they agree."
  echo "  - If this repo has a toolchain, add $CLOUD_DIR/ensure-<tool>.sh modeled on"
  echo "    race_engineer's ensure-flutter.sh, wired as a Makefile prerequisite."
  echo "  - Paste $CLOUD_DIR/cloud-setup.sh into the cloud environment's Setup script field."
  echo "  - Set all four of GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL and GIT_COMMITTER_NAME/"
  echo "    GIT_COMMITTER_EMAIL in the cloud environment's env vars so commits are authored"
  echo "    as you, never the harness. Git honors them natively; the SessionStart hook only"
  echo "    warns in the repo pulse when they are missing."
}

merge_settings() {
  local target="$1" tmp
  local f="$target/.claude/settings.json"
  command -v jq >/dev/null 2>&1 || die "jq is required for the settings.json merge"
  mkdir -p "$target/.claude"
  [ -f "$f" ] || echo '{}' > "$f"
  tmp="$(mktemp)"
  # The idempotency guard matches BOTH the nested {hooks:[{command}]} form this
  # scaffold writes and a pre-existing FLAT {matcher,command} form a repo may have
  # hand-authored, so re-runs never double-insert the hook. It also strips a stale
  # legacy-path hook, at per-HOOK granularity: a flat legacy entry is dropped whole,
  # but a nested entry keeps its other hooks and loses only the legacy one (the entry
  # is dropped only if that empties it). A repo hook co-located with the legacy one in
  # the same entry is therefore never destroyed.
  jq --arg hook "$HOOK_CMD" --arg legacy "$LEGACY_HOOK_CMD" '
    .extraKnownMarketplaces = (.extraKnownMarketplaces // {})
    | .extraKnownMarketplaces["dot-claude"] //= {source:{source:"github", repo:"rtircher/dot-claude"}}
    | .hooks = (.hooks // {})
    | .hooks.SessionStart = (.hooks.SessionStart // [])
    | .hooks.SessionStart = [ .hooks.SessionStart[]
        | select(.command? != $legacy)
        | if (.hooks | type) == "array" then .hooks |= map(select(.command? != $legacy)) else . end
        | select(((.hooks | type) != "array") or ((.hooks | length) > 0)) ]
    | if any(.hooks.SessionStart[]?; (.command? == $hook) or (.hooks[]?.command? == $hook))
      then .
      else .hooks.SessionStart += [{hooks:[{type:"command", command:$hook}]}]
      end
  ' "$f" > "$tmp" && mv "$tmp" "$f"
  echo "  merged .claude/settings.json (extraKnownMarketplaces + SessionStart hook)"
}

# Strip the provenance line so it never counts as drift. awk (not BSD-fragile sed):
# drop the first stamp line within the first two (line 2 for a shebang seed, line 1
# for a future non-shebang one, matching stamp_copy); pass everything else through.
strip_stamp() { awk 'NR<=2 && !done && /^# vendored from dot-claude @ /{done=1; next} {print}' "$1"; }

# Network-free drift check: compare each vendored file (stamp stripped) against the
# LIVE canonical seed in this dot-claude checkout. Catches local edits AND a moved
# canonical seed ("re-sync me"); needs no git fetch/show and has no dirty-tree false
# positive (vendor and check read the same $seed_dir). The stamp SHA is informational
# only (reported, not used to fetch).
check_drift() {
  local target="$1" drift=0 pair name dst canon sha
  echo "Checking vendored cloud-parity files in $target against the live seed ($seed_dir)"
  for pair in "${SEED_FILES[@]}"; do
    name="${pair%%:*}"; dst="$target/${pair#*:}"; canon="$seed_dir/$name"
    [ -f "$canon" ] || die "canonical seed missing: $canon (run from a dot-claude checkout / with the dev plugin present)"
    if [ ! -f "$dst" ]; then echo "  [MISSING] ${pair#*:}"; drift=1; continue; fi
    sha="$(sed -n '1,2{s/^# vendored from dot-claude @ \([0-9a-f]*\).*/\1/p;}' "$dst")"
    [ -n "$sha" ] || echo "  [warn]    ${pair#*:} has no provenance stamp"
    if diff -q <(strip_stamp "$dst") "$canon" >/dev/null 2>&1; then
      echo "  [ok]      ${pair#*:}${sha:+  (vendored @ ${sha:0:12})}"
    else
      echo "  [DRIFT]   ${pair#*:} (differs from the current canonical seed; re-run init-cloud-parity to re-sync)"
      drift=1
    fi
  done
  # Flag any pre-.claude/cloud leftover so a half-migrated repo can't pass silently.
  local legacy pair2
  for legacy in "${LEGACY_SEED_COPIES[@]}"; do
    [ -e "$target/$legacy" ] && { echo "  [LEGACY]  $legacy still present (pre-.claude/cloud layout); re-run init-cloud-parity to migrate"; drift=1; }
  done
  for pair2 in "${LEGACY_AUTHORED[@]}"; do
    legacy="${pair2%%:*}"
    [ -e "$target/$legacy" ] && { echo "  [LEGACY]  $legacy still present (pre-.claude/cloud layout); re-run init-cloud-parity to migrate"; drift=1; }
  done
  [ "$drift" -eq 0 ] || { echo "Drift detected. This is a blocking gate."; return 1; }
  echo "No drift vs the canonical seed."
}

# Warn (non-fatal) when an enabledPlugins entry has no clone recipe: that plugin
# would be enabled but never cloned on a cold cloud session (the silent-missing-skill
# failure the design exists to prevent). An entry X@Y is satisfied by 'install X@Y'
# or by 'marketplace-add */Y'.
check_consistency() {
  local target="$1"
  local f="$target/.claude/settings.json" recipes="$target/$RECIPES_REL"
  command -v jq >/dev/null 2>&1 || return 0
  [ -f "$f" ] || return 0
  local recipe_markets="" recipe_installs="" verb arg _rest key market issues=0
  if [ -f "$recipes" ]; then
    while read -r verb arg _rest || [ -n "$verb" ]; do
      case "$verb" in
        marketplace-add) recipe_markets="$recipe_markets ${arg##*/}" ;;
        install) recipe_installs="$recipe_installs $arg" ;;
      esac
    done < "$recipes"
  fi
  echo "Checking enabledPlugins vs recipes:"
  while read -r key; do
    [ -n "$key" ] || continue
    market="${key#*@}"
    case " $recipe_markets " in *" $market "*) continue ;; esac
    case " $recipe_installs " in *" $key "*) continue ;; esac
    echo "  [warn] enabledPlugins '$key' has no matching recipe (marketplace-add */$market or install $key); it may never clone on a cold session"
    issues=$((issues+1))
  done < <(jq -r '(.enabledPlugins // {}) | keys[]' "$f" 2>/dev/null)
  [ "$issues" -eq 0 ] && echo "  [ok] enabledPlugins and recipes agree"
  return 0
}

# --- arg parsing ---
mode="vendor"
if [ "${1:-}" = "--check" ]; then mode="check"; shift; fi
target="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
[ -d "$target" ] || die "target repo not found: $target"

case "$mode" in
  vendor) echo "Vendoring cloud-parity seed into $target"; vendor "$target" ;;
  check)  check_drift "$target"; check_consistency "$target" ;;
esac
