# quests

A shared, per-repo quest log for Claude Code. Every session in a repo sees the same main quests and quests, takes the one it works on, and files side quests instead of losing them. The data lives on a git branch, not in the working tree, so it never dirties your code.

Wording: a goal is a "main quest", a ticket is a "quest". A side quest is a quest filed under the one you are on.

## Install

This repo is a plugin marketplace and `quests` has an entry in `.claude-plugin/marketplace.json`:

```
/plugin marketplace add <this-repo>
/plugin install quests@dot-claude
```

Requires `python3` (standard library only) and `git`.

## Setup

In a repo, tell Claude "set up quests" (the `log` skill, `/quests:log`, walks through it), or run `quest init --mode same|external [--url URL]`.

- Same repo: the log lives on branch `claude/quests` of the code repo's own remote.
- External: the log lives on branch `quests/<slug>` of a separate repo you name with `--url`.

Cloud sessions find an external log through the environment variable `CLAUDE_QUESTS_REPO=<url>`. Same-repo logs need nothing extra.

Note: pushed quest content (titles, notes, links) is visible to anyone with access to that remote. Do not put secrets in the log, and use a private external repo if the code repo is public.

## Commands

- `/quests` opens the Quest log pane (desktop app): main quests, live sessions, and next quests at a glance.
- `/quests:log` is the skill Claude uses to read and update the log. It also triggers on its own when you ask "what's next" or park a side quest.

The skill must not be named `quests`: a skill named after its plugin takes the bare `/quests`, and the engine then refuses to register the pane command. `hooks/commands.test.mjs` guards this.

## State

Per-machine state (session heartbeats, checkouts, hook error log) is kept under `${QUESTS_STATE_DIR:-$HOME/.claude/state/quests}`. Nothing is written inside the plugin directory or the code repo's working tree.

## CLI reference

All commands accept `--json` and `--session <id>`. Session id falls back to `$QUESTS_SESSION_ID`, then `$CLAUDE_CODE_SESSION_ID`. Other environment variables: `QUESTS_SESSION_LABEL`, `QUESTS_WHERE`, `CLAUDE_QUESTS_REPO`, `QUESTS_STATE_DIR`.

| Command | Purpose |
| --- | --- |
| `quest init --mode same\|external [--url URL]` | Create or adopt the quest log |
| `quest log [--next-limit N]` | Main quests, in-progress work, next up, stale claims |
| `quest next` | The next ready quest |
| `quest show <id>` | One quest with its log |
| `quest add <title> [--main G] [--parent ID] [--link L]` | Create a quest |
| `quest side <title> [--link L]` | Create a quest under the quest this session is on |
| `quest take <id>` | Take a quest (takes over only a stale claim) |
| `quest drop <id>` | Give a quest back |
| `quest done <id>` | Mark done; if the parent is not done, prints how to go back to it |
| `quest status <id> <status>` | `todo`, `in_progress`, `blocked`, `done`, `dropped` |
| `quest note <id> <text>` | Append a note |
| `quest link <id> <link>` | Attach a doc or URL |
| `quest main add <title> [--link L]` / `quest main list` | Manage main quests |
| `quest sync` | Fetch and push now |
| `quest html [--out PATH]` | Write the whole log as one HTML page |

`quest side` needs a current quest (one this session has taken and not finished); without one it exits 2 and says to use `quest add`.

Exit codes: 0 ok, 1 error, 2 no quest log (or no current quest for `side`), 3 take refused, 4 setup refused, 5 busy.

## Known limits

- The pane cannot jump to another session.
- Stop hook firing, `CLAUDE_ENV_FILE` export visibility, and `additionalContext` delivery were verified from documentation only, not against a live platform. See `docs/platform-notes.md`.
