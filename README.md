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
| `dev`         | On-demand software-development tooling: the `adversarial-review` and `autonomous-feature` **skills**, the `/dev:handover` + `/dev:takeover` session-continuity **commands**, and the `coder` (worktree-isolated) + `researcher` (read-only) **agents** for parallel subagent work. |

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
