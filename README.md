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
| `dev`         | On-demand software-development skills: `adversarial-review` and `autonomous-feature`. Namespaced as `/dev:adversarial-review` etc. |

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

`conventions.md` and skill `SKILL.md` edits take effect immediately; changes to
`hooks/` need `/reload-plugins` or a restart.
