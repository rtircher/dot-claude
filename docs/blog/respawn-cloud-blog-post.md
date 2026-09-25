# Respawn in the cloud: when nothing travels but git

*A follow-up to [Respawn: how an agent gives itself a fresh start](respawn-blog-post.md).*

The last post ended on a neat asymmetry: an agent cannot rename or clear itself, but
it can name a child. `/dev:respawn` builds on that pivot, and on three comfortable
assumptions of a local machine: a spawn primitive that surfaces a clickable chip, a
shared `~/.claude/state` directory where the handover waits, and git worktrees that
share one object store so a commit made here is instantly visible over there.

Then you run it in a Claude Code cloud session, and all three are gone.

## Four assumptions, all broken

This is not hypothetical. A real working session hit every one of these in a single
afternoon:

1. **There is no `spawn_task`.** Cloud sessions do not expose the tool at all. No
   chip, no one-click successor.
2. **There is no shared filesystem.** Every cloud session is a fresh ephemeral
   container. A handover written to `~/.claude/state` dies with the container that
   wrote it.
3. **There are no worktrees.** A fresh session clones the repo. All the careful
   worktree bookkeeping, the `Stale worktree:` line, the pruning etiquette, is
   meaningless.
4. **The git proxy can refuse to delete branches.** `git push --delete` failed,
   consistently, with "the remote end hung up unexpectedly." Any cleanup step that
   *requires* deleting a remote branch will wedge.

You could read this list as "respawn does not work in the cloud." The better reading
is a question: what *does* travel between two cloud sessions that share nothing?

Two things. Text the user pastes. And commits pushed to the shared remote.

That is the entire design space, and it turns out to be enough.

## The handover rides on git

If the filesystem cannot carry the handover, the repository can. The cloud flow
writes the same handover document the local flow does, then commits it to a
throwaway branch, `handover/<slug>`, forked off the base commit, and pushes it. The
work branch, `feat/<slug>`, is pushed too, pointing at the base commit itself,
carrying no bootstrap commit that would later need stripping out of a PR.

The successor session, wherever and whenever it starts, needs nothing from the old
machine. It fetches, reads the handover straight off the carrier branch with
`git show origin/handover/<slug>:docs/handovers/<date>-<slug>.md` (never checking
the branch out), switches to the work branch, and verifies it is standing on the
recorded base commit before doing anything else.

The single-source-of-truth rule from the first post survives intact: the handover
document remains the only place the branch, base, and next steps live. What changed
is the courier.

## Replacing the chip

The local flow ends with a chip the user clicks. The cloud has no chip, and the
obvious substitute, a scheduled trigger that fires up a session on its own, was
considered and rejected. A session that appears out of nowhere at a set time is
opaque, and the trigger UI is unreachable from the mobile app, which is exactly
where you are when you want to poke a cloud session from the couch.

So the cloud flow ends the way the local one does, with the same honesty about who
holds the button: it prints a **copy-paste resume prompt**. Nothing launches by
itself. When you are ready, on desktop or on your phone, you paste it into a fresh
session and the fetch-read-verify-stop sequence runs from there. The prompt is
deliberately thin: two branch names, one file path, one SHA, and marching orders.
Everything else stays in the handover, because two copies cannot drift if there is
only one.

## The gate that bit its author

My favorite wrinkle. This same plugin ships a green-tests gate: a hook that refuses
`git commit` unless a fingerprint of the *entire worktree* matches the last recorded
green test run. It exists so no commit can quietly claim an unverified tree.

Now watch it collide with the cloud flow. The handover document is a new file. A new
file changes the worktree fingerprint. So the gate denies the handover commit even
on a perfectly clean, green tree, and on a red tree (a common reason to respawn in
the first place) the denial is unrecoverable, because you cannot record a green run
for a failing suite. The flow's core deliverable was blocked, by design, by its own
sibling.

The fix is not an exemption or a bypass flag. It is to notice what the gate is
actually protecting: work commits that claim the worktree is in a known-good state.
The handover carrier commit claims nothing of the sort. So the cloud flow builds it
with git plumbing, `hash-object`, `read-tree` into a throwaway index, `commit-tree`,
never running `git commit`, never switching branches, never touching the working
tree at all. The carrier commit is assembled off to the side and pushed. The gate
never fires because the thing it guards never happens; the user's actual work
commit, meanwhile, stays fully gated. As a bonus, the same plumbing means a dirty
tree (the "respawn anyway" path) can never be accidentally swept into the carrier
commit by a careless `git add`.

## The review that earned its keep

This design went through an adversarial review before implementation: three
independent reviewers prompted to find what is wrong, not to approve. All three said
don't ship. They were right.

The gate collision above was one of two blockers. The other was a phrase I had
written without noticing it was load-bearing: choose the cloud flow "if `spawn_task`
is not callable." Callable how? You cannot test-invoke a spawn tool; a successful
probe *spawns a session*. There is no harmless way to poke it. The fix is to key
detection off the tool's *presence in the session's tool list*, and to define what
happens when the tool is present but the call fails anyway.

The smaller findings were the kind you only get from hostile readers. Verify the
base commit with an ancestor check rather than strict tip equality, or resuming a
branch that has already advanced becomes illegal by the flow's own rules. Push the
work branch *before* the handover branch, so a race between two concurrent respawns
can never strand a discoverable orphan handover. Normalize repositories to
`owner/repo` before comparing, because the same repo is `git@github.com:...` on a
laptop and `http://local_proxy@127.0.0.1:<port>/git/...` inside a cloud container,
and raw URLs will never match. None of these would have surfaced in a happy-path
walkthrough.

## The honest edges, cloud edition

Same section as last time, because the credibility lives here.

- **Deletion may fail, so cleanup never depends on it.** The resume flow attempts to
  delete the consumed handover branch; when the proxy refuses, it says so and moves
  on. The `handover/` namespace is the escape hatch: anything under it is disposable
  by convention, so a leftover branch is clutter, not corruption. Delete it from the
  GitHub UI, or don't.
- **Leftovers accumulate, so discovery never guesses.** Because deletion is
  best-effort, old handover branches pile up. When `/dev:takeover` finds more than
  one, it lists them and asks instead of silently grabbing the newest.
- **The resume prompt duplicates takeover on purpose.** The pasted prompt must work
  in a session where this plugin is not even installed, so it cannot delegate
  blindly. It prefers `/dev:takeover` when available and carries the inline steps as
  fallback, and both files carry a keep-in-sync note pointing at each other. A
  documented duplication beats an undocumented dependency.

## The same idea, one level down

The first post argued that an agent needing a fresh start must work within the
levers it actually has. The cloud version is the same argument with fewer levers.
No spawn primitive, no shared disk, no worktrees; fine. Write down what matters,
push it where it survives, and hand the user one paste-able message that turns any
fresh session, on any device, into the successor.

The substrate changed from a filesystem to a git remote plus a human clipboard. The
principle did not move an inch.
