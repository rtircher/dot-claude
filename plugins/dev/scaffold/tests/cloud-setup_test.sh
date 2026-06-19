#!/usr/bin/env bash
# The generic cloud-setup.sh runs the OPTIONAL repo-defined root hook
# (scripts/cloud-setup-local.sh) when a consumer repo ships one, and is a clean
# no-op when it doesn't. This is the setup-time, root, once-cached counterpart to
# the in-session ensure-<tool>.sh convention: it's where a repo puts work that
# needs root at container build (apt system packages, a native build toolchain).
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
. "$here/lib.sh"
seed="$here/../cloud-parity/cloud-setup.sh"

# Shadow the few side-effecting commands the generic seed touches so the test never
# hits the network, real apt, or the real ~/.claude. The seed already guards each
# with `|| echo WARN`, but a real `claude` on PATH would do a live marketplace add.
fakebin="$(mktemp -d)"; trap 'rm -rf "$fakebin"' EXIT
for cmd in claude apt-get; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$fakebin/$cmd"; chmod +x "$fakebin/$cmd"
done
export PATH="$fakebin:$PATH"

echo "case: repo-defined cloud-setup-local.sh is executed when present"
repo="$(mktemp -d)"; mkdir -p "$repo/scripts"
sentinel="$repo/ran"
printf '#!/usr/bin/env bash\n: > %q\n' "$sentinel" > "$repo/scripts/cloud-setup-local.sh"
chmod +x "$repo/scripts/cloud-setup-local.sh"
( cd "$repo" && bash "$seed" >/dev/null 2>&1 )
[ -f "$sentinel" ] && printf "  ok: local hook executed\n" \
  || { printf "  FAIL: local hook not executed\n"; failures=$((failures+1)); }
rm -rf "$repo"

echo "case: a failing local hook fails the whole setup (loud, not swallowed)"
repo="$(mktemp -d)"; mkdir -p "$repo/scripts"
printf '#!/usr/bin/env bash\nexit 7\n' > "$repo/scripts/cloud-setup-local.sh"
chmod +x "$repo/scripts/cloud-setup-local.sh"
( cd "$repo" && bash "$seed" >/dev/null 2>&1 ); rc=$?
[ "$rc" -ne 0 ] && printf "  ok: setup exits non-zero when the local hook fails\n" \
  || { printf "  FAIL: local hook failure was swallowed\n"; failures=$((failures+1)); }
rm -rf "$repo"

echo "case: absent cloud-setup-local.sh is skipped without error"
repo="$(mktemp -d)"
( cd "$repo" && bash "$seed" >/dev/null 2>&1 ); rc=$?
assert_eq "$rc" "0" "seed exits 0 when no local hook is present"
rm -rf "$repo"

finish "cloud-setup"
