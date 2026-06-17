#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
script="$here/../cloud-parity/cloud-plugin-doctor.sh"

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
home="$(make_fake_home "$work/home")"
repo="$work/repo"; mkdir -p "$repo/scripts"; git -C "$repo" init -q
printf '%s\n' "marketplace-add rtircher/dot-claude" "install superpowers@claude-plugins-official" > "$repo/scripts/cloud-parity-recipes"

run() { HOME="$home" bash -c "cd '$repo' && bash '$script'"; }

echo "case: nothing present -> two MISSING + non-clean verdict + exit 0"
out="$(run 2>&1)"; rc=$?
assert_eq "$rc" "0" "doctor always exits 0 even with misses"
assert_contains "$out" "[MISSING] marketplace rtircher/dot-claude" "dot-claude reported missing"
assert_contains "$out" "[MISSING] external superpowers@claude-plugins-official" "superpowers reported missing"
assert_contains "$out" "one or more clones are MISSING" "verdict flags misses"

echo "case: all present (real layout) -> all ok + clean verdict + conventions sub-check"
add_marketplace_clone "$home" "dot-claude" "conventions" "conventions.md"
add_install_clone "$home" "claude-plugins-official" "superpowers" "skill.md"
out="$(run 2>&1)"
assert_contains "$out" "[ok]      marketplace rtircher/dot-claude" "dot-claude ok"
assert_contains "$out" "[ok]      conventions.md" "conventions sub-check ok"
assert_contains "$out" "all expected plugin clones are present" "clean verdict"

echo "case: no recipe file -> nothing to check"
rm -f "$repo/scripts/cloud-parity-recipes"
out="$(run 2>&1)"
assert_contains "$out" "declares no cloud plugins" "no-recipe message"

finish "doctor"
