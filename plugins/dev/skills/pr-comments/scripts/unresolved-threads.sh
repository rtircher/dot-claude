#!/usr/bin/env bash
# Read-only: unresolved review threads on my open PRs, or on the one PR named by
# $1. No repo is assumed:
#   (none)            my open PRs in every repo (gh search), or only in -R's repo
#   <url>             that PR (the URL carries owner/repo)
#   <n> | #<n>        PR n in -R's repo, else the current directory's repo
#   -R owner/repo     scope the above to one repo
# Prints a TSV, one row per thread, from the thread's first comment:
# pr (owner/repo#n), path:line, author, excerpt, url, thread_id.
# Exits non-zero if any lookup fails, so an outage never reads as "no threads".
set -uo pipefail
# type -P, not command -v: a BASH_ENV may inject a gh() guard function into
# every script, and command -v resolves to it instead of the binary.
GH="$(type -P gh || true)"
[[ -x "$GH" ]] || { echo "unresolved-threads: gh not found" >&2; exit 2; }

repo="" arg=""
while (( $# )); do
  case "$1" in
    -R) repo="${2:-}"; shift 2 ;;
    -R*) repo="${1#-R}"; shift ;;
    *) [[ -z "$arg" ]] && arg="$1"; shift ;;
  esac
done

current_repo() {
  "$GH" repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null \
    || { echo "unresolved-threads: no -R and not in a GitHub repo" >&2; return 2; }
}

# targets: one "owner/repo<TAB>number" per line.
if [[ "$arg" =~ github\.com/([^/]+/[^/]+)/pull/([0-9]+) ]]; then
  targets="${BASH_REMATCH[1]}"$'\t'"${BASH_REMATCH[2]}"
elif [[ "$arg" =~ ^#?([0-9]+)$ ]]; then
  n="${BASH_REMATCH[1]}"
  [[ -n "$repo" ]] || repo="$(current_repo)" || exit 2
  targets="$repo"$'\t'"$n"
elif [[ -z "$arg" ]]; then
  scope=()
  [[ -n "$repo" ]] && scope=(--repo "$repo")
  targets="$("$GH" search prs --author @me --state open --limit 100 "${scope[@]}" \
             --json repository,number --jq '.[] | "\(.repository.nameWithOwner)\t\(.number)"')" \
    || { echo "unresolved-threads: gh search prs failed" >&2; exit 2; }
else
  echo "unresolved-threads: unrecognised argument: $arg" >&2; exit 2
fi

QUERY='query($owner:String!,$name:String!,$number:Int!,$endCursor:String){
  repository(owner:$owner,name:$name){pullRequest(number:$number){
    reviewThreads(first:100,after:$endCursor){
      pageInfo{hasNextPage endCursor}
      nodes{id isResolved isOutdated path line originalLine
        comments(first:1){nodes{author{login} body url}}}}}}}'

rc=0 rows="" seen=""
while IFS=$'\t' read -r r pr; do
  [[ -z "$pr" ]] && continue
  seen+="$r#$pr "
  out="$("$GH" api graphql --paginate -f query="$QUERY" \
         -F owner="${r%/*}" -F name="${r#*/}" -F number="$pr" --jq '
    .data.repository.pullRequest.reviewThreads.nodes[]
    | select(.isResolved | not)
    | .comments.nodes[0] as $c
    | ["'"$r#$pr"'",
       .path + ":" + ((.line // .originalLine // "?") | tostring)
         + (if .isOutdated then " (outdated)" else "" end),
       "@" + ($c.author.login // "ghost"),
       ($c.body | gsub("\\s+"; " ") | gsub("<!--.*?-->|<[^>]+>|!\\[[^]]*\\]\\([^)]*\\)|\\*+"; "")
         | sub("^ +"; "") | .[0:140]),
       $c.url, .id] | @tsv')" \
    || { echo "unresolved-threads: query failed for $r#$pr" >&2; rc=2; continue; }
  [[ -n "$out" ]] && rows+="$out"$'\n'
done <<<"$targets"

if [[ -n "$rows" ]]; then
  printf 'pr\tlocation\tauthor\texcerpt\turl\tthread_id\n%s' "$rows"
elif (( rc == 0 )); then
  echo "No unresolved review threads on: ${seen:-no open PRs}"
fi
exit "$rc"
