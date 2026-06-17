#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
script="$here/../cloud-parity/session-start.sh"

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
home="$(make_fake_home "$work/home")"
bin="$work/bin"; make_fake_claude "$bin" "$work/c.log"
repo="$work/repo"; mkdir -p "$repo/scripts"; git -C "$repo" init -q
git -C "$repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "init"
# A no-op ensure-plugins so the detached rescue launches without doing real work.
printf '#!/usr/bin/env bash\nexit 0\n' > "$repo/scripts/ensure-plugins.sh"; chmod +x "$repo/scripts/ensure-plugins.sh"

run() { HOME="$home" TMPDIR="$work" PATH="$bin:$PATH" bash -c "cd '$repo' && bash '$script'"; }

echo "case: repo pulse always emitted"
out="$(run 2>&1)"
assert_contains "$out" "## Repo pulse" "pulse header present"
assert_contains "$out" "Branch:" "branch line present"

echo "case: conventions plugin ABSENT -> backstop fires and points at AGENTS.md"
printf "# project\n" > "$repo/AGENTS.md"
out="$(run 2>&1)"
assert_contains "$out" "Conventions backstop (conventions plugin not loaded)" "backstop header"
assert_contains "$out" "Read AGENTS.md" "points at AGENTS.md when present"
assert_contains "$out" "unversioned alias" "model-alias reminder present"

echo "case: conventions plugin PRESENT (real layout) -> backstop stays silent"
add_marketplace_clone "$home" "dot-claude" "conventions" "conventions.md"
out="$(run 2>&1)"
assert_not_contains "$out" "Conventions backstop" "backstop suppressed when plugin loaded"

echo "case: detached rescue eventually writes its log (bounded poll, no race)"
run >/dev/null 2>&1
ok=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -f "$work/plugin-prewarm.log" ] && { ok=1; break; }
  sleep 0.1
done
assert_eq "${ok:-}" "1" "prewarm log created within 1s"

finish "session-start"
