#!/usr/bin/env bash
#
# update-plugins: the owner's local release step for the dot-claude marketplace.
#
# 1. The marketplace is a `directory` source pointing at the main checkout, and
#    `marketplace update` never pulls. So pull first, or the update is a no-op.
# 2. Repos that commit `enabledPlugins` for @dot-claude get a project-scope
#    entry in installed_plugins.json, pinned to the version current when it was
#    created. `plugin update --scope user` never touches those, so prune them;
#    Claude Code recreates each one at the current version on the repo's next
#    session.
#
# Other setups: use the manual commands in README.md.

set -euo pipefail

plugins_dir="${HOME:?HOME must be set}/.claude/plugins"
installed_file="$plugins_dir/installed_plugins.json"

refuse() { echo "update-plugins: $*" >&2; exit 1; }

# Step 1: fast-forward the checkout, refusing anything that isn't a clean main.
source_type="$(jq -r '.["dot-claude"].source.source // empty' "$plugins_dir/known_marketplaces.json" 2>/dev/null || true)"
[ "$source_type" = "directory" ] ||
  refuse "dot-claude is not a local directory source; use the manual commands in README.md"

checkout="$(jq -r '.["dot-claude"].source.path' "$plugins_dir/known_marketplaces.json")"
git -C "$checkout" rev-parse --git-dir >/dev/null 2>&1 ||
  refuse "$checkout does not exist or is not a git repository"
[ -z "$(git -C "$checkout" status --porcelain --untracked-files=no)" ] ||
  refuse "$checkout has uncommitted changes"
branch="$(git -C "$checkout" rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || refuse "$checkout is on '$branch', not main"

echo "update-plugins: fast-forwarding $checkout"
git -C "$checkout" pull --ff-only

# Step 2: re-read the marketplace index.
echo "update-plugins: updating marketplace index"
claude plugin marketplace update dot-claude

if [ ! -f "$installed_file" ]; then
  echo "update-plugins: no installed_plugins.json; nothing to update or prune"
  exit 0
fi

# Step 3: bump every @dot-claude plugin installed at user scope. -y accepts a
# marketplace-declared install command when there is no TTY.
jq -r '.plugins | to_entries[]
  | select((.key | endswith("@dot-claude")) and any(.value[]; .scope == "user"))
  | .key' "$installed_file" |
  while read -r plugin; do
    echo "update-plugins: updating $plugin"
    claude plugin update "$plugin" --scope user -y
  done

# Step 4: back up, then drop @dot-claude project-scope entries. Write to a temp
# file and mv, so a failed write can't corrupt installed_plugins.json.
cp "$installed_file" "$installed_file.bak"
tmp_file="$(mktemp "$installed_file.tmp.XXXXXX")"
jq '.plugins |= with_entries(
      if (.key | endswith("@dot-claude")) then .value |= map(select(.scope != "project")) else . end
    )' "$installed_file" >"$tmp_file"
mv "$tmp_file" "$installed_file"

echo "update-plugins: pruned project-scope entries (backup: $installed_file.bak); user-scope versions:"
jq -r '.plugins | to_entries[] | select(.key | endswith("@dot-claude"))
  | .key as $k | .value[] | select(.scope == "user") | "  \($k): \(.version)"' "$installed_file"
echo "update-plugins: restart every running Claude Code session to apply"
