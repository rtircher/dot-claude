#!/usr/bin/env bash
# Usage: post-review.sh [--dry-run] --pr <n> --remote <git remote> --plan <file.json> \
#          [--summary-file <file>] [--repo <owner/repo>] [--sha <sha>]
#
# Posts one PR review holding many inline comments, so the author gets one
# notification. Grouped counterpart of post-comment.sh: pins the head SHA,
# locates every line from the file content at that SHA (never from `gh pr diff`),
# creates the review PENDING (no event), verifies each comment's diff_hunk, and
# only then submits it as a COMMENT. A misplaced anchor or an API error deletes
# the pending review, so none is ever left behind.
# Run from a clone of the PR's repo; `--remote` is the git remote whose URL
# matches that repo, and names the repo when --repo is omitted.
#
#   --plan          JSON list of {path, pattern, body_file, side?}; side is RIGHT
#                   (default) or LEFT. pattern is an ERE matching exactly one line
#                   of <path> at the head SHA (RIGHT) or at the PR's base SHA (LEFT,
#                   for a deleted line). body_file is the comment body, read verbatim.
#   --summary-file  the review body (default: empty)
#   --sha           reuse an already pinned head SHA; omitted, the PR's head is
#                   pinned and printed
#   --dry-run       read-only: locates the anchors, checks for an existing pending
#                   review, prints the request body; writes nothing
#
# Exit: 0 ok, 1 usage or lookup failure (no match, several matches, a pending
# review of yours already on the PR), 3 a comment landed on the wrong line or an
# API call failed after the review was created (the review is deleted, and where
# each entry landed is printed).
set -euo pipefail

usage() { sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }
die() { echo "post-review: $*" >&2; exit 1; }

dry=0 pr="" remote="" plan="" summary_file="" repo="" sha=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --pr) pr="${2:?}"; shift 2 ;;
    --remote) remote="${2:?}"; shift 2 ;;
    --plan) plan="${2:?}"; shift 2 ;;
    --summary-file) summary_file="${2:?}"; shift 2 ;;
    --repo) repo="${2:?}"; shift 2 ;;
    --sha) sha="${2:?}"; shift 2 ;;
    *) usage ;;
  esac
done
{ [ -n "$pr" ] && [ -n "$remote" ] && [ -n "$plan" ]; } || usage
[ -f "$plan" ] || die "no such plan file: $plan"
[ -z "$summary_file" ] || [ -f "$summary_file" ] || die "no such summary file: $summary_file"
jq -e 'type == "array" and length > 0 and all(.[]; (.path|type=="string") and (.pattern|type=="string") and (.body_file|type=="string") and ((.side // "RIGHT") | . == "RIGHT" or . == "LEFT"))' \
  "$plan" >/dev/null 2>&1 \
  || die "plan must be a non-empty JSON list of {path, pattern, body_file, side?} (side RIGHT or LEFT)"
n=$(jq length "$plan")
for ((i = 0; i < n; i++)); do
  bf=$(jq -r ".[$i].body_file" "$plan")
  [ -f "$bf" ] || die "no such body file: $bf"
done

# The repo comes from --remote, the remote the SHA is fetched from, so the review
# and the line lookups always address the same repo.
if [ -z "$repo" ]; then
  url=$(git remote get-url "$remote" 2>/dev/null) \
    || die "no git remote named '$remote'"
  url=${url%/}; url=${url%.git}
  # URL form (ssh:// or https://, optional user@ and :port) or scp form
  # (user@host:owner/repo, host may be an ssh config alias).
  if [[ "$url" =~ ^[A-Za-z][A-Za-z0-9+.-]*://([^/@]+@)?[^/]+/([^/]+)/([^/]+)$ ]]; then
    repo="${BASH_REMATCH[2]}/${BASH_REMATCH[3]}"
  elif [[ "$url" =~ ^([^/@:]+@)?[^/:]+:([^/]+)/([^/]+)$ ]]; then
    repo="${BASH_REMATCH[2]}/${BASH_REMATCH[3]}"
  else
    die "cannot derive owner/repo from remote '$remote' ($url); pass --repo"
  fi
fi

# 1. Pin the head SHA (and the base SHA when an entry targets a deleted line).
[ -n "$sha" ] || sha=$(gh pr view "$pr" -R "$repo" --json headRefOid -q .headRefOid)
echo "sha: $sha"
base_sha=""
if jq -e 'any(.[]; .side == "LEFT")' "$plan" >/dev/null; then
  base_sha=$(gh pr view "$pr" -R "$repo" --json baseRefOid -q .baseRefOid)
  echo "base: $base_sha"
fi

# 2. Locate each line in the real file at its SHA.
git fetch -q "$remote" "$sha"
[ -z "$base_sha" ] || git fetch -q "$remote" "$base_sha"
paths=() lines=() texts=() sides=() bodies=()
for ((i = 0; i < n; i++)); do
  path=$(jq -r ".[$i].path" "$plan")
  pattern=$(jq -r ".[$i].pattern" "$plan")
  side=$(jq -r ".[$i].side // \"RIGHT\"" "$plan")
  at=$sha; [ "$side" = LEFT ] && at=$base_sha
  matches=$(git show "$at:$path" | grep -nE -e "$pattern" || true)
  count=$(printf '%s' "$matches" | grep -c . || true)
  if [ "$count" -ne 1 ]; then
    echo "post-review: entry $((i + 1)): pattern matched $count lines of $path at ${at:0:9} (need exactly 1):" >&2
    printf '%s\n' "$matches" | cut -c1-120 >&2
    exit 1
  fi
  text=${matches#*:}
  paths+=("$path"); lines+=("${matches%%:*}"); texts+=("${text%$'\r'}"); sides+=("$side")
  bodies+=("$(jq -r ".[$i].body_file" "$plan")")
  echo "anchor: $path:${lines[i]} $side @ ${at:0:9}  ${text:0:60}"
done

# 3. Refuse when the current user already has a pending review on the PR: GitHub
# allows one, and ours would collide with it.
me=$(gh api user -q .login)
pending=$(gh api "repos/$repo/pulls/$pr/reviews" --paginate \
  -q ".[] | select(.state==\"PENDING\" and .user.login==\"$me\") | .id")
if [ -n "$pending" ]; then
  die "$me already has a pending review on PR $pr (review id $(printf '%s' "$pending" | head -1)); submit or delete it first. Nothing was written."
fi

comments='[]'
for ((i = 0; i < n; i++)); do
  comments=$(jq --arg p "${paths[i]}" --argjson l "${lines[i]}" --arg s "${sides[i]}" \
    --rawfile b "${bodies[i]}" '. + [{path: $p, line: $l, side: $s, body: $b}]' <<<"$comments")
done
summary=""
[ -z "$summary_file" ] || summary=$(<"$summary_file")
request=$(jq -n --arg c "$sha" --arg b "$summary" --argjson cs "$comments" \
  '{commit_id: $c, body: $b, comments: $cs}')

if [ "$dry" = 1 ]; then
  echo "dry-run, would POST repos/$repo/pulls/$pr/reviews (no event, stays PENDING) with:"
  printf '%s\n' "$request"
  echo "then verify each diff_hunk, then POST repos/$repo/pulls/$pr/reviews/<id>/events event=COMMENT"
  exit 0
fi

# 4. Create the review PENDING: no `event`.
review=$(printf '%s' "$request" | gh api "repos/$repo/pulls/$pr/reviews" --method POST --input -)
id=$(jq -r .id <<<"$review")
[[ "$id" =~ ^[0-9]+$ ]] || die "review creation returned no id: ${review:0:200}"

# 5. Verify each comment's diff_hunk against the located line. Sets $landed to a
# report of where every entry ended up; returns 1 on any mismatch or API error.
landed=""
verify() {
  local got i hunk last ok bad=0
  got=$(gh api "repos/$repo/pulls/$pr/reviews/$id/comments" --paginate) || return 1
  got=$(jq -s 'add // []' <<<"$got") || return 1
  [ "$(jq length <<<"$got")" -eq "$n" ] || { landed="expected $n comments, review has $(jq length <<<"$got")"; return 1; }
  for ((i = 0; i < n; i++)); do
    # Entries map to comments by path + body (trailing newlines ignored).
    hunk=$(jq -r --arg p "${paths[i]}" --rawfile b "${bodies[i]}" \
      'map(select(.path == $p and ((.body | rtrimstr("\n")) == ($b | rtrimstr("\n"))))) | first | .diff_hunk // empty' \
      <<<"$got") || return 1
    last=$(printf '%s' "$hunk" | awk 'END { print }')
    last=${last%$'\r'}
    if [ -z "$hunk" ]; then
      landed+="  entry $((i + 1)) ${paths[i]}:${lines[i]}: no matching comment in the review"$'\n'; bad=1; continue
    fi
    ok=0
    if [ "${last:1}" = "${texts[i]}" ]; then
      case "${sides[i]}:${last:0:1}" in RIGHT:+ | "RIGHT: " | LEFT:-) ok=1 ;; esac
    fi
    if [ "$ok" = 1 ]; then
      landed+="  entry $((i + 1)) ${paths[i]}:${lines[i]} ${sides[i]}: ok"$'\n'
    else
      landed+="  entry $((i + 1)) ${paths[i]}:${lines[i]} ${sides[i]}: WRONG, diff_hunk ends: ${last:0:60}"$'\n'; bad=1
    fi
  done
  [ "$bad" = 0 ]
}

# 6. Any mismatch or API error from here on: delete the pending review.
if ! verify; then
  echo "post-review: review $id has misplaced or missing comments:" >&2
  printf '%s' "$landed" >&2
  if gh api "repos/$repo/pulls/$pr/reviews/$id" --method DELETE >/dev/null; then
    echo "post-review: pending review $id deleted; nothing was submitted" >&2
  else
    echo "post-review: could not delete it; run: gh api -X DELETE repos/$repo/pulls/$pr/reviews/$id" >&2
  fi
  exit 3
fi

# 7. Submit.
if ! out=$(gh api "repos/$repo/pulls/$pr/reviews/$id/events" --method POST -f event=COMMENT); then
  echo "post-review: submitting review $id failed" >&2
  if gh api "repos/$repo/pulls/$pr/reviews/$id" --method DELETE >/dev/null; then
    echo "post-review: pending review $id deleted" >&2
  else
    echo "post-review: could not delete it; run: gh api -X DELETE repos/$repo/pulls/$pr/reviews/$id" >&2
  fi
  exit 3
fi
printf '%s' "$landed"
echo "posted: review $id, $n comments (diff_hunks verified)"
echo "url: $(jq -r '.html_url // empty' <<<"$out")"
