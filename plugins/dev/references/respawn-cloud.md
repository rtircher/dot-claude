# Respawn: cloud flow

Read by `/dev:respawn` only when `mcp__ccd_session__start_session` is absent and the
repo has a pushable `origin`. "Local step N" below means that command's local flow.

## Why the cloud flow differs

Claude Code cloud/web sessions break four assumptions the local flow rests on.
Each forces the substitution named with it; do not "simplify" one away without
re-checking its constraint:

1. **No `start_session`.** Cloud sessions do not expose `mcp__ccd_session__start_session`,
   so nothing can launch a fresh session. Substitution: the deliverable becomes a **copy-paste
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

## Cloud flow: branch-carried respawn (no start_session, pushable origin)

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
has (pre-commit hooks), exactly as in the local flow; do not suggest bypassing them. If a gate blocks the commit, fix the cause
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

Why plumbing rather than switch-commit-switch: with a dirty tree (the "Respawn
anyway" path), `git switch` drags the uncommitted changes across branches and a
careless `git add` would sweep them into the carrier commit, stranding in-progress
work on a never-merged branch. Plumbing leaves the working tree and current branch
untouched.

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
