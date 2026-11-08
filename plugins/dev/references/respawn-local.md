# Respawn: local flow detail

Read by `/dev:respawn` during the local flow (and the manual fallback, which reuses steps 1 to 4 and this file's Step 5 detail for the prompt's step 3).
Each section below is the detail for the same-numbered step in the command.

## Step 2 detail: commit-first mechanics

In a jj repo the dirty check is `jj status` instead (a workspace has no `.git`): jj's working-copy
commit `@` holds uncommitted changes, so a non-empty `@` is a dirty tree.

When the user picks **Commit now**: commit the in-progress work to the current branch with a
clear conventional message (a `wip:` checkpoint is fine; squash later). **Stage
deliberately** rather than blanket `git add -A`: prefer `git add -u` for tracked
changes and add only the new files you mean to keep, so secrets, build output, or
scratch files are not swept in. jj has no staging area, so read `jj status` and
`jj diff --stat` first and keep stray files out of the working copy; then
`jj commit -m '<msg>'`, which moves the work into `@-` and leaves `@` empty.

### Capturing `<base-sha>`

Capture the resulting tip (call it `<base-sha>`): `` git rev-parse HEAD ``, or in a jj
repo `` jj log --no-graph -r @- -T commit_id ``. The new session forks off it. In jj,
`@-` is the tip only when the work sits in `@-` and `@` is empty: after a bare
`jj describe -m ...` the work is still in `@` and `@-` is its parent, one commit too
early, and the new session would silently miss the work. So first get the work out of
`@` (`jj commit -m '<msg>'`, or `jj describe -m '<msg>'` then `jj new`), then check
`` jj log --no-graph -r @ -T empty `` prints `true`, and only then read `@-`. If it
prints `false`, commit again; do not read `@-`. After a **Respawn anyway** choice `@` is
non-empty by design and `@-` is still the right base; the warning above stands.

## Step 4 detail: handover file

To bound accumulation **without** disturbing a sibling respawn still waiting to
start, archive only *already-consumed* prior handovers: run
`bash "${CLAUDE_PLUGIN_ROOT}/scripts/handover-archive-sweep.sh"` (add `--dry-run` to
preview). It moves each `~/.claude/state/handover/<repo-key>-*.md` whose `Branch:`
already exists into `~/.claude/state/handover-archive/` and leaves pending ones
(branch not yet created) alone. It never touches the shared
`~/.claude/state/handover/<repo-key>.md` slot; that one belongs to plain
`/dev:handover`.

Then `mkdir -p ~/.claude/state/handover` if needed and write
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`, with a real UTC timestamp
(`date -u +%Y-%m-%dT%H:%M:%SZ`) inside the doc as well.

Use `/dev:handover`'s sections, but **record `feat/<slug>` as the `Branch:` line, not the
current branch** (this is the branch the new session will be on, so `/dev:takeover` sees
it is already there and does not try to switch or redirect). The `Repo:` line must be the
main repo root verbatim (`/dev:takeover` checks it). Keyed lines `Repo:`, `Branch:`, and
the `## Respawn` `Base commit:` are mandatory and parsed downstream.

The handover is the **single source of truth** for the base commit, the destination
branch, and the worktree to prune. The spawn prompt (step 5) points at these rather than
repeating them, so the two cannot drift. Record the current worktree path
(`git rev-parse --show-toplevel`; in a jj workspace, `jj root`) on the `Stale worktree:`
line, so the resumed session knows exactly which worktree to clean up once this one is
archived. For a jj workspace also record its name, which cleanup needs:
`jj log --no-graph -r @ -T working_copies` prints `<name>@` (several names only if
workspaces share one working copy: take the one whose `jj workspace root --name <name>`
is `jj root`). Write `Stale worktree: <jj root> (jj workspace <name>)`.

```markdown
# Session handover: <ISO 8601 UTC timestamp>
Repo: <main repo root path>
Branch: feat/<slug>
Quest: <quest id and title, or none>

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
its now-stale worktree from your own worktree. A git worktree: `git worktree remove
<Stale worktree>`. A jj workspace (the line says so): `jj -R <Repo> --ignore-working-copy
workspace forget <name>`, then delete the `<Stale worktree>` directory, because forget only
drops the registration and leaves the files; `git worktree remove` fails on it.
```

## Step 5 detail: spawn prompt and failure

```
Resume work in this repo. You are a fresh session in your own new worktree, with no prior
context beyond this message and the handover doc.

Repo: <main repo root path>
Handover: ~/.claude/state/handover/<repo-key>-<slug>-<ts>.md

Do these in order:
1. Read the handover. Note its `Branch:` (the branch to create) and the `Base commit:`
   under its `## Respawn` section (the commit to fork from). Those two values are the
   single source of truth; this prompt deliberately does not repeat them.
2. Confirm that base commit is reachable: in a jj repo (`jj root` succeeds and
   `git rev-parse --show-toplevel` fails or prints the same path; a git worktree
   nested in a jj repo prints its own path, so it is plain git) `jj log -r <base> --no-graph -T commit_id`, else
   `git rev-parse --verify <base>^{commit}`.
   If it is missing, STOP and report; do not continue.
3. Create that branch off it without `git switch`. jj repo (as in step 2):
   `jj new <base>`, then `jj bookmark create <branch> -r @-`. Plain git: if
   `git rev-parse HEAD` equals `<base>` and this worktree is on an auto-named branch,
   `git branch -m <branch>` renames it in place; otherwise
   `git worktree add <path> -b <branch> <base>` and work from `<path>`. If this errors
   (e.g. the branch already exists), STOP and report. Do NOT fall through onto another
   branch or into another worktree.
4. Run `/dev:takeover` to load the handover and orient. It reads the handover, does only
   the targeted line-range reads the handover cites, then presents a short status and
   **stops for your go-ahead**. It does not
   start working on its own. You are already on that branch, so its branch-switch is a
   no-op; never switch into another worktree. `/dev:takeover` detects this respawn handover
   (it has a `## Respawn` section and you are on its branch) and skips its rename step on
   its own, since this session is already named.

Task: <one-paragraph summary of the work and the immediate next step, so you can act cold>.
```

If the `start_session` call fails (the tool was listed but the environment rejected it),
tell the user: the handover is already written (at
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`), so they can open a fresh session
manually, read the `Branch:` and `## Respawn` base commit from it, create the branch as
in step 3 of the prompt above, then `/dev:takeover`. Nothing is lost. If the repo
also has a pushable `origin`, additionally offer the cloud flow (`respawn-cloud.md`) as the recovery
path: it republishes the same handover as a branch-carried one and prints a paste-able
resume prompt, which does not depend on this machine's filesystem at all.

## Step 6 detail: hand-off wording

Tell the user plainly:

- The fresh, named session was started with the handover and resume prompt. If the host
  shows a launch prompt instead of starting it outright, accept it. Either way the work
  is safe (committed) and `/dev:takeover` resumes it manually.
- The committed work is safe the moment it was committed: it lives in the shared git
  object store, reachable via the branch and reflog, and closing this session removes only
  its worktree, not the commit. The one rule: do not delete the original branch until the
  new session has created `feat/<slug>`. In practice, wait until the new session has
  resumed and forked, then **archive/close this session** freely.
- **Worktrees do not self-clean.** `/dev:respawn` removes nothing, and a session cannot
  remove the worktree it is running in, so this session's worktree (plus any trial
  worktrees from earlier attempts) outlives it. After the new session has forked and you
  have archived this one, prune the leftovers: run `git worktree remove <path>` yourself
  from the main repo (a jj workspace: `jj workspace forget <name>` from the main repo,
  then delete its directory), or just confirm to the resumed session that this session
  is closed and let it remove the stale worktree (its handover records the path).
