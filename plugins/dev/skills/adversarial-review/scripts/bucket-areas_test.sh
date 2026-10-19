#!/usr/bin/env bash
# bucket-areas.sh: size gate, bucketing (longest prefix, top-level fallback), the
# merge into misc, and the migrations slot. Feeds numstat on stdin; no git needed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../../scaffold/tests/lib.sh
. "$here/../../../scaffold/tests/lib.sh"

ba="$here/bucket-areas.sh"
tab=$'\t'
run() { bash "$ba" "$@"; } # stdin passes through

# Empty diff.
assert_eq "$(printf '' | run)" "mode${tab}single-pass${tab}no files" "no files: single pass"

# Small diff with a binary file (numstat prints '-' for both counts): the binary
# adds no lines and must not break the arithmetic.
out=$(printf '5\t1\tsrc/a.c\n-\t-\timg/x.png\nREADME.md\n' | run)
assert_eq "$out" "$(printf 'mode\tsingle-pass\t2 files, 6 lines\nbucket\tsrc\t1\t6\nbucket\timg\t1\t0\nfile\tsrc\tsrc/a.c\nfile\timg\timg/x.png')" \
  "binary numstat counts as 0 lines; short line ignored"

# A root-level file buckets as (root).
out=$(printf '1\t1\tREADME.md\n' | run)
assert_contains "$out" "bucket${tab}(root)${tab}1${tab}2" "root file bucket"

# Many files and lines but a single area: still one pass.
out=$(for i in $(seq 1 12); do printf '30\t0\tsrc/f%s.c\n' "$i"; done | run)
assert_contains "$out" "mode${tab}single-pass${tab}all files in one area (src)" "one area: single pass"

# Six areas, two files each, 20..120 lines per area: fan-out, the four smallest
# areas merge into misc and the two largest keep their buckets.
six() { for i in 1 2 3 4 5 6; do printf '%s\t0\td%s/a\n%s\t0\td%s/b\n' $((i * 10)) "$i" $((i * 10)) "$i"; done; }
out=$(six | run)
assert_contains "$out" "mode${tab}fan-out${tab}12 files, 420 lines, 6 areas" "six areas: fan-out"
assert_contains "$out" "bucket${tab}d5${tab}2${tab}100" "largest areas keep a bucket (d5)"
assert_contains "$out" "bucket${tab}d6${tab}2${tab}120" "largest areas keep a bucket (d6)"
assert_contains "$out" "bucket${tab}misc${tab}8${tab}200" "four smallest areas merge into misc"
assert_eq "$(printf '%s\n' "$out" | grep -c '^bucket')" "3" "three buckets in total"
assert_contains "$out" "file${tab}misc${tab}d1/a" "merged file reports misc"
assert_contains "$out" "file${tab}d6${tab}d6/b" "kept file keeps its bucket"

# Migrations: the bucket keeps its own slot even when it is the smallest, so only
# two slots remain for the other areas.
mig() { printf '1\t0\tdb/mig/001.sql\n1\t0\tdb/mig/002.sql\n'; }
out=$({ six; mig; } | run --migrations "db/mig/")
assert_contains "$out" "bucket${tab}db/mig/${tab}2${tab}2" "migrations bucket survives as the smallest"
assert_contains "$out" "bucket${tab}d6${tab}2${tab}120" "migrations: largest other area kept"
assert_contains "$out" "bucket${tab}misc${tab}10${tab}300" "migrations: the other five merge into misc"
assert_not_contains "$out" "bucket${tab}d5" "migrations: second-largest area merged, only 2 non-migration slots"
assert_eq "$(printf '%s\n' "$out" | grep -c '^bucket')" "3" "migrations: still three buckets"

# Longest --areas prefix wins; unlisted paths fall back to the top-level dir.
out=$(printf '1\t0\tsrc/api/x.py\n1\t0\tsrc/web/y.py\n1\t0\tdocs/z.md\n' | run --areas "src/ src/api/")
assert_contains "$out" "file${tab}src/api/${tab}src/api/x.py" "longest area prefix wins"
assert_contains "$out" "file${tab}src/${tab}src/web/y.py" "shorter area prefix otherwise"
assert_contains "$out" "file${tab}docs${tab}docs/z.md" "no prefix: top-level directory"

# A prefix matches from the start of the path only.
out=$(printf '1\t0\tother/src/x.py\n' | run --areas "src/")
assert_contains "$out" "file${tab}other${tab}other/src/x.py" "prefix is anchored at the path start"

# Bad flag.
printf '' | bash "$ba" --bogus >/dev/null 2>&1
assert_eq "$?" "2" "unknown flag exits 2"

finish "bucket-areas"
