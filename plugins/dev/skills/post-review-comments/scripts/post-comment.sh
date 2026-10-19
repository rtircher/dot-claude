#!/usr/bin/env bash
# Usage: post-comment.sh [--dry-run] --pr <n> --remote <git remote> --path <file> \
#          --pattern <ERE> --body-file <file> [--repo <owner/repo>] [--sha <sha>]
#
# Posts one inline PR review comment on the right line: pins the head SHA,
# locates the line from the file content at that SHA (never from `gh pr diff`),
# posts with the single-comment endpoint, then checks the comment's diff_hunk.
# Run from a clone of the PR's repo; `--remote` is the git remote whose URL
# matches that repo, and names the repo when --repo is omitted. Side is always RIGHT (the new version of the file); for a
# deleted line, make the same `gh api` call by hand with side=LEFT.
#
#   --pattern    ERE matching exactly one line of <path> at the SHA
#   --body-file  the comment body (tag first), read verbatim
#   --sha        reuse an already pinned SHA across several comments of one
#                review; omitted, the PR's current head is pinned and printed
#   --dry-run    read-only: prints the `gh api` call it would make and checks the
#                located line sits inside a diff hunk of the PR; posts nothing
#
# Exit: 0 ok, 1 usage or lookup failure (no match, several matches, line outside
# the diff), 3 posted but misplaced (the comment id and delete command are
# printed; delete and repost, a comment on the wrong line is always wrong).
set -euo pipefail

usage() { sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }

dry=0 pr="" remote="" path="" pattern="" body_file="" repo="" sha=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --pr) pr="${2:?}"; shift 2 ;;
    --remote) remote="${2:?}"; shift 2 ;;
    --path) path="${2:?}"; shift 2 ;;
    --pattern) pattern="${2:?}"; shift 2 ;;
    --body-file) body_file="${2:?}"; shift 2 ;;
    --repo) repo="${2:?}"; shift 2 ;;
    --sha) sha="${2:?}"; shift 2 ;;
    *) usage ;;
  esac
done
{ [ -n "$pr" ] && [ -n "$remote" ] && [ -n "$path" ] && [ -n "$pattern" ] && [ -n "$body_file" ]; } || usage
[ -f "$body_file" ] || { echo "post-comment: no such body file: $body_file" >&2; exit 1; }

# The repo comes from --remote, the remote the SHA is fetched from, so the comment
# and the line lookup always address the same repo (`gh repo view` follows the
# gh default, which can differ in a multi-remote clone).
if [ -z "$repo" ]; then
  url=$(git remote get-url "$remote" 2>/dev/null) \
    || { echo "post-comment: no git remote named '$remote'" >&2; exit 1; }
  url=${url%/}; url=${url%.git}
  # URL form (ssh:// or https://, optional user@ and :port) or scp form
  # (user@host:owner/repo, host may be an ssh config alias).
  if [[ "$url" =~ ^[A-Za-z][A-Za-z0-9+.-]*://([^/@]+@)?[^/]+/([^/]+)/([^/]+)$ ]]; then
    repo="${BASH_REMATCH[2]}/${BASH_REMATCH[3]}"
  elif [[ "$url" =~ ^([^/@:]+@)?[^/:]+:([^/]+)/([^/]+)$ ]]; then
    repo="${BASH_REMATCH[2]}/${BASH_REMATCH[3]}"
  else
    echo "post-comment: cannot derive owner/repo from remote '$remote' ($url); pass --repo" >&2
    exit 1
  fi
fi

# 1. Pin the head SHA.
[ -n "$sha" ] || sha=$(gh pr view "$pr" -R "$repo" --json headRefOid -q .headRefOid)
echo "sha: $sha"

# 2. Locate the line in the real file at that SHA.
git fetch -q "$remote" "$sha"
matches=$(git show "$sha:$path" | grep -nE -e "$pattern" || true)
count=$(printf '%s' "$matches" | grep -c . || true)
if [ "$count" -ne 1 ]; then
  echo "post-comment: pattern matched $count lines of $path at ${sha:0:9} (need exactly 1):" >&2
  printf '%s\n' "$matches" | cut -c1-120 >&2
  exit 1
fi
line=${matches%%:*}
text=${matches#*:}
echo "anchor: $path:$line @ ${sha:0:9}  ${text:0:60}"

call=(gh api "repos/$repo/pulls/$pr/comments" --method POST
  -f "commit_id=$sha" -f "path=$path" -F "line=$line" -f side=RIGHT -F "body=@$body_file")

if [ "$dry" = 1 ]; then
  # Read-only anchor check: the line must fall inside a hunk of the PR's diff,
  # or GitHub rejects the comment.
  patch=$(gh api "repos/$repo/pulls/$pr/files" --paginate -q ".[] | select(.filename==\"$path\") | .patch // \"\"")
  if [ -z "$patch" ]; then
    echo "anchor check: no patch for $path in the PR's files (not in the diff, or too large to show)" >&2
    exit 1
  fi
  range=$(printf '%s\n' "$patch" | awk -v n="$line" '
    /^@@/ { s = $3; sub(/^\+/, "", s); split(s, a, ","); start = a[1]; len = (a[2] == "" ? 1 : a[2])
            if (n >= start && n < start + len) { print start "-" (start + len - 1); exit } }')
  if [ -z "$range" ]; then
    echo "anchor check: line $line of $path is outside every diff hunk of PR $pr" >&2
    exit 1
  fi
  echo "anchor check: line $line is inside the diff hunk covering new lines $range"
  printf 'dry-run, would run:'; printf ' %q' "${call[@]}"; printf '\n'
  exit 0
fi

# 3. Post, then 4. verify via the last line of the comment's diff_hunk.
id=$("${call[@]}" -q .id)
last=$(gh api "repos/$repo/pulls/comments/$id" -q '.diff_hunk | split("\n") | last')
last=${last%$'\r'}
if [ "${last:1}" = "${text%$'\r'}" ]; then
  echo "posted: comment $id on $path:$line (diff_hunk verified)"
else
  echo "post-comment: comment $id landed on the wrong line (diff_hunk ends: ${last:0:60})" >&2
  echo "delete it: gh api -X DELETE repos/$repo/pulls/comments/$id" >&2
  exit 3
fi
