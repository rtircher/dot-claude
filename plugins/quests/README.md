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

## Migrating from the old name

This plugin used to be called `board`. Nothing is lost and nothing is deleted:

- `quest migrate` creates `claude/quests` at the same commit as the old `claude/board` branch (the same remote, no rewrite) and says what it did. If `claude/quests` already exists it says so and does nothing. External logs get `quests/<slug>` from `board/<slug>` the same way, and their config entry is carried over. The old branches are never modified or deleted.
- It also copies the old state directory's config entries into the new one, and moves any non-empty pending journal across so it replays on the next sync.
- At session start, when no quest log is found but a marked old one is, the same migration runs once automatically within a 5 second network budget. If it fails, the session start prints a one-line hint and carries on.

- A config entry that still names an old-style branch is never used as is: it is rewritten to the new branch once that branch is migrated, otherwise skipped. `quest init` refuses while a marked old branch exists, and tells you to run `quest migrate`.
- If the remote cannot be reached, session start says so and retries next session. A journal moved by the session-start migration is pushed by the next normal sync, not by the hook.

After switching:

- Change `"board@dot-claude"` to `"quests@dot-claude"` under `enabledPlugins` in any `settings.json` that lists it.
- Sessions or machines still running the old plugin keep writing to the old branch, and those later writes are not carried over. Update every machine, then run `quest migrate` again if needed (it only acts when the new branch is missing).

The on-disk format inside the branch is unchanged (including the `goal` frontmatter key and the `board.json` marker file), so existing data reads as is.

## State

Per-machine state (session heartbeats, checkouts, hook error log) is kept under `${QUESTS_STATE_DIR:-$HOME/.claude/state/quests}`. Nothing is written inside the plugin directory or the code repo's working tree.

## CLI reference

All commands accept `--json` and `--session <id>`. Session id falls back to `$QUESTS_SESSION_ID`, then `$CLAUDE_CODE_SESSION_ID`. Other environment variables: `QUESTS_SESSION_LABEL`, `QUESTS_WHERE`, `CLAUDE_QUESTS_REPO`, `QUESTS_STATE_DIR`.

| Command | Purpose |
| --- | --- |
| `quest init --mode same\|external [--url URL]` | Create or adopt the quest log |
| `quest migrate` | Carry a log made under the plugin's earlier name over to the quests branch |
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
| `quest move <id> --top\|--bottom\|--up\|--down\|--before ID\|--after ID` | Reorder a quest within its main quest |
| `quest main move <id> (same flags)` | Reorder a main quest |
| `quest sync` | Fetch and push now |
| `quest html [--out PATH]` | Write the whole log as one HTML page |

`quest side` needs a current quest (one this session has taken and not finished); without one it exits 2 and says to use `quest add`.

Exit codes: 0 ok, 1 error, 2 no quest log (or no current quest for `side`, or an unknown id for `done` and `status`), 3 take refused, 4 setup or migration refused, 5 busy.

## Known limits

- The pane cannot jump to another session.
- Stop hook firing, `CLAUDE_ENV_FILE` export visibility, and `additionalContext` delivery were verified from documentation only, not against a live platform. See `docs/platform-notes.md`.
