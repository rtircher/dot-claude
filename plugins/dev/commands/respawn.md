---
description: Respawn this session into a fresh, meaningfully named one. Writes a handover, then spawns a clean session that resumes the work (a started session, or a branch-carried resume prompt in cloud)
allowed-tools: Bash(jj root:*), Bash(jj log:*), Bash(jj new:*), Bash(jj bookmark:*), Bash(jj status:*), Bash(jj diff:*), Bash(jj commit:*), Bash(jj describe:*), Bash(git status:*), Bash(git branch:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git worktree list:*), Bash(git add:*), Bash(git commit:*), Bash(git ls-remote:*), Bash(git push:*), Bash(git hash-object:*), Bash(git read-tree:*), Bash(git update-index:*), Bash(git write-tree:*), Bash(git commit-tree:*), Bash(mkdir -p:*), Bash(mktemp:*), Bash(rm -f:*), Bash(date:*), Bash(ls:*), Bash(mv:*), Write, ToolSearch, Read, mcp__ccd_session__start_session
---

Collapse the `handover` then `clear` then `takeover` ritual into one step. This writes
a handover (as `/dev:handover` does), then spawns a brand-new session that is **named at
birth** and pre-seeded to resume the work in its **own clean worktree**, forked off your
committed state. The goal is a fresh, uncluttered context without losing anything.

Why a new session rather than an in-place clear: `/clear` and `/rename` are user-only,
so the model cannot reset or retitle the current session. A *new* session, by contrast,
can be named at creation. That is the lever this command pulls.

## Which flow: capability detection, never a user flag

Decide by what this session actually exposes. Detection keys off **tool presence**,
never a test invocation: calling `start_session` starts a session, so there is no
harmless probe. The tool may be deferred; load it with ToolSearch query
`select:mcp__ccd_session__start_session`. If that returns no match, it is absent.

1. **`mcp__ccd_session__start_session` is present**: run the **local flow**, steps 1
   to 6 below, exactly as written.
2. **No such tool, but the repo has a pushable `origin`**: run the **cloud flow**: Read
   `${CLAUDE_PLUGIN_ROOT}/references/respawn-cloud.md` and follow it in place of steps
   2 to 6 (it reuses steps 1 and 3 of the local flow). This is deliberately not "am I
   in cloud" sniffing: the branch-carried flow needs only git, so it is the correct
   fallback anywhere the tool is missing.
3. **No such tool and no usable remote**: run the **manual fallback** (last section).
   Not a git repo at all: stop, as step 1 says.

Use `start_session`, not `hand_off_to_session`: a hand-off forks the whole
conversation into the new session, which defeats a respawn.

jj repos (`jj root` succeeds and `git rev-parse --show-toplevel` fails or prints the same path; a git worktree nested in a jj repo prints its own path, so it is plain git) have no `git checkout`/`switch` (a hook blocks them) and
their workspaces have no `.git`, so branch work below uses jj there and non-switching
git commands otherwise.

## 1. Gather state and check preconditions

Repo key (shared across git worktrees and jj workspaces) is the basename of the
**main** repo: run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/repo-key.sh"`, which prints
`KEY` (the repo key) and `ROOT` (the main root path); note both.
Ground everything in fact: `git status`, `git branch --show-current`, `git diff --stat`,
`git log --oneline -5`, `git worktree list`. Do not guess.

**Stop early if respawn does not apply:**
- **Not a repo** (`ROOT` above is empty): respawn needs a repo to fork from. Say so
  and stop.
- **Nothing to hand off** (clean tree, no feature work in progress, no resumable task):
  there is nothing to respawn into. Surface this and confirm with the user before going on.

## 2. Commit-first gate

The new session lands in its **own fresh worktree** and can only see what is committed
(worktrees share the same git object store, so a local commit is reachable there without
a push). Anything not committed does not travel.

So if `git status` shows uncommitted changes (jj: non-empty `@` in `jj status`), **stop and ask the user**, offering:

- **Commit now** (recommended): commit the in-progress work to the current branch, staging deliberately (no blanket `git add -A`).
- **Respawn anyway**: proceed without committing. **Warn loudly** that the new session
  will NOT see the uncommitted changes; they stay stranded in this worktree.
- **Cancel**: stop and do nothing.

Also warn, either way, that the fresh worktree starts clean: gitignored / local artifacts
(env files, `node_modules`, build output, tool caches) will not exist there and may need
rebuilding.

Capture the resulting tip as `<base-sha>`; the new session forks off it. In jj, `@-` is the tip
only when the work sits in `@-` and `@` is empty, so verify that before reading it. Read `${CLAUDE_PLUGIN_ROOT}/references/respawn-local.md`
(Step 2 detail) when committing or capturing `<base-sha>`, for the staging and jj commands.

## 3. Pick names (and reserve the branch)

Derive a short kebab-case `<slug>` from the handover's `Task & goal` (lowercased,
non-alphanumeric runs to `-`, trimmed to ~40 chars), e.g. `respawn-command`. From it:

- **Branch:** `feat/<slug>` (or `fix/<slug>` for a bugfix).
- **Session title:** a readable form, e.g. "respawn command".

`feat/<slug>` must be free, since the new session creates it. Check
`git branch --list "feat/<slug>"` (jj: `jj bookmark list "feat/<slug>"`) and
`git worktree list`; on any collision, pick a distinct slug or ask the user. Do not
proceed with a name that already exists.

## 4. Write the handover

Write to a **per-respawn unique path** so concurrent respawns never clobber each other:
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`, where `<ts>` is
`date -u +%Y%m%dT%H%M%SZ`. The timestamp is what guarantees uniqueness: `<slug>` alone is
not enough, because the branch is not reserved until the new session forks (step 5), so two
concurrent respawns can derive the same slug. Each spawn prompt (step 5) points the new
session at its own file by exact path.

Then archive already-consumed prior handovers with `bash "${CLAUDE_PLUGIN_ROOT}/scripts/handover-archive-sweep.sh"`
(never touches the shared `<repo-key>.md` slot), `mkdir -p ~/.claude/state/handover`, and write the file with a real UTC timestamp inside.
Use `/dev:handover`'s sections, but **record `feat/<slug>` as the `Branch:` line, not the current branch**.
The `Repo:` line must be the main repo root verbatim. Keyed lines `Repo:`, `Branch:`, and the `## Respawn`
`Base commit:` are mandatory and parsed downstream. The handover is the **single source of truth** for the base
commit, destination branch, and worktree to prune (`Stale worktree:`). Read `${CLAUDE_PLUGIN_ROOT}/references/respawn-local.md`
(Step 4 detail) before writing it, for the sweep options, `Stale worktree:` rules, and the template.

## 5. Spawn the fresh session

Call `mcp__ccd_session__start_session` with `initiation` = `"user_asked"` (the user
typed `/dev:respawn`), `context` = `"fresh"`, `title` = the session title from step 3
(this becomes the new session's name), `background` = at least 80 characters of the
goal and constraints (a one-line restatement of the handover's `Task & goal` plus the
main constraint), and a `prompt` built from the template in `respawn-local.md` (Step 5 detail). Interpolate `<main repo root path>`, the full handover path from step 4
(`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`), and the `Task:` summary. Do **not**
embed the branch name or base commit here: they live solely in the handover, so the prompt
and handover cannot drift. The new session has no memory of this one.

Read `${CLAUDE_PLUGIN_ROOT}/references/respawn-local.md` (Step 5 detail) for the prompt template to pass, and for what to tell the user if `start_session` fails
(the handover is already written, so nothing is lost; offer the cloud flow if `origin` is pushable).

## 6. Hand off

Tell the user plainly: the fresh named session was started (accept a host launch prompt if shown); the
committed work is safe, but do not delete the original branch until the new session has created `feat/<slug>`;
and **worktrees do not self-clean**: `/dev:respawn` removes nothing, so this session's worktree outlives it.
Read `${CLAUDE_PLUGIN_ROOT}/references/respawn-local.md` (Step 6 detail) for the exact wording and prune commands.

## Manual fallback (no start_session, no usable remote)

Run local steps 1 to 4 unchanged (gather, commit-first gate, names, write the
timestamped handover file with its archive sweep; the sweep is a natural no-op in a
fresh container). Skip the spawn. Print the manual-resume instructions (open a fresh
session, read `Branch:` and the `## Respawn` base commit from the handover, create the
branch as in step 3 of the local prompt (read `${CLAUDE_PLUGIN_ROOT}/references/respawn-local.md`, Step 5 detail), then `/dev:takeover`), and **also print
the handover content itself in your reply**: in an ephemeral container the file dies
with the session, and the transcript is what survives.
