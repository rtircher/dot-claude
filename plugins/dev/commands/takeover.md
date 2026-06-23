---
description: Load this repo's latest handover into the session on demand (non-destructive read)
allowed-tools: Bash(ls:*), Bash(git rev-parse:*), Bash(git branch:*), Read
---

Pull the most recent handover for THIS repo (written by `/dev:handover`) into the
session and resume from it. Non-destructive: it never moves, renames, or deletes
anything, so it works any time, as many times as you like.

## 1. Find this repo's handover

- Repo key: basename of the **main** repo, shared across worktrees:
  `` basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" `` (`default` if not in a repo).
- Prefer `~/.claude/state/handover/<repo-key>.md`. If absent, fall back to the newest
  `~/.claude/state/handover-archive/<repo-key>-*.md` (timestamped names sort
  lexically, so the last one is newest).
- If neither exists, say so and stop.

## 2. Sanity-check before resuming

`Read` the chosen file, then guard against stale / cross-repo state:

- **Repo match:** confirm the `Repo:` line matches the current main repo root
  (`` dirname "$(git rev-parse --path-format=absolute --git-common-dir)" ``). If it
  doesn't, warn, summarise what you found, and do NOT switch branches — ask the user
  how to proceed.
- **Staleness:** note the handover's timestamp and branch; if the branch is already
  merged or gone, flag that rather than blindly resuming.

## 3. Rename the session

**Skip this step entirely if** the handover has a `## Respawn` section **and** you
are already on its `Branch:`. That combination means `/dev:respawn` spawned this
session and named it at birth, so a rename would only clobber a good title. (A
generic session manually resuming a respawn handover won't be on that branch yet,
so it still falls through to the rename below.)

Otherwise: fresh sessions carry a generic auto-generated title (e.g. "general
coding session"). Retitle this one to reflect the work you're resuming. Pick a
short, kebab-case name derived from the handover's `Task & goal` (or its `Branch`,
minus any `feat/` / `fix/` prefix), e.g. `takeover-session-rename`. Do this only on
a repo match.

The session title is set with `/rename <name>`. If your environment lets you
invoke slash commands, run it. `/rename` is often user-only, though, so if you
can't run it, surface the suggestion instead: in your reply, put the command on
its own line as `` `/rename <name>` `` and ask the user to run it.

## 4. Resume

Open your reply with a short "Resuming from handover:" summary (3-4 lines: what was
in progress and the immediate next step) and name which file you loaded. Then
continue the work.

Only when the repo matches, the named branch exists in this repo, and you are not
already on it: switch to it using this repo's convention (`git switch <branch>`, or
`gt co <branch>` where Graphite is in use). If that branch already lives in another
worktree, work from that path instead. Never switch branches on a repo mismatch.
