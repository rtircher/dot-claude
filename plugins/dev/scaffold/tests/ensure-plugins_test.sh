#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
script="$here/../cloud-parity/ensure-plugins.sh"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

home="$(make_fake_home "$work/home")"
bin="$work/bin"; log="$work/claude.log"; : > "$log"
make_fake_claude "$bin" "$log"

repo="$work/repo"; mkdir -p "$repo/scripts"
git -C "$repo" init -q
printf '%s\n' "marketplace-add rtircher/dot-claude" "install superpowers@claude-plugins-official" > "$repo/scripts/cloud-parity-recipes"

run() { HOME="$home" PATH="$bin:$PATH" bash -c "cd '$repo' && bash '$script'"; }

echo "case: nothing cloned -> both recipes fire"
run >/dev/null 2>&1
runlog="$(cat "$log")"
assert_contains "$runlog" "plugin marketplace add rtircher/dot-claude" "marketplace-add invoked"
assert_contains "$runlog" "plugin install superpowers@claude-plugins-official" "install invoked"
assert_contains "$runlog" "plugin marketplace update claude-plugins-official" "index updated before install"

echo "case: both present (real layout) -> nothing fires"
: > "$log"
add_marketplace_clone "$home" "dot-claude" "conventions" "conventions.md"
add_install_clone "$home" "claude-plugins-official" "superpowers" "skill.md"
run >/dev/null 2>&1
assert_eq "$(cat "$log")" "" "no claude calls when all clones present"

echo "case: collision negative -> an unrelated plugin does not satisfy a missing one"
: > "$log"
rm -rf "$home/.claude/plugins/cache"; mkdir -p "$home/.claude/plugins/cache"
add_install_clone "$home" "claude-plugins-official" "superpowers" "skill.md"   # only superpowers present
run >/dev/null 2>&1
assert_contains "$(cat "$log")" "plugin marketplace add rtircher/dot-claude" "dot-claude still fetched when only superpowers present"

echo "case: partial clone (bare dir, no file) -> still fires"
: > "$log"
rm -rf "$home/.claude/plugins/cache"
mkdir -p "$home/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0"   # dir only, no file
run >/dev/null 2>&1
assert_contains "$(cat "$log")" "plugin install superpowers@claude-plugins-official" "partial superpowers clone retried"

echo "case: last recipe line without trailing newline still fires"
: > "$log"
rm -rf "$home/.claude/plugins/cache"; mkdir -p "$home/.claude/plugins/cache"
printf 'marketplace-add rtircher/dot-claude' > "$repo/scripts/cloud-parity-recipes"   # no trailing newline
run >/dev/null 2>&1
assert_contains "$(cat "$log")" "plugin marketplace add rtircher/dot-claude" "last recipe processed without trailing newline"

echo "case: no recipe file -> no-op"
: > "$log"
rm -f "$repo/scripts/cloud-parity-recipes"
out="$(run 2>&1)"
assert_contains "$out" "no recipe file" "missing recipe file is a clean no-op"
assert_eq "$(cat "$log")" "" "no claude calls without recipes"

finish "ensure-plugins"
