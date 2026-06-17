#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
scaffold="$here/../init-cloud-parity.sh"

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not installed"; exit 0; }

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
target="$work/consumer"; mkdir -p "$target"; git -C "$target" init -q

# Pre-existing settings the scaffold must PRESERVE, with the SessionStart hook in the
# FLAT {matcher,command} form to exercise the idempotency guard's blind spot.
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

echo "case: seed files copied and provenance-stamped"
run >/dev/null 2>&1
for f in .claude/cloud-setup.sh scripts/claude-hooks/session-start.sh scripts/ensure-plugins.sh scripts/cloud-plugin-doctor.sh; do
  [ -f "$target/$f" ] && printf "  ok: copied %s\n" "$f" || { printf "  FAIL: missing %s\n" "$f"; failures=$((failures+1)); }
  head -3 "$target/$f" | grep -q "vendored from dot-claude @" \
    && printf "  ok: stamped %s\n" "$f" || { printf "  FAIL: unstamped %s\n" "$f"; failures=$((failures+1)); }
done

echo "case: copied scripts stay valid bash (stamp inserted after the shebang)"
head -1 "$target/scripts/ensure-plugins.sh" | grep -q '^#!/usr/bin/env bash' && printf "  ok: shebang intact on line 1\n" || { printf "  FAIL: shebang moved\n"; failures=$((failures+1)); }
bash -n "$target/scripts/ensure-plugins.sh" && printf "  ok: stamped script parses\n" || { printf "  FAIL: stamped script broken\n"; failures=$((failures+1)); }

echo "case: starter recipe file written when absent"
[ -f "$target/scripts/cloud-parity-recipes" ] && printf "  ok: recipes written\n" || { printf "  FAIL\n"; failures=$((failures+1)); }

echo "case: settings merge owns only extraKnownMarketplaces + SessionStart, preserves the rest"
s="$target/.claude/settings.json"
assert_eq "$(jq -r '.extraKnownMarketplaces["dot-claude"].source.repo' "$s")" "rtircher/dot-claude" "marketplace added"
assert_eq "$(jq -r '.permissions.deny[0]' "$s")" "Bash(make tf-apply*)" "existing deny preserved"
assert_eq "$(jq -r '.hooks.PostToolUse[0].hooks[0].command' "$s")" "scripts/claude-hooks/format.sh" "existing PostToolUse hook preserved"
assert_eq "$(jq -r '.enabledPlugins | keys | length' "$s")" "1" "enabledPlugins untouched (scaffold does not add plugins)"

echo "case: flat-form SessionStart hook is recognized, NOT duplicated"
assert_eq "$(jq '.hooks.SessionStart | length' "$s")" "1" "no duplicate SessionStart entry (flat form recognized)"

echo "case: idempotent re-run does not duplicate the hook"
run >/dev/null 2>&1
assert_eq "$(jq '.hooks.SessionStart | length' "$s")" "1" "no duplicate SessionStart entry on re-run"

echo "case: existing recipe file is NOT overwritten"
printf "marketplace-add me/custom\n" > "$target/scripts/cloud-parity-recipes"
run >/dev/null 2>&1
assert_eq "$(cat "$target/scripts/cloud-parity-recipes")" "marketplace-add me/custom" "authored recipes preserved"

echo "case: --check passes immediately after vendoring (no drift)"
bash "$scaffold" "$target" >/dev/null 2>&1
printf "marketplace-add rtircher/dot-claude\n" > "$target/scripts/cloud-parity-recipes"   # match enabledPlugins
if bash "$scaffold" --check "$target" >/dev/null 2>&1; then printf "  ok: clean check exits 0\n"; else printf "  FAIL: clean check non-zero\n"; failures=$((failures+1)); fi

echo "case: --check flags a locally edited vendored file"
printf '\n# local tweak\n' >> "$target/scripts/ensure-plugins.sh"
if bash "$scaffold" --check "$target" >/dev/null 2>&1; then printf "  FAIL: drift not detected\n"; failures=$((failures+1)); else printf "  ok: drift detected (non-zero)\n"; fi

echo "case: --check warns when enabledPlugins has no matching recipe"
bash "$scaffold" "$target" >/dev/null 2>&1   # restore clean vendored files
printf "marketplace-add rtircher/dot-claude\n" > "$target/scripts/cloud-parity-recipes"
tmp="$(mktemp)"; jq '.enabledPlugins["superpowers@claude-plugins-official"]=true' "$target/.claude/settings.json" > "$tmp" && mv "$tmp" "$target/.claude/settings.json"
out="$(bash "$scaffold" --check "$target" 2>&1 || true)"
assert_contains "$out" "superpowers@claude-plugins-official" "consistency warning names the unmatched plugin"

echo "case: consistency reads a recipe with no trailing newline (gate not fooled)"
bash "$scaffold" "$target" >/dev/null 2>&1
printf 'install superpowers@claude-plugins-official' > "$target/scripts/cloud-parity-recipes"   # no trailing newline; covers the enabled plugin
out="$(bash "$scaffold" --check "$target" 2>&1 || true)"
assert_not_contains "$out" "'superpowers@claude-plugins-official' has no matching recipe" "no-newline recipe still satisfies consistency"

finish "scaffold"
