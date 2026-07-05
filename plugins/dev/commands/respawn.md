---
description: Respawn this session into a fresh, meaningfully named one. Writes a handover, then spawns a clean session that resumes the work (local chip, or a branch-carried resume prompt in cloud)
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git worktree list:*), Bash(git add:*), Bash(git commit:*), Bash(git ls-remote:*), Bash(git push:*), Bash(git hash-object:*), Bash(git read-tree:*), Bash(git update-index:*), Bash(git write-tree:*), Bash(git commit-tree:*), Bash(mkdir -p:*), Bash(mktemp:*), Bash(rm -f:*), Bash(date:*), Bash(ls:*), Bash(mv:*), Write, mcp__ccd_session__spawn_task
---

Collapse the `handover` then `clear` then `takeover` ritual into one step. This writes
a handover (as `/dev:handover` does), then spawns a brand-new session that is **named at
birth** and pre-seeded to resume the work in its **own clean worktree**, forked off your
committed state. The goal is a fresh, uncluttered context without losing anything.

Why a new session rather than an in-place clear: `/clear` and `/rename` are user-only,
so the model cannot reset or retitle the current session. A *new* session, by contrast,
can be named at creation. That is the lever this command pulls.

## Which flow: capability detection, never a user flag

Decide by what this session actually exposes. Detection keys off **tool presence in
your available tool set**, never a test invocation: calling `spawn_task` spawns a
session, so there is no harmless probe.

1. **`mcp__ccd_session__spawn_task` is present**: run the **local flow**, steps 1 to 6
   below, exactly as written.
2. **No spawn tool, but the repo has a pushable `origin`**: run the **cloud flow**
   (after step 6). This is deliberately not "am I in cloud" sniffing: the
   branch-carried flow needs only git, so it is the correct fallback anywhere the
   spawn tool is missing.
3. **No spawn tool and no usable remote**: run the **manual fallback** (last section).
   Not a git repo at all: stop, as step 1 says.

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

If the `spawn_task` call fails (the tool was listed but the environment rejected it),
tell the user: the handover is already written (at
`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`), so they can open a fresh session
manually, read the `Branch:` and `## Respawn` base commit from it, run
`git switch -c <branch> <base>`, then `/dev:takeover`. Nothing is lost. If the repo
also has a pushable `origin`, additionally offer the cloud flow below as the recovery
path: it republishes the same handover as a branch-carried one and prints a paste-able
resume prompt, which does not depend on this machine's filesystem at all.

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

## Why the cloud flow differs

Claude Code cloud/web sessions break four assumptions the local flow rests on
(observed 2026-07-04). Each forces the substitution named with it; do not "simplify"
one away without re-checking its constraint:

1. **No `spawn_task`.** Cloud sessions do not expose `mcp__ccd_session__spawn_task`,
   so there is no clickable chip. Substitution: the deliverable becomes a **copy-paste
   resume prompt** the user pastes into any fresh session (desktop or mobile). Not a
   Routine/trigger: Routines are unreachable from the mobile app, and timed triggers
   make sessions appear out of nowhere.
2. **No shared filesystem.** Each cloud session is a fresh ephemeral container, so
   `~/.claude/state/handover/*` does not travel. The only state that reliably travels
   is (a) prompt text the user pastes and (b) commits pushed to the shared remote.
   Substitution: the handover doc ships on a pushed throwaway **`handover/<slug>`
   branch** instead of a state file.
3. **No worktrees.** Fresh cloud sessions clone the repo; worktree creation, pruning,
   and `Stale worktree:` bookkeeping are meaningless there. Substitution: none of it
   in the cloud flow; the old session is simply archived.
4. **The cloud git proxy can reject branch deletion.** `git push --delete`
   consistently failed with "the remote end hung up unexpectedly". Substitution:
   cleanup *attempts* deletion but never depends on it; the fallback is deleting from
   the GitHub UI or leaving the branch, with the `handover/` namespace marking
   branches disposable by convention.

## Cloud flow: branch-carried respawn (no spawn_task, pushable origin)

Validated by hand in `rtircher/race_engineer` (branches
`handover/stage-4-tip-library-followups` + `feat/stage-4-tip-library-followups`).

### C1. Gather state and check preconditions

As local step 1, minus the worktree commands. Additionally read the origin URL with
`git ls-remote --get-url origin` (a local read, no network) and snapshot remote
branches with `git ls-remote --heads origin` for the collision check in C3. The same
stop-early rules apply (not a repo; nothing to hand off).

### C2. Commit-first gate (cloud wording)

Same three options as local step 2, with the stakes raised: in cloud, **only pushed
commits travel**. "Respawn anyway" must warn that uncommitted changes are *lost
forever* when this container dies, not merely stranded in a sibling worktree.

The user's work commit ("Commit now") stays subject to whatever commit gates the repo
has (pre-commit hooks, the conventions plugin's green-tests gate), exactly as in the
local flow; do not suggest bypassing them. If a gate blocks the commit, fix the cause
or put the choice to the user. The handover-doc commit is NOT such a commit; C4
explains why it is built with plumbing instead.

Capture `<base-sha>` = `git rev-parse HEAD` after the gate, as in the local flow.
Because base is always this session's HEAD, the pushes below are the ordinary "push my
current work" case; no deep historical SHA is involved.

### C3. Pick names, check the remote

Derive `<slug>` and the session-title form as local step 3. Two branches:

- **Work branch** `feat/<slug>` (or `fix/<slug>`), pushed **at the base commit**.
  "At base" means it carries no respawn-generated bootstrap commit that would later
  need stripping from the PR; the user's committed work is of course in its history
  up to base.
- **Handover branch** `handover/<slug>`: a throwaway carrier, forked off the same
  base commit, holding exactly one commit (the handover doc). It is never merged.

Collision check against the **remote**:
`git ls-remote --heads origin "feat/<slug>" "handover/<slug>"` must return nothing;
on any hit pick a distinct slug (append `-2`, etc.) or ask the user. This check is
best-effort against a concurrent respawn racing the same slug; the pushes in C4 are
the real arbiter (a non-forced push to a new ref fails for the loser), and their
ordering is chosen so a lost race leaves no discoverable half-spawn.

### C4. Write the handover, commit it with plumbing, push

Write the handover doc first as a file, at the local flow's usual path
(`~/.claude/state/handover/<repo-key>-<slug>-<ts>.md`; the file is ephemeral here,
it only feeds the commit below). Use `/dev:handover`'s sections with these
cloud-specific keyed lines:

- `Repo:` the origin **normalized to `<owner>/<repo>`**: strip a trailing `.git` and
  trailing slashes from the origin URL, then take the last two path components (after
  the `:` for scp-style SSH URLs). Raw URLs never match across environments (SSH
  locally, an `http://local_proxy@127.0.0.1:<port>/git/<owner>/<repo>` proxy URL in
  cloud containers), so writer and reader both normalize; `/dev:takeover` applies the
  same rule when matching.
- `Branch: feat/<slug>` (the work branch, as in the local respawn flow).
- **No `Stale worktree:` line** (constraint 3).
- A `## Respawn` section recording, as keyed lines plus short prose:
  `Base commit: <base-sha>`; `Handover branch: handover/<slug>`; that the work branch
  starts at base with no bootstrap commit; the repo's fresh-clone bootstrap command if
  it has one (e.g. `make deps`); that the old session can simply be archived once
  resumed (no worktree to prune); and the cleanup rule: delete `handover/<slug>` once
  consumed; if the git proxy rejects the deletion ("the remote end hung up
  unexpectedly"), ask the user to delete it from the GitHub UI **or leave it**, since
  the `handover/` namespace marks branches disposable.

The in-repo path for the committed copy follows the convention
`docs/handovers/<UTC yyyy-mm-dd>-<slug>.md` (it exists only on the carrier branch,
so it never pollutes the real `docs/` tree).

**Build the carrier commit with plumbing. Never switch branches, never run
`git commit`, never touch the working tree.** One Bash chain with a throwaway index:

```bash
tmpidx=$(mktemp) && rm -f "$tmpidx" && \
blob=$(git hash-object -w ~/.claude/state/handover/<repo-key>-<slug>-<ts>.md) && \
GIT_INDEX_FILE="$tmpidx" git read-tree <base-sha> && \
GIT_INDEX_FILE="$tmpidx" git update-index --add \
  --cacheinfo 100644,"$blob","docs/handovers/<date>-<slug>.md" && \
tree=$(GIT_INDEX_FILE="$tmpidx" git write-tree) && \
commit=$(git commit-tree "$tree" -p <base-sha> -m "docs: handover for <slug>") && \
rm -f "$tmpidx" && echo "$commit"
```

Why plumbing rather than switch-commit-switch:

- With a dirty tree (the "Respawn anyway" path), `git switch` drags the uncommitted
  changes across branches and a careless `git add` would sweep them into the carrier
  commit, stranding in-progress work on a never-merged branch. Plumbing leaves the
  working tree and current branch untouched.
- The conventions green-tests gate fingerprints the **whole worktree** and denies
  `git commit` whenever the tree diverges from the last recorded green run. A
  porcelain handover commit is therefore denied even on a clean tree (the new doc
  file changes the fingerprint) and unrecoverably on a red tree, a common reason to
  respawn. The gate exists so no *work* commit claims an unverified tree; this
  carrier commit makes no claim about the worktree at all (built off base, outside
  the worktree, on a branch that is never merged), so constructing it with
  `commit-tree` is outside the gate's purpose, not a bypass of it. The user's work
  commit in C2 stays gated.

**Push work branch first, then handover branch:**

```bash
git push origin <base-sha>:refs/heads/feat/<slug>
git push origin <commit>:refs/heads/handover/<slug>
```

If the work-branch push is rejected (a racing respawn won the name), stop, pick a
fresh slug, and redo from C3; nothing has been published. If the handover push fails
after the work branch landed, the leftover is a work branch at base: harmless,
reusable by a retry of the same slug (re-pushing the same SHA is a no-op), and
invisible to takeover discovery, which looks only at `handover/*`. The reverse order
could strand a discoverable orphan `handover/<slug>`. Only after **both** pushes
succeed, print the resume prompt.

### C5. Print the copy-paste resume prompt (the deliverable)

Print this in a fenced block for the user to paste into any new session, desktop or
phone. It must NOT duplicate handover content beyond the two branch names, the
handover file path, and the base SHA: the handover stays the single source of truth.

```
Resume work in <owner>/<repo>. You are a fresh session with no prior context beyond
this message and a handover doc stored on a git branch.

If /dev:takeover is available, run it now: it discovers origin/handover/<slug> and
performs this same procedure. Otherwise, do these in order:
1. git fetch origin feat/<slug> handover/<slug>
2. Read the handover WITHOUT switching branches:
   git show origin/handover/<slug>:docs/handovers/<date>-<slug>.md
   Never check out the handover branch; it is a throwaway carrier.
3. git switch feat/<slug> (creating it from origin/feat/<slug>), then verify
   <base-sha> is its tip or an ancestor of it:
   git merge-base --is-ancestor <base-sha> HEAD. On failure, STOP and report; do
   not fall through to another branch or commit. If the tip has advanced past
   <base-sha>, work already resumed once; trust the branch state over the
   handover's "Next steps".
4. If the handover's Respawn section names a fresh-clone bootstrap (e.g.
   make deps), run it.
5. Present a short status from the handover and STOP for my go-ahead. Do not
   start working on your own.
6. After my go-ahead, attempt cleanup: git push origin --delete handover/<slug>.
   If the push is rejected (cloud git proxy, "the remote end hung up
   unexpectedly"), say so and ask me to delete the branch from the GitHub UI, or
   leave it (handover/ branches are disposable by convention).
```

Notes pinned to this template:

- The **ancestor check** (not strict tip equality) keeps a re-resume legal after the
  successor session has committed work; on the first resume it degenerates to
  equality.
- Steps 1 to 6 intentionally duplicate `/dev:takeover`'s branch-carried procedure:
  the pasted prompt must work even where the dev plugin is not loaded, so it cannot
  hard-depend on the command. The duplication is bounded (fetch, show, switch,
  ancestor-verify, bootstrap, stop, cleanup) and the first line prefers delegating to
  `/dev:takeover` when it exists. **Keep this template and takeover's branch-carried
  steps in sync when editing either.**

### C6. Hand off

Tell the user plainly: **nothing launches by itself.** Copy the prompt above into a
fresh session (desktop or mobile) whenever ready; that paste replaces the local
flow's chip. The work is safe the moment both pushes succeeded. This session can then
be archived; there is no worktree to prune in cloud.

## Manual fallback (no spawn tool, no usable remote)

Run local steps 1 to 4 unchanged (gather, commit-first gate, names, write the
timestamped handover file with its archive sweep; the sweep is a natural no-op in a
fresh container). Skip the spawn. Print the local flow's manual-resume instructions
(open a fresh session, read `Branch:` and the `## Respawn` base commit from the
handover, `git switch -c <branch> <base>`, then `/dev:takeover`), and **also print
the handover content itself in your reply**: in an ephemeral container the file dies
with the session, and the transcript is what survives.
