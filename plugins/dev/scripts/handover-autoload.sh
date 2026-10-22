#!/usr/bin/env bash
# SessionStart hook (matcher `clear`): after `/dev:handover` then `/clear`, load the
# handover into the fresh context so the next message resumes without
# `/dev:takeover`. Acts only on a plain `LOCAL` handover (`<key>.md`, what
# /dev:handover writes) younger than HANDOVER_AUTOLOAD_MAX_AGE_MIN minutes
# (default 15, 0 turns it off); several sessions can share a machine, and the age
# guard keeps an ordinary `/clear` from picking up an unrelated handover. A respawn
# handover belongs to the session respawn started, and BRANCH/ARCHIVE/NONE stay
# with /dev:takeover. Read-only, never fetches, and silent with exit 0 on any
# failure so a broken hook never gets in the way of a session.

exec 2>/dev/null
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) || exit 0
plugin_root=$(cd "$here/.." && pwd) || exit 0
max_min=${HANDOVER_AUTOLOAD_MAX_AGE_MIN:-15}
[[ "$max_min" =~ ^[0-9]+$ ]] || max_min=15
max_min=$((10#$max_min)) # `08` is not octal
# Over this, Claude Code cuts additionalContext to a preview Claude is never asked
# to expand, so a larger handover is pointed at instead of inlined.
cap=10000

# The matcher already limits this to `clear`; checking `source` again keeps a
# mis-wired matcher from loading a handover into a new or resumed session.
input=$(python3 -c 'import json, sys; d = json.load(sys.stdin); print(d.get("source", "")); print(d.get("cwd", ""))') || exit 0
{ read -r src; read -r cwd; } <<<"$input"
[[ "$src" == clear ]] || exit 0
[[ -n "$cwd" ]] && { cd "$cwd" || exit 0; }

found=$(bash "$here/find-handover.sh" --no-fetch) || exit 0
key=$(awk -F'\t' '$1 == "KEY" { print $2 }' <<<"$found")
root=$(awk -F'\t' '$1 == "ROOT" { print $2 }' <<<"$found")
file=$(awk -F'\t' '$1 == "LOCAL" { print $2 }' <<<"$found")
[[ -n "$file" && "$(basename "$file")" == "$key.md" && -r "$file" ]] || exit 0

# GNU stat, then BSD/macOS stat.
mtime=$(stat -c %Y "$file" || stat -f %m "$file") || exit 0
[[ "$mtime" =~ ^[0-9]+$ ]] || exit 0
(($(date +%s) - mtime < max_min * 60)) || exit 0

body=$(<"$file") || exit 0
instructions="# Auto-resume after /clear

This repo's handover was written less than ${max_min} minutes ago, most likely by \`/dev:handover\` just before this \`/clear\`, so resume it here without waiting for \`/dev:takeover\`.

- Handover file: ${file}
- Main repo root: ${root}

On the user's first message, Read steps 2, 4 and 5 of ${plugin_root}/commands/takeover.md and follow them. Skip step 1 (the handover is found) and step 3 (the rename). In short:

1. Check the handover's \`Repo:\` line matches the main repo root above and its branch still exists unmerged. On a mismatch, warn and do not switch branches.
2. Get onto the handover's branch only if you are not already on it, the way step 4 says for jj and plain git, and work from the branch's existing worktree if it has one.
3. Orient from the first Next step only: read just the lines it cites, and do not explore.
4. Present step 5's status block, then stop for the user's go-ahead.

If the first message asks for something unrelated, mention the handover in one line and do what was asked.

Leave the handover file where it is."

if ((${#instructions} + ${#body} + 40 < cap)); then
  context="${instructions}

## Handover

${body}"
else
  context="${instructions}

The handover is too long to inline: Read ${file} before step 1."
fi

json=$(printf '%s' "$context" | python3 -c 'import json, sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": sys.stdin.read()}}))') || exit 0
printf '%s\n' "$json"
