#!/usr/bin/env bash
# Usage: bucket-areas.sh [--areas "<prefix> ..."] [--migrations "<prefix> ..."] < numstat
#
# Quick tier size gate and area bucketing. Reads `git diff --numstat` lines
# (added<TAB>deleted<TAB>path) on stdin; for a PR without a clone:
#   gh pr view <n> --json files -q '.files[]|[.additions,.deletions,.path]|@tsv'
#
# Each file maps to its longest matching --areas prefix (--migrations prefixes
# also count as areas), else its top-level directory. A migrations bucket always
# keeps one of the 3 area slots and never merges into misc; the other buckets
# merge smallest-first (by lines) into `misc` until they fit the remaining slots.
#
# Output:
#   mode<TAB>single-pass|fan-out<TAB><reason>
#   bucket<TAB><name><TAB><files><TAB><lines>
#   file<TAB><bucket><TAB><path>
# Single pass: fewer than 10 files and fewer than 200 lines added plus deleted,
# or every file in one area. Read-only; no side effects.
set -euo pipefail

areas="" migrations=""
while [ $# -gt 0 ]; do
  case "$1" in
    --areas) areas="${2-}"; shift 2 ;;
    --migrations) migrations="${2-}"; shift 2 ;;
    *) echo 'usage: bucket-areas.sh [--areas "<prefix> ..."] [--migrations "<prefix> ..."] < numstat' >&2; exit 2 ;;
  esac
done

awk -F'\t' -v areas="$areas" -v migs="$migrations" '
  BEGIN {
    na = split(areas " " migs, tmp, /[ \t]+/)
    for (i = 1; i <= na; i++) if (tmp[i] != "") prefix[++np] = tmp[i]
    nm = split(migs, mm, /[ \t]+/)
    for (i = 1; i <= nm; i++) if (mm[i] != "") ismig[mm[i]] = 1
  }
  NF >= 3 {
    add = ($1 ~ /^[0-9]+$/) ? $1 : 0; del = ($2 ~ /^[0-9]+$/) ? $2 : 0
    path = $3; for (i = 4; i <= NF; i++) path = path "\t" $i
    best = ""
    for (i = 1; i <= np; i++) if (index(path, prefix[i]) == 1 && length(prefix[i]) > length(best)) best = prefix[i]
    if (best == "") { best = path; if (index(best, "/")) sub(/\/.*/, "", best); else best = "(root)" }
    nf++; total += add + del
    fbucket[nf] = best; fpath[nf] = path
    files[best]++; lines[best] += add + del
    if (!(best in seen)) { seen[best] = 1; names[++nb] = best }
  }
  END {
    if (nf == 0) { print "mode\tsingle-pass\tno files"; exit }
    if (nf < 10 && total < 200) { mode = "single-pass"; why = nf " files, " total " lines" }
    else if (nb == 1) { mode = "single-pass"; why = "all files in one area (" names[1] ")" }
    else { mode = "fan-out"; why = nf " files, " total " lines, " nb " areas" }
    print "mode\t" mode "\t" why

    # Merge into misc: migrations buckets keep a slot; the rest share what is left.
    nmig = 0; nrest = 0
    for (i = 1; i <= nb; i++) { if (names[i] in ismig) nmig++; else rest[++nrest] = names[i] }
    slots = 3 - (nmig > 0 ? nmig : 0); if (slots < 1) slots = 1
    if (mode == "fan-out" && nrest > slots) {
      for (i = 1; i <= nrest; i++) for (j = i + 1; j <= nrest; j++)
        if (lines[rest[j]] < lines[rest[i]] || (lines[rest[j]] == lines[rest[i]] && rest[j] < rest[i])) { t = rest[i]; rest[i] = rest[j]; rest[j] = t }
      k = nrest - slots + 1
      for (i = 1; i <= k; i++) { merged[rest[i]] = 1; files["misc"] += files[rest[i]]; lines["misc"] += lines[rest[i]] }
      misc = 1
    }
    for (i = 1; i <= nb; i++) if (!(names[i] in merged)) print "bucket\t" names[i] "\t" files[names[i]] "\t" lines[names[i]]
    if (misc) print "bucket\tmisc\t" files["misc"] "\t" lines["misc"]
    for (i = 1; i <= nf; i++) print "file\t" ((fbucket[i] in merged) ? "misc" : fbucket[i]) "\t" fpath[i]
  }
'
