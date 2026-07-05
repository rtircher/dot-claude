---
description: Load this repo's latest handover into the session on demand (non-destructive read; finds branch-carried cloud handovers too)
allowed-tools: Bash(ls:*), Bash(git rev-parse:*), Bash(git branch:*), Bash(git fetch:*), Bash(git for-each-ref:*), Bash(git ls-tree:*), Bash(git show:*), Bash(git ls-remote:*), Bash(git merge-base:*), Bash(git switch:*), Bash(git log:*), Read, Task
---

Pull the most recent handover for THIS repo (written by `/dev:handover` or
`/dev:respawn`) into the session to orient from it, then stop for the user's go-ahead.
Non-destructive: it never moves, renames, or deletes anything, so it works any time, as
many times as you like.

Handovers arrive two ways: as **state files** under `~/.claude/state/handover/`
(local sessions, shared filesystem) or **branch-carried** on a pushed throwaway
`handover/<slug>` branch (written by `/dev:respawn`'s cloud flow, because cloud
containers share no filesystem; see "Why the cloud flow differs" in respawn.md for
the full rationale). This command consumes both.

## 1. Find this repo's handover

- Repo key: basename of the **main** repo, shared across worktrees:
  `` basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" `` (`default` if not in a repo).
- If this session was spawned by `/dev:respawn`, your prompt names the exact handover
  file: read that. Otherwise discover it: take the **newest** (by mtime) of
  `~/.claude/state/handover/<repo-key>.md` and any
  `~/.claude/state/handover/<repo-key>-*.md` (respawn writes per-session unique files
  there).
- If the live dir has none and the repo has an `origin`, look for **branch-carried
  handovers**:
  - Fetch them:
    `git fetch origin '+refs/heads/handover/*:refs/remotes/origin/handover/*'`
    (tolerate failure or zero matches).
  - Enumerate newest-first:
    `git for-each-ref --sort=-committerdate --format='%(refname:short) %(committerdate:iso8601)' refs/remotes/origin/handover/`.
  - Exactly one candidate: take it. Several (cleanup is allowed to leave consumed
    ones behind when the git proxy rejects deletion): list branch, date, and each
    doc's `Task & goal` first line, and ask the user which to resume; never silently
    auto-pick among multiple.
  - Read the doc **without switching branches**: find its path with
    `git ls-tree -r --name-only origin/handover/<slug> -- docs/handovers/`
    (a pathspec, deliberately not a `| grep` pipe, which permission prefix-matching
    would reject). Then `git show origin/handover/<slug>:<path>`. If the convention
    path `docs/handovers/` is empty, list the branch's `.md` files with the same
    `ls-tree` minus the pathspec and ask the user; do not guess. **Never check out a
    `handover/*` branch**; it is a throwaway carrier.
- If still nothing, fall back to the newest
  `~/.claude/state/handover-archive/<repo-key>-*.md` (timestamped names sort
  lexically, so the last one is newest).
- If none exists anywhere, say so and stop.

## 2. Sanity-check before resuming

`Read` the chosen file (a branch-carried handover has no file; you already have its
content from `git show` in step 1), then guard against stale / cross-repo state:

- **Repo match, keyed to where the handover was found:**
  - Found under `~/.claude/state`: confirm the `Repo:` line matches the current main
    repo root (`` dirname "$(git rev-parse --path-format=absolute --git-common-dir)" ``),
    as before.
  - Branch-carried: its `Repo:` line holds `<owner>/<repo>`, not a path (container
    paths do not survive; raw origin URLs differ per environment, SSH locally vs an
    `http://local_proxy@127.0.0.1:<port>/git/...` proxy URL in cloud). Compare it
    against the current origin normalized the same way: take
    `git ls-remote --get-url origin`, strip a trailing `.git` and trailing slashes,
    keep the last two path components (after the `:` for scp-style SSH URLs).
  - On a mismatch either way, warn, summarise what you found, and do NOT switch
    branches. Ask the user how to proceed.
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

For a **branch-carried** handover, additionally:

- The `Branch:` branch may not exist locally yet; create it from the remote
  (`git switch feat/<slug>` sets up tracking from `origin/feat/<slug>` after a
  `git fetch origin feat/<slug>`).
- Verify the `## Respawn` section's `Base commit:` is the branch tip **or an
  ancestor of it**: `git merge-base --is-ancestor <base-sha> HEAD`. On failure, STOP
  and report; never fall through to another branch. The ancestor form (not strict
  equality) keeps re-resume legal: the work branch starts exactly at base, but a
  previous resume may have already committed on top of it, in which case trust the
  branch state over the handover's `Next steps`.

(The resume prompt printed by cloud respawn duplicates this fetch / show / switch /
ancestor-verify / bootstrap / stop / cleanup procedure inline, so it works even where
this plugin is not loaded. **Keep the two in sync when editing either**; the template
lives in respawn.md step C5.)

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

For a branch-carried handover, two extras belong in that status. If its `## Respawn`
section names a fresh-clone bootstrap (e.g. `make deps`), run it before presenting
status, this being a fresh clone. And surface the handover's cleanup rule as a
suggested next step, since this command stays non-destructive and never deletes the
carrier branch itself: after the user's go-ahead they (or you, once confirmed) can
`git push origin --delete handover/<slug>`; if the cloud git proxy rejects it ("the
remote end hung up unexpectedly"), deleting from the GitHub UI or leaving it are both
fine, as `handover/` branches are disposable by convention.
