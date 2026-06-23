---
description: Load this repo's latest handover into the session on demand (non-destructive read)
allowed-tools: Bash(ls:*), Bash(git rev-parse:*), Bash(git branch:*), Read, Task
---

Pull the most recent handover for THIS repo (written by `/dev:handover` or
`/dev:respawn`) into the session to orient from it, then stop for the user's go-ahead.
Non-destructive: it never moves, renames, or deletes anything, so it works any time, as
many times as you like.

## 1. Find this repo's handover

- Repo key: basename of the **main** repo, shared across worktrees:
  `` basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" `` (`default` if not in a repo).
- If this session was spawned by `/dev:respawn`, your prompt names the exact handover
  file: read that. Otherwise discover it: take the **newest** (by mtime) of
  `~/.claude/state/handover/<repo-key>.md` and any
  `~/.claude/state/handover/<repo-key>-*.md` (respawn writes per-session unique files
  there). If the live dir has none, fall back to the newest
  `~/.claude/state/handover-archive/<repo-key>-*.md` (timestamped names sort lexically,
  so the last one is newest).
- If none exists, say so and stop.

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

## 4. Get on the right branch (only if needed)

Only when the repo matches, the named branch exists in this repo, and you are not
already on it: switch to it using this repo's convention (`git switch <branch>`, or
`gt co <branch>` where Graphite is in use). If that branch already lives in another
worktree, work from that path instead. Never switch branches on a repo mismatch. A
respawned session is already on its branch, so this is a no-op for it.

## 5. Orient, then stop

The point of a handover is that reading it gets you ready. So **orient; do not start
working.**

- Read the specific files the handover's `Next steps` and `Key files & pointers` cite
  (with line refs). Those targeted reads are cheap and expected.
- Do **not** explore broadly in this session. Re-deriving how a subsystem fits, mapping
  an unfamiliar area, or re-running investigation the handover already records is exactly
  the context bloat that respawning exists to avoid. If genuine broad context rebuild is
  needed **and** the handover doesn't already supply it, dispatch a read-only
  `dev:researcher` subagent (via `Task`) and ask for a condensed brief, keeping this
  session lean. Skip the subagent when the handover's pointers already make the next step
  actionable.

Then present a tight, structured status and **stop for the user's go-ahead**. Never
auto-execute the next step:

```
Resuming from handover: <file>
Task:     <one line>
State:    <committed vs in-progress, what's verified>
Next:     <the immediate first action>
Confirm to proceed, or redirect.
```
