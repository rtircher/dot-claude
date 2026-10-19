---
description: Load this repo's latest handover into the session on demand (non-destructive read; finds branch-carried cloud handovers too)
allowed-tools: Bash(git rev-parse:*), Bash(git branch:*), Bash(git fetch:*), Bash(git show:*), Bash(git merge-base:*), Bash(git switch:*), Bash(git log:*), Bash(jj root:*), Bash(jj new:*), Bash(jj git fetch:*), Bash(jj bookmark track:*), Bash(jj log:*), Read
---

Pull the most recent handover for THIS repo (written by `/dev:handover` or
`/dev:respawn`) into the session to orient from it, then stop for the user's go-ahead.
Non-destructive: it never moves, renames, or deletes anything, so it works any time, as
many times as you like.

Handovers arrive two ways: as **state files** under `~/.claude/state/handover/`
(local sessions, shared filesystem) or **branch-carried** on a pushed throwaway
`handover/<slug>` branch (written by `/dev:respawn`'s cloud flow, because cloud
containers share no filesystem; see "Why the cloud flow differs" in references/respawn-cloud.md for
the full rationale). This command consumes both.

## 1. Find this repo's handover

Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/find-handover.sh"`. One call does the whole
search and prints tab-separated lines: `KEY` (the repo key, basename of the **main**
repo so git worktrees and jj workspaces share it; `default` outside a repo), `ROOT`
(main repo root), `ORIGIN` (origin normalized to `<owner>/<repo>`, empty with no
remote), then the first hit of this order:

- `LOCAL <path>`: the newest state file under `~/.claude/state/handover/`. If this
  session was spawned by `/dev:respawn`, your prompt names the exact file: read that
  one instead.
- `BRANCH <ref> <date> <doc path> <task line>`: branch-carried handovers (written by
  `/dev:respawn`'s cloud flow), newest first, searched only when there is no `LOCAL`.
  Exactly one: take it. Several (cleanup may leave consumed ones behind when the git
  proxy rejects deletion): list ref, date and task line and ask the user which to
  resume; never silently auto-pick. Read the doc **without switching branches**:
  `git show <ref>:<doc path>`. A `-` doc path means the convention path
  `docs/handovers/` is empty: list the branch's `.md` files with `git show <ref>:`
  and ask the user; do not guess. **Never check out a `handover/*` branch**; it is a
  throwaway carrier.
- `ARCHIVE <path>`: newest archived handover, the last resort.
- `NONE`: say so and stop.

## 2. Sanity-check before resuming

`Read` the chosen file (a branch-carried handover has no file; you already have its
content from `git show` in step 1), then guard against stale / cross-repo state:

- **Repo match, keyed to where the handover was found:**
  - Found under `~/.claude/state`: confirm the `Repo:` line matches `ROOT` from step 1.
  - Branch-carried: its `Repo:` line holds `<owner>/<repo>`, not a path (container
    paths do not survive; raw origin URLs differ per environment). Compare it against
    `ORIGIN` from step 1, which is normalized the same way the writer does it.
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
already on it, get onto it. In a jj repo (`jj root` succeeds and `git rev-parse --show-toplevel` fails or prints the same path; a git worktree nested in a jj repo prints its own path, so it is plain git) that is `jj new
<bookmark>`; in plain git `git switch <branch>`, or `git worktree add <path>
<branch>` where a hook blocks switching. If that branch already lives in another
worktree, work from that path instead. Never switch branches on a repo
mismatch. A respawned session is already on its branch, so this is a no-op for it.

For a **branch-carried** handover, additionally:

- The `Branch:` branch may not exist locally yet; create it from the remote. jj:
  `jj git fetch`, `jj bookmark track feat/<slug>@origin` (this creates the local
  bookmark; `jj new feat/<slug>@origin` alone leaves none to set or push), then
  `jj new feat/<slug>`. Plain git: `git fetch origin
  feat/<slug>`, then `git switch feat/<slug>` sets up tracking from
  `origin/feat/<slug>`.
- Verify the `## Respawn` section's `Base commit:` is the branch tip **or an
  ancestor of it**: plain git `git merge-base --is-ancestor <base-sha> HEAD`; jj
  `jj log --no-graph -r '<base-sha> & ::@' -T commit_id` (empty output is a failure;
  a jj workspace has no `.git`). On failure, STOP
  and report; never fall through to another branch. The ancestor form (not strict
  equality) keeps re-resume legal: the work branch starts exactly at base, but a
  previous resume may have already committed on top of it, in which case trust the
  branch state over the handover's `Next steps`.

(The resume prompt printed by cloud respawn duplicates this fetch / show / switch /
ancestor-verify / bootstrap / stop / cleanup procedure inline, so it works even where
this plugin is not loaded. **Keep the two in sync when editing either**; the template
lives in references/respawn-cloud.md step C5.)

## 5. Orient, then stop

The point of a handover is that reading it gets you ready. So **orient; do not start
working.**

- Read only the line ranges the handover cites for the first `Next step`, not every
  cited file in full; the later steps wait for the user's go-ahead.
- Do **not** explore broadly in this session. Re-deriving how a subsystem fits, mapping
  an unfamiliar area, or re-running investigation the handover already records is exactly
  the context bloat that respawning exists to avoid. If the first step is not actionable
  from the handover's pointers, say so in the status and ask instead of exploring.

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
