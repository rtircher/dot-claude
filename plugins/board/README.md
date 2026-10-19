# board

A shared, per-repo ticket board for Claude Code. Every session in a repo sees the same goals and tickets, claims what it works on, and files side quests instead of losing them. Board data lives on a git branch, not in the working tree, so it never dirties your code.

## Install

This repo is a plugin marketplace and `board` has an entry in `.claude-plugin/marketplace.json`:

```
/plugin marketplace add <this-repo>
/plugin install board@dot-claude
```

Requires `python3` (standard library only) and `git`.

## Setup

In a repo, tell Claude "set up a board" (the `board` skill walks through it), or run `board init --mode same|external [--url URL]`.

- Same repo: the board lives on branch `claude/board` of the code repo's own remote.
- External: the board lives on branch `board/<slug>` of a separate repo you name with `--url`.

Cloud sessions find an external board through the environment variable `CLAUDE_BOARD_REPO=<url>`. Same-repo boards need nothing extra.

Note: pushed board content (titles, notes, links) is visible to anyone with access to that remote. Do not put secrets on a board, and use a private external repo if the code repo is public.

## State

Per-machine state (session heartbeats, checkouts, hook error log) is kept under `${BOARD_STATE_DIR:-$HOME/.claude/state/board}`. Nothing is written inside the plugin directory or the code repo's working tree.

## CLI reference

All commands accept `--json` and `--session <id>`. Session id falls back to `$BOARD_SESSION_ID`, then `$CLAUDE_CODE_SESSION_ID`.

| Command | Purpose |
| --- | --- |
| `board init --mode same\|external [--url URL]` | Create or adopt the board |
| `board summary [--next-limit N]` | Goals, in-progress work, next up, stale claims |
| `board next` | The next ready ticket |
| `board show <id>` | One ticket with its log |
| `board add <title> [--goal G] [--parent ID] [--link L]` | Create a ticket |
| `board claim <id>` | Claim a ticket (takes over only a stale claim) |
| `board release <id>` | Give a ticket back |
| `board status <id> <status>` | `todo`, `in_progress`, `blocked`, `done`, `dropped` |
| `board note <id> <text>` | Append a note |
| `board link <id> <link>` | Attach a doc or URL |
| `board goal add <title> [--link L]` / `board goal list` | Manage goals |
| `board sync` | Fetch and push now |

Exit codes: 0 ok, 1 error, 2 no board, 3 claim refused, 4 setup refused, 5 busy.

## Known limits

- The pane cannot jump to another session.
- Stop hook firing, `CLAUDE_ENV_FILE` export visibility, and `additionalContext` delivery were verified from documentation only, not against a live platform. See `docs/platform-notes.md`.
