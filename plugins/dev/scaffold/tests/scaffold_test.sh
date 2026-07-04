#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
scaffold="$here/../init-cloud-parity.sh"

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not installed"; exit 0; }

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
target="$work/consumer"; mkdir -p "$target"; git -C "$target" init -q

# Pre-existing settings the scaffold must PRESERVE, with a SessionStart hook in the
# FLAT {matcher,command} form pointing at the PRE-.claude/cloud path, so the run
# exercises both the flat-form guard and the legacy-path migration (strip + replace).
mkdir -p "$target/.claude"
cat > "$target/.claude/settings.json" <<'JSON'
{
  "permissions": { "allow": ["Bash(make *)"], "deny": ["Bash(make tf-apply*)"] },
  "hooks": {
    "PostToolUse": [ { "matcher": "Write", "hooks": [ { "type": "command", "command": "scripts/claude-hooks/format.sh" } ] } ],
    "SessionStart": [ { "matcher": "", "command": "scripts/claude-hooks/session-start.sh" } ]
  },
  "enabledPlugins": { "conventions@dot-claude": true }
}
JSON

run() { bash "$scaffold" "$target"; }

echo "case: seed files copied under .claude/cloud and provenance-stamped"
run >/dev/null 2>&1
for f in .claude/cloud/cloud-setup.sh .claude/cloud/session-start.sh .claude/cloud/ensure-plugins.sh .claude/cloud/cloud-plugin-doctor.sh; do
  [ -f "$target/$f" ] && printf "  ok: copied %s\n" "$f" || { printf "  FAIL: missing %s\n" "$f"; failures=$((failures+1)); }
  head -3 "$target/$f" | grep -q "vendored from dot-claude @" \
    && printf "  ok: stamped %s\n" "$f" || { printf "  FAIL: unstamped %s\n" "$f"; failures=$((failures+1)); }
done

echo "case: copied scripts stay valid bash (stamp inserted after the shebang)"
head -1 "$target/.claude/cloud/ensure-plugins.sh" | grep -q '^#!/usr/bin/env bash' && printf "  ok: shebang intact on line 1\n" || { printf "  FAIL: shebang moved\n"; failures=$((failures+1)); }
bash -n "$target/.claude/cloud/ensure-plugins.sh" && printf "  ok: stamped script parses\n" || { printf "  FAIL: stamped script broken\n"; failures=$((failures+1)); }

echo "case: starter recipe file written when absent"
[ -f "$target/.claude/cloud/cloud-parity-recipes" ] && printf "  ok: recipes written\n" || { printf "  FAIL\n"; failures=$((failures+1)); }

echo "case: settings merge owns only extraKnownMarketplaces + SessionStart, preserves the rest"
s="$target/.claude/settings.json"
assert_eq "$(jq -r '.extraKnownMarketplaces["dot-claude"].source.repo' "$s")" "rtircher/dot-claude" "marketplace added"
assert_eq "$(jq -r '.permissions.deny[0]' "$s")" "Bash(make tf-apply*)" "existing deny preserved"
assert_eq "$(jq -r '.hooks.PostToolUse[0].hooks[0].command' "$s")" "scripts/claude-hooks/format.sh" "existing PostToolUse hook preserved"
assert_eq "$(jq -r '.enabledPlugins | keys | length' "$s")" "1" "enabledPlugins untouched (scaffold does not add plugins)"

echo "case: legacy flat-form SessionStart hook is migrated to the new path, not duplicated"
assert_eq "$(jq '.hooks.SessionStart | length' "$s")" "1" "exactly one SessionStart entry (legacy flat form stripped)"
assert_eq "$(jq -r '.hooks.SessionStart[0].hooks[0].command' "$s")" ".claude/cloud/session-start.sh" "hook points at the .claude/cloud path"

echo "case: idempotent re-run does not duplicate the hook"
run >/dev/null 2>&1
assert_eq "$(jq '.hooks.SessionStart | length' "$s")" "1" "no duplicate SessionStart entry on re-run"

echo "case: existing recipe file is NOT overwritten"
printf "marketplace-add me/custom\n" > "$target/.claude/cloud/cloud-parity-recipes"
run >/dev/null 2>&1
assert_eq "$(cat "$target/.claude/cloud/cloud-parity-recipes")" "marketplace-add me/custom" "authored recipes preserved"

echo "case: --check passes immediately after vendoring (no drift)"
bash "$scaffold" "$target" >/dev/null 2>&1
printf "marketplace-add rtircher/dot-claude\n" > "$target/.claude/cloud/cloud-parity-recipes"   # match enabledPlugins
if bash "$scaffold" --check "$target" >/dev/null 2>&1; then printf "  ok: clean check exits 0\n"; else printf "  FAIL: clean check non-zero\n"; failures=$((failures+1)); fi

echo "case: --check flags a locally edited vendored file"
printf '\n# local tweak\n' >> "$target/.claude/cloud/ensure-plugins.sh"
if bash "$scaffold" --check "$target" >/dev/null 2>&1; then printf "  FAIL: drift not detected\n"; failures=$((failures+1)); else printf "  ok: drift detected (non-zero)\n"; fi

echo "case: --check warns when enabledPlugins has no matching recipe"
bash "$scaffold" "$target" >/dev/null 2>&1   # restore clean vendored files
printf "marketplace-add rtircher/dot-claude\n" > "$target/.claude/cloud/cloud-parity-recipes"
tmp="$(mktemp)"; jq '.enabledPlugins["superpowers@claude-plugins-official"]=true' "$target/.claude/settings.json" > "$tmp" && mv "$tmp" "$target/.claude/settings.json"
out="$(bash "$scaffold" --check "$target" 2>&1 || true)"
assert_contains "$out" "superpowers@claude-plugins-official" "consistency warning names the unmatched plugin"

echo "case: consistency reads a recipe with no trailing newline (gate not fooled)"
bash "$scaffold" "$target" >/dev/null 2>&1
printf 'install superpowers@claude-plugins-official' > "$target/.claude/cloud/cloud-parity-recipes"   # no trailing newline; covers the enabled plugin
out="$(bash "$scaffold" --check "$target" 2>&1 || true)"
assert_not_contains "$out" "'superpowers@claude-plugins-official' has no matching recipe" "no-newline recipe still satisfies consistency"

# --- migration from the pre-.claude/cloud layout ---
echo "case: full legacy layout is migrated on vendor (moves authored data, drops seed copies, rewrites hook)"
old="$work/legacy"; mkdir -p "$old/scripts/claude-hooks" "$old/.claude"; git -C "$old" init -q
# Legacy seed copies (content is irrelevant; migration deletes and re-vendors them).
printf '#!/usr/bin/env bash\n# old hook\n' > "$old/scripts/claude-hooks/session-start.sh"
printf '#!/usr/bin/env bash\n# old ensure\n' > "$old/scripts/ensure-plugins.sh"
printf '#!/usr/bin/env bash\n# old doctor\n' > "$old/scripts/cloud-plugin-doctor.sh"
printf '#!/usr/bin/env bash\n# old setup\n' > "$old/.claude/cloud-setup.sh"
# Legacy authored data (must be PRESERVED verbatim at the new path).
printf 'marketplace-add rtircher/dot-claude\n' > "$old/scripts/cloud-parity-recipes"
printf '#!/usr/bin/env bash\n: > /tmp/authored-local\n' > "$old/scripts/cloud-setup-local.sh"
cat > "$old/.claude/settings.json" <<'JSON'
{ "hooks": { "SessionStart": [ { "hooks": [ { "type": "command", "command": "scripts/claude-hooks/session-start.sh" } ] } ] } }
JSON
bash "$scaffold" "$old" >/dev/null 2>&1

for legacy in scripts/claude-hooks/session-start.sh scripts/ensure-plugins.sh scripts/cloud-plugin-doctor.sh .claude/cloud-setup.sh scripts/cloud-parity-recipes scripts/cloud-setup-local.sh; do
  [ -e "$old/$legacy" ] && { printf "  FAIL: legacy %s survived migration\n" "$legacy"; failures=$((failures+1)); } || printf "  ok: legacy %s removed\n" "$legacy"
done
[ -d "$old/scripts/claude-hooks" ] && { printf "  FAIL: empty scripts/claude-hooks not pruned\n"; failures=$((failures+1)); } || printf "  ok: empty scripts/claude-hooks pruned\n"
for f in .claude/cloud/session-start.sh .claude/cloud/ensure-plugins.sh .claude/cloud/cloud-plugin-doctor.sh .claude/cloud/cloud-setup.sh .claude/cloud/cloud-parity-recipes .claude/cloud/cloud-setup-local.sh; do
  [ -f "$old/$f" ] && printf "  ok: new %s present\n" "$f" || { printf "  FAIL: new %s missing\n" "$f"; failures=$((failures+1)); }
done
assert_eq "$(cat "$old/.claude/cloud/cloud-parity-recipes")" "marketplace-add rtircher/dot-claude" "authored recipe content preserved through move"
assert_contains "$(cat "$old/.claude/cloud/cloud-setup-local.sh")" "authored-local" "authored cloud-setup-local content preserved through move"
assert_eq "$(jq '.hooks.SessionStart | length' "$old/.claude/settings.json")" "1" "single SessionStart entry after migration"
assert_eq "$(jq -r '.hooks.SessionStart[0].hooks[0].command' "$old/.claude/settings.json")" ".claude/cloud/session-start.sh" "legacy nested hook rewritten to new path"

echo "case: --check on a migrated repo is clean; a re-introduced legacy file is flagged"
printf 'marketplace-add rtircher/dot-claude\n' > "$old/.claude/cloud/cloud-parity-recipes"
if bash "$scaffold" --check "$old" >/dev/null 2>&1; then printf "  ok: migrated repo checks clean\n"; else printf "  FAIL: migrated repo check non-zero\n"; failures=$((failures+1)); fi
printf '#!/usr/bin/env bash\n' > "$old/scripts/ensure-plugins.sh"   # re-introduce a legacy leftover
out="$(bash "$scaffold" --check "$old" 2>&1 || true)"
assert_contains "$out" "[LEGACY]  scripts/ensure-plugins.sh" "--check flags a leftover legacy file"

echo "case: legacy hook co-located with a repo hook in one entry -> repo hook survives (strip is per-hook)"
mix="$work/mixed"; mkdir -p "$mix/.claude"; git -C "$mix" init -q
cat > "$mix/.claude/settings.json" <<'JSON'
{ "hooks": { "SessionStart": [ { "hooks": [
  { "type": "command", "command": "scripts/claude-hooks/session-start.sh" },
  { "type": "command", "command": "scripts/repo-critical-init.sh" }
] } ] } }
JSON
bash "$scaffold" "$mix" >/dev/null 2>&1
cmds="$(jq -r '[.hooks.SessionStart[] | (.command? // empty), (.hooks[]?.command? // empty)] | join(",")' "$mix/.claude/settings.json")"
assert_contains "$cmds" "scripts/repo-critical-init.sh" "co-located repo hook preserved through the legacy strip"
assert_contains "$cmds" ".claude/cloud/session-start.sh" "new cloud hook added"
assert_not_contains "$cmds" "scripts/claude-hooks/session-start.sh" "legacy hook stripped"

finish "scaffold"
