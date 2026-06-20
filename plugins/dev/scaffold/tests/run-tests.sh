#!/usr/bin/env bash
# Run all cloud-parity static checks and tests. Exit non-zero if any fails.
# This is the project's manual gate: run it before committing scaffold changes.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
seed="$here/../cloud-parity"
rc=0

echo "== bash -n (syntax) =="
for f in "$seed"/*.sh "$here/../init-cloud-parity.sh" "$here"/*.sh; do
  bash -n "$f" || { echo "  syntax error: $f"; rc=1; }
done

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck =="
  # Gate on warning+; info-level is non-blocking (the `A && ok || { FAIL; }` test
  # idiom is SC2015, sourcing lib.sh is SC1091, the diagnostic `ls` is SC2012).
  shellcheck --severity=warning "$seed"/*.sh "$here/../init-cloud-parity.sh" "$here"/*.sh || rc=1
else
  echo "== shellcheck (skipped: not installed) =="
fi

echo "== test suites =="
for t in "$here"/*_test.sh; do
  echo "--- $(basename "$t") ---"
  bash "$t" || rc=1
done

[ "$rc" -eq 0 ] && echo "ALL GREEN" || echo "FAILURES (rc=$rc)"
exit "$rc"
