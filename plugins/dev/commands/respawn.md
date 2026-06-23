---
description: Respawn this session into a fresh, meaningfully named one. Writes a handover, then spawns a clean session that resumes the work in its own worktree
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git worktree list:*), Bash(git add:*), Bash(git commit:*), Bash(mkdir -p:*), Bash(date:*), Bash(ls:*), Bash(mv:*), Write, mcp__ccd_session__spawn_task
---

Collapse the `handover` then `clear` then `takeover` ritual into one step. This writes
a handover (as `/dev:handover` does), then spawns a brand-new session that is **named at
birth** and pre-seeded to resume the work in its **own clean worktree**, forked off your
committed state. The goal is a fresh, uncluttered context without losing anything.

Why a new session rather than an in-place clear: `/clear` and `/rename` are user-only,
so the model cannot reset or retitle the current session. A *new* session, by contrast,
can be named at creation. That is the lever this command pulls.

## 1. Gather state and check preconditions

Repo key (shared across worktrees) is the basename of the **main** repo:
`` basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" ``.
Note the main root path too (`` dirname "$(git rev-parse --path-format=absolute --git-common-dir)" ``).
Ground everything in fact: `git status`, `git branch --show-current`, `git diff --stat`,
`git log --oneline -5`, `git worktree list`. Do not guess.

**Stop early if respawn does not apply:**
- **Not a git repo** (the `git rev-parse` above fails): respawn needs a repo to fork
  from. Say so and stop.
- **Nothing to hand off** (clean tree, no feature work in progress, no resumable task):
  there is nothing to respawn into. Surface this and confirm with the user before going on.

## 2. Commit-first gate

The new session lands in its **own fresh worktree** and can only see what is committed
(worktrees share the same git object store, so a local commit is reachable there without
a push). Anything not committed does not travel.

So if `git status` shows uncommitted changes, **stop and ask the user**, offering:

- **Commit now** (recommended): commit the in-progress work to the current branch with a
  clear conventional message (a `wip:` checkpoint is fine; squash later). **Stage
  deliberately** rather than blanket `git add -A`: prefer `git add -u` for tracked
  changes and add only the new files you mean to keep, so secrets, build output, or
  scratch files are not swept in.
- **Respawn anyway**: proceed without committing. **Warn loudly** that the new session
  will NOT see the uncommitted changes; they stay stranded in this worktree.
- **Cancel**: stop and do nothing.

Also warn, either way, that the fresh worktree starts clean: gitignored / local artifacts
(env files, `node_modules`, build output, tool caches) will not exist there and may need
rebuilding.

Capture the resulting tip: `` git rev-parse HEAD `` (call it `<base-sha>`). The new
session forks off it.

## 3. Pick names (and reserve the branch)

Derive a short kebab-case `<slug>` from the handover's `Task & goal` (lowercased,
non-alphanumeric runs to `-`, trimmed to ~40 chars), e.g. `respawn-command`. From it:

- **Branch:** `feat/<slug>` (or `fix/<slug>` for a bugfix).
- **Session title:** a readable form, e.g. "respawn command".

`feat/<slug>` must be free, since the new session creates it. Check
`git branch --list "feat/<slug>"` (and `git worktree list`); on any collision, pick a
distinct slug or ask the user. Do not proceed with a name that already exists.

## 4. Write the handover

Write to a **per-respawn unique path** so concurrent respawns never clobber each other:
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`, where `<ts>` is
`date -u +%Y%m%dT%H%M%SZ`. The timestamp is what guarantees uniqueness: `<slug>` alone is
not enough, because the branch is not reserved until the new session forks (step 5), so two
concurrent respawns can derive the same slug. Each spawn prompt (step 5) points the new
session at its own file by exact path.

`mkdir -p ~/.claude/state/handover ~/.claude/state/handover-archive`. To bound
accumulation **without** disturbing a sibling respawn still waiting for its chip, archive
only *already-consumed* prior handovers: for each existing
`~/.claude/state/handover/<repo-key>-*.md`, read its `Branch:` line and, **only if that
branch already exists** (`git branch --list <branch>` is non-empty, meaning that respawn
already forked), move it to
`~/.claude/state/handover-archive/<basename>-$(date -u +%Y%m%dT%H%M%SZ).md`. Leave any
handover whose branch does not yet exist in place: it is still pending. Never touch the
shared `~/.claude/state/handover/<repo-key>.md` slot; that one belongs to plain
`/dev:handover`.

Then write `~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`, with a real UTC timestamp
(`date -u +%Y-%m-%dT%H:%M:%SZ`) inside the doc as well.

Use `/dev:handover`'s sections, but **record `feat/<slug>` as the `Branch:` line, not the
current branch** (this is the branch the new session will be on, so `/dev:takeover` sees
it is already there and does not try to switch or redirect). The `Repo:` line must be the
main repo root verbatim (`/dev:takeover` checks it). Keyed lines `Repo:`, `Branch:`, and
the `## Respawn` `Base commit:` are mandatory and parsed downstream.

The handover is the **single source of truth** for the base commit, the destination
branch, and the worktree to prune. The spawn prompt (step 5) points at these rather than
repeating them, so the two cannot drift. Record the current worktree path
(`git rev-parse --show-toplevel`) on the `Stale worktree:` line, so the resumed session
knows exactly which worktree to clean up once this one is archived.

```markdown
# Session handover: <ISO 8601 UTC timestamp>
Repo: <main repo root path>
Branch: feat/<slug>

## Task & goal
What this session is doing and why.

## Current state
Committed vs in-progress, what's done vs next. Note what's already **verified**
(tests green, build passing) so the resumed session doesn't redundantly re-run it.

## Key decisions
Non-obvious context: approaches ruled out, constraints learned.

## Key files & pointers
The specific files (with `path:line` refs), entry points, and commands the next steps
touch, so the resumed session can act without re-discovering the codebase.

## Next steps
Concrete actions to resume, in order. Cite exact `path:line` for each.

## Open questions / blockers
What's unresolved or waiting on input.

## Respawn
Base commit: <base-sha>
Stale worktree: <current worktree path>
You are a fresh session in your own new worktree. Create the branch named on the `Branch:`
line off the base commit above, and continue there. Do NOT switch into or work inside any
other worktree while this session's original one may still be live: it may be mid-archive
and must not be disturbed. Once the user confirms that old session is closed, you may prune
its now-stale worktree with `git worktree remove <Stale worktree>` from your own worktree.
```

## 5. Spawn the fresh session

Call `spawn_task` (`mcp__ccd_session__spawn_task`) with `title` = the session title from
step 3 (this becomes the new session's name), a one-line `tldr`, and a `prompt` built from
this template. Interpolate `<main repo root path>`, the full handover path from step 4
(`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`), and the `Task:` summary. Do **not**
embed the branch name or base commit here: they live solely in the handover, so the prompt
and handover cannot drift. The new session has no memory of this one.

```
Resume work in this repo. You are a fresh session in your own new worktree, with no prior
context beyond this message and the handover doc.

Repo: <main repo root path>
Handover: ~/.claude/state/handover/<repo-key>-<slug>-<ts>.md

Do these in order:
1. Read the handover. Note its `Branch:` (the branch to create) and the `Base commit:`
   under its `## Respawn` section (the commit to fork from). Those two values are the
   single source of truth; this prompt deliberately does not repeat them.
2. Confirm that base commit is reachable: `git rev-parse --verify <base>^{commit}`.
   If it is missing, STOP and report; do not continue.
3. Create that branch off it: `git switch -c <branch> <base>`. If this errors (e.g. the
   branch already exists), STOP and report. Do NOT fall through onto another branch or
   into another worktree.
4. Run `/dev:takeover` to load the handover and orient. It reads the handover, does only
   the targeted file reads the handover cites (delegating any broad context rebuild to a
   subagent), then presents a short status and **stops for your go-ahead**. It does not
   start working on its own. You are already on that branch, so its branch-switch is a
   no-op; never switch into another worktree. `/dev:takeover` detects this respawn handover
   (it has a `## Respawn` section and you are on its branch) and skips its rename step on
   its own, since this session is already named.

Task: <one-paragraph summary of the work and the immediate next step, so you can act cold>.
```

If the `spawn_task` call fails, tell the user: the handover is already written (at
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`), so they can open a fresh session
manually, read the `Branch:` and `## Respawn` base commit from it, run
`git switch -c <branch> <base>`, then `/dev:takeover`. Nothing is lost.

## 6. Hand off

Tell the user plainly:

- A chip is showing. **Click it** to launch the fresh, named session. It is one click;
  there is no way to auto-launch a foreground session. If the chip is missed, the work is
  safe (committed) and `/dev:takeover` resumes it manually.
- The committed work is safe the moment it was committed: it lives in the shared git
  object store, reachable via the branch and reflog, and closing this session removes only
  its worktree, not the commit. The one rule: do not delete the original branch until the
  new session has created `feat/<slug>`. In practice, wait until the new session has
  resumed and forked, then **archive/close this session** freely.
- **Worktrees do not self-clean.** `/dev:respawn` removes nothing, and a session cannot
  remove the worktree it is running in, so this session's worktree (plus any trial
  worktrees from earlier attempts) outlives it. After the new session has forked and you
  have archived this one, prune the leftovers: run `git worktree remove <path>` yourself
  from the main repo, or just confirm to the resumed session that this session is closed
  and let it remove the stale worktree (its handover records the path).
