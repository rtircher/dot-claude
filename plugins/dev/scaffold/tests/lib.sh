# plugins/dev/scaffold/tests/lib.sh
# Tiny test helpers. Source this; each test file sets `failures` and calls assert_*.
# A fake `claude` records its argv to a logfile; a fake $HOME/.claude/plugins tree
# simulates clone presence using the REAL on-disk layout:
#   marketplace-add <owner/repo>  -> cache/<repo>/<plugin>/<sha>/<file>
#   install <plugin@market>       -> cache/<market>/<plugin>/<ver>/<file>
# No external test framework.

# shellcheck shell=bash
set -uo pipefail

failures=0

assert_eq() { # <actual> <expected> <msg>
  if [ "$1" = "$2" ]; then printf "  ok: %s\n" "$3"; else
    printf "  FAIL: %s\n    expected: %s\n    actual:   %s\n" "$3" "$2" "$1"; failures=$((failures+1)); fi
}
assert_contains() { # <haystack> <needle> <msg>
  case "$1" in *"$2"*) printf "  ok: %s\n" "$3" ;; *)
    printf "  FAIL: %s\n    missing: %s\n    in:      %s\n" "$3" "$2" "$1"; failures=$((failures+1)) ;; esac
}
assert_not_contains() { # <haystack> <needle> <msg>
  case "$1" in *"$2"*)
    printf "  FAIL: %s\n    unexpected: %s\n" "$3" "$2"; failures=$((failures+1)) ;; *) printf "  ok: %s\n" "$3" ;; esac
}

# make_fake_home <dir>: create an empty plugins tree and echo the HOME path.
make_fake_home() { mkdir -p "$1/.claude/plugins/cache" "$1/.claude/plugins/marketplaces"; printf "%s" "$1"; }

# add_fake_clone <home> <relative-path-under-plugins>: simulate a completed clone
# (a regular file present under the plugins tree).
add_fake_clone() { mkdir -p "$(dirname "$1/.claude/plugins/$2")"; : > "$1/.claude/plugins/$2"; }

# Real-layout convenience seeders (use these in tests, not raw paths).
add_marketplace_clone() { # <home> <repo-basename> <plugin> <file>
  add_fake_clone "$1" "cache/$2/$3/abc123/$4"
}
add_install_clone() { # <home> <market> <plugin> <file>
  add_fake_clone "$1" "cache/$2/$3/5.1.0/$4"
}

# make_fake_claude <bindir> <logfile>: put a `claude` on PATH that appends its argv
# (one space-joined line) to <logfile> and exits 0.
make_fake_claude() {
  mkdir -p "$1"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'printf "%%s\\n" "$*" >> %q\n' "$2"
    printf 'exit 0\n'
  } > "$1/claude"
  chmod +x "$1/claude"
}

finish() { # <suite-name>
  if [ "$failures" -eq 0 ]; then printf "PASS: %s\n" "$1"; exit 0
  else printf "FAIL: %s (%d failing)\n" "$1" "$failures"; exit 1; fi
}
