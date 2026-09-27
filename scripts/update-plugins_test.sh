#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../plugins/dev/scaffold/tests/lib.sh
. "$here/../plugins/dev/scaffold/tests/lib.sh"
script="$here/update-plugins.sh"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME=Test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=Test GIT_COMMITTER_EMAIL=test@example.com

# make_checkout <dir>: a git repo on main whose bare origin is one commit ahead.
make_checkout() {
  git init -q --bare -b main "$1.origin.git"
  git init -q -b main "$1"
  git -C "$1" commit -q --allow-empty -m "initial"
  git -C "$1" remote add origin "$1.origin.git"
  git -C "$1" push -q -u origin main
  git clone -q "$1.origin.git" "$1.writer"
  git -C "$1.writer" commit -q --allow-empty -m "newer"
  git -C "$1.writer" push -q origin main
  rm -rf "$1.writer"
}

# make_claude <bindir> <log> <checkout> [fail-pattern]: a fake claude that logs
# "<checkout HEAD> | <argv>" and exits 1 when argv matches fail-pattern.
make_claude() {
  mkdir -p "$1"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'echo "$(git -C %q rev-parse HEAD 2>/dev/null) | $*" >> %q\n' "$3" "$2"
    [ -n "${4:-}" ] && printf 'case "$*" in *%q*) exit 1 ;; esac\n' "$4"
    printf 'exit 0\n'
  } >"$1/claude"
  chmod +x "$1/claude"
}

# setup <name> [fail-pattern]: a fake HOME with a directory-source marketplace
# and installed plugins, a checkout, and a fake claude. Sets home, checkout,
# log, installed.
setup() {
  home="$(make_fake_home "$work/$1/home")"
  checkout="$work/$1/checkout"
  log="$work/$1/claude.log"
  installed="$home/.claude/plugins/installed_plugins.json"
  make_checkout "$checkout"
  make_claude "$work/$1/bin" "$log" "$checkout" "${2:-}"
  : >"$log"
  jq -n --arg p "$checkout" '{"dot-claude": {"source": {"source": "directory", "path": $p}}}' \
    >"$home/.claude/plugins/known_marketplaces.json"
  jq -n '{version: 2, plugins: {
    "conventions@dot-claude": [
      {scope: "user", version: "aaa111"},
      {scope: "project", projectPath: "/repo/one", version: "old111"},
      {scope: "project", projectPath: "/repo/two", version: "old222"}],
    "dev@dot-claude": [
      {scope: "user", version: "aaa111"},
      {scope: "project", projectPath: "/repo/one", version: "old111"}],
    "superpowers@claude-plugins-official": [
      {scope: "user", version: "5.1.0"},
      {scope: "project", projectPath: "/repo/one", version: "5.1.0"}]}}' >"$installed"
}

# run <name>: the script with the fake HOME and the fake claude first on PATH.
run() { out="$(HOME="$home" PATH="$work/$1/bin:$PATH" bash "$script" 2>&1)"; rc=$?; }

scopes_of() { jq -r --arg k "$1" '.plugins[$k] | map(.scope) | join(",")' "$installed"; }

# assert_refused <needle> <label>: exit 1, message, and nothing touched.
assert_refused() {
  assert_eq "$rc" "1" "$2: exits 1"
  assert_contains "$out" "$1" "$2: explains why"
  assert_eq "$(cat "$log")" "" "$2: claude never called"
  assert_eq "$(scopes_of conventions@dot-claude)" "user,project,project" "$2: nothing pruned"
}

echo "case: happy path"
setup happy
origin_sha="$(git --git-dir="$checkout.origin.git" rev-parse HEAD)"
run happy
assert_eq "$rc" "0" "exits 0"
assert_eq "$(git -C "$checkout" rev-parse HEAD)" "$origin_sha" "checkout fast-forwarded"
assert_contains "$(head -1 "$log")" "$origin_sha | plugin marketplace update dot-claude" "marketplace update runs first, after the pull"
assert_contains "$(cat "$log")" "plugin update conventions@dot-claude --scope user -y" "conventions bumped"
assert_contains "$(cat "$log")" "plugin update dev@dot-claude --scope user -y" "dev bumped"
assert_eq "$(scopes_of conventions@dot-claude)" "user" "conventions project entries pruned"
assert_eq "$(scopes_of dev@dot-claude)" "user" "dev project entries pruned"
assert_eq "$(scopes_of superpowers@claude-plugins-official)" "user,project" "other marketplaces untouched"
assert_eq "$(jq -r '.plugins["conventions@dot-claude"] | map(.scope) | join(",")' "$installed.bak")" \
  "user,project,project" "backup holds the pre-prune file"

echo "case: no installed_plugins.json"
setup none
rm "$installed"
run none
assert_eq "$rc" "0" "exits 0"
assert_contains "$out" "nothing to update or prune" "says so"

echo "case: untracked file in the checkout"
setup untracked
echo x >"$checkout/untracked.txt"
run untracked
assert_eq "$rc" "0" "does not block the pull"

echo "case: modified tracked file"
setup dirty
echo x >"$checkout/tracked.txt"
git -C "$checkout" add tracked.txt
run dirty
assert_refused "uncommitted" "dirty checkout"

echo "case: checkout not on main"
setup branch
git -C "$checkout" checkout -q -b other
run branch
assert_refused "not main" "non-main checkout"

echo "case: checkout path missing"
setup missing
rm -rf "$checkout"
run missing
assert_refused "not a git repository" "missing checkout"

echo "case: non-directory marketplace source"
setup github
jq -n '{"dot-claude": {"source": {"source": "github", "repo": "rtircher/dot-claude"}}}' \
  >"$home/.claude/plugins/known_marketplaces.json"
run github
assert_refused "README" "non-directory source"

echo "case: claude plugin update fails"
setup failing "plugin update"
before="$(cat "$installed")"
run failing
assert_eq "$rc" "1" "exits 1"
assert_contains "$(cat "$log")" "plugin update conventions@dot-claude" "failed at plugin update, not earlier"
assert_eq "$(cat "$installed")" "$before" "installed_plugins.json untouched"
assert_eq "$([ -e "$installed.bak" ] && echo yes || echo no)" "no" "no backup written"

finish "update-plugins"
