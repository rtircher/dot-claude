# dot-claude

My personal [Claude Code](https://code.claude.com) plugin marketplace — the single
source of truth for cross-cutting conventions and workflow skills I want in **every**
project, local and cloud, without re-embedding them per repo.

Project-*specific* facts stay in each repo's `AGENTS.md` / `CLAUDE.md`. This repo
holds only what generalizes.

## Plugins

| Plugin        | What it does                                                                                  |
| ------------- | -------------------------------------------------------------------------------------------- |
| `conventions` | Always-on working-style rules (TDD, git hygiene, review gates, no-heredoc, model selection), injected into every session via a `SessionStart` hook. Edit [`conventions.md`](plugins/conventions/conventions.md). |
| `dev`         | On-demand software-development tooling: the `design-doc`, `adversarial-review`, and `autonomous-feature` **skills**, the `/dev:babysit`, `/dev:pr-pruner`, and `/dev:post-merge-sweeper` PR-loop **commands** plus the `/dev:handover` + `/dev:takeover` session-continuity ones and the `/dev:init-cloud-parity` **cloud-parity scaffold**, and the `coder` (worktree-isolated) + `researcher` (read-only) **agents** for parallel subagent work. |

## Enable it

Register the marketplace and turn on the plugins in a `settings.json` —
`~/.claude/settings.json` for **all local projects at once**, or a repo's committed
`.claude/settings.json` so **cloud sessions** of that repo pick it up too:

```json
{
  "extraKnownMarketplaces": {
    "dot-claude": { "source": { "source": "github", "repo": "rtircher/dot-claude" } }
  },
  "enabledPlugins": {
    "conventions@dot-claude": true,
    "dev@dot-claude": true
  }
}
```

Cloud sessions fetch this from GitHub, which is on the default Trusted network
allowlist — no setup script or auth needed while this repo stays public.

## Cloud-parity scaffold

The `dev` plugin carries the canonical **cloud-session-parity seed** (under
`plugins/dev/scaffold/cloud-parity/`) plus a `/dev:init-cloud-parity` scaffold that
vendors it into a consumer repo, so cloud (web) sessions behave like local ones:
apt fixes, a lazy toolchain hook, an in-session plugin rescue, a conventions
backstop, and a doctor. The generic `cloud-setup.sh` also calls an OPTIONAL
repo-authored `scripts/cloud-setup-local.sh` for work that needs root at
container-build time (apt system packages, a native build toolchain), so the
vendored setup script stays byte-identical while repo-specific root setup lives in
a file the scaffold never overwrites. dot-claude is the scaffold *source*, never a
runtime dependency: everything on the cold-start path is committed into the
consumer's clone.

- Run `/dev:init-cloud-parity` **locally** in a consumer repo to vendor or refresh
  the seed. It merges `.claude/settings.json` conservatively (owns only
  `extraKnownMarketplaces` plus a touch-if-absent SessionStart hook) and writes a
  starter recipe file.
- `init-cloud-parity.sh --check` is the network-free drift gate: it flags a vendored
  copy that differs from the canonical seed and warns when `enabledPlugins` names a
  plugin with no clone recipe.
- `bash plugins/dev/scaffold/tests/run-tests.sh` is the manual test gate for changes
  to the seed or scaffold (bash -n, shellcheck, and the fake-harness suites).

## Versioning

Neither `plugin.json` declares a `version`, so on a git-hosted marketplace **every
commit is a new version** — edits propagate to all consuming projects automatically.
If you ever pin a `version`, you must bump it on every release or consumers stop
seeing updates.

## Develop / validate locally

```sh
# Add this checkout as a local marketplace and install from it
claude plugin marketplace add ./
claude plugin install conventions@dot-claude
claude plugin install dev@dot-claude

# Validate before pushing
claude plugin validate .                      # marketplace.json
claude plugin validate ./plugins/conventions  # plugin.json + hook syntax
claude plugin validate ./plugins/dev          # plugin.json + skill frontmatter
```

## Updating an installed copy

An *installed* plugin is pinned to a marketplace commit (see `claude plugin list`),
so new commits are **not** picked up automatically — not even from a local
`directory` source. To pull the latest into an installed copy:

```sh
claude plugin marketplace update dot-claude     # re-read the marketplace from its source
claude plugin update conventions@dot-claude     # bump each plugin (the <plugin> arg is required)
claude plugin update dev@dot-claude
# then restart Claude Code to apply
```

`hooks/` changes likewise only take effect after the restart (or `/reload-plugins`).
Cloud sessions and the GitHub-source consumer pull from `main` on GitHub, so a change
must be merged + pushed there before `claude plugin update` can fetch it.
