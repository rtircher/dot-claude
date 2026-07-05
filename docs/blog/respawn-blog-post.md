# Respawn: how an agent gives itself a fresh start

Every long Claude Code session eventually hits the same wall. The context window
fills with the residue of work already done: dead ends, verbose tool output, three
abandoned approaches before the one that stuck. The agent is still capable, but it
is reasoning through a fog of its own history. The usual fix is to start over. The
catch is that starting over, done by hand, loses everything you learned getting here.

`/dev:respawn` is the command that lets a session start over without losing the thread.

## The ritual it replaces

Before respawn, the clean-restart dance had three steps, and you ran all three by hand:

1. `/dev:handover` writes a per-repo summary of what you were doing, what is done,
   what comes next, and the non-obvious decisions you would otherwise have to
   rediscover.
2. `/clear` wipes the context.
3. `/dev:takeover` reads the handover back in and resumes.

It works, but it is fiddly, and it has a sharp edge: a cleared session keeps its old
auto-generated title ("general coding session") and its old, cluttered worktree. You
get a fresh context but not a fresh *name*, and you are still sitting in the same
directory full of half-built artifacts.

## The constraint that shaped the design

Here is the part that makes this interesting. The obvious implementation, "have the
agent clear and rename itself," is impossible. `/clear` and `/rename` are user-only
commands. The model cannot reset its own context or retitle its own session. Those
levers are not wired to the agent's hands.

So respawn does not try to fix the current session. It does the one thing the model
*can* do: spawn a brand-new session, and a new session can be named at the moment it
is born. That single asymmetry, "you cannot rename yourself, but you can name a
child," is the whole pivot the command is built around.

## What respawn actually does

In one step, `/dev:respawn`:

1. **Grounds itself in fact.** It reads `git status`, the current branch, the diff,
   recent log, and the worktree list. It does not guess at state. If you are not in a
   git repo, or there is genuinely nothing to hand off, it stops and says so.
2. **Gates on committed work.** The new session lands in its own fresh worktree, and a
   worktree can only see what is committed. So if you have uncommitted changes, respawn
   stops and asks: commit now (recommended, staged deliberately rather than a blanket
   `git add -A`), respawn anyway and strand the changes, or cancel. It also warns that
   the fresh worktree starts clean, so gitignored artifacts like `node_modules` or env
   files will not be there.
3. **Picks names and reserves the branch.** It derives a short kebab-case slug from the
   task, turns it into a `feat/<slug>` branch and a readable session title, and checks
   that the branch name is actually free before committing to it.
4. **Writes a handover** in the same format `/dev:handover` uses, with one twist: the
   `Branch:` line records the *destination* `feat/<slug>`, not the branch you are on
   now. It also records the base commit to fork from and the path of the current
   worktree to clean up later.
5. **Spawns the fresh session** with a prompt that points at the handover rather than
   repeating its contents, so the prompt and the handover cannot drift out of sync.

The new session wakes up with no memory of the old one, reads the handover, creates
`feat/<slug>` off the recorded base commit, and runs `/dev:takeover` to resume. Because
it is already on the right branch and already correctly named, takeover quietly skips
its own rename and branch-switch steps. The handoff is seamless.

## The single source of truth

A recurring failure mode in handoff systems is drift: the spawn prompt says one branch,
the handover says another, and the resumed session picks the wrong one. Respawn avoids
this by being strict about ownership. The base commit, the destination branch, and the
stale worktree to prune all live in exactly one place, the handover document. The spawn
prompt deliberately does not repeat them. It just says "read the handover; those two
values are the single source of truth." Two copies cannot disagree if there is only one.

## The honest edges

Respawn is upfront about what it does not do, which is the part worth respecting.

- **It cannot auto-launch the new session.** A foreground session needs one human click
  on the chip it surfaces. If you miss the chip, nothing is lost: the work is committed
  and `/dev:takeover` will resume it by hand.
- **Worktrees do not self-clean.** A session cannot remove the worktree it is running
  inside, so the old worktree outlives the old session. The command tells you this
  plainly and hands the cleanup to the resumed session (which has the path in its
  handover) or to you.
- **Committed work is safe the moment it is committed.** It lives in the shared git
  object store, reachable by branch and reflog. Closing the old session removes only its
  worktree, never the commit.

## Why this matters

The deeper idea here is small but general. An agent that runs long enough needs a way to
shed its own accumulated context without amnesia, and it needs to do that within the
constraints it actually has, not the ones we wish it had. It cannot clear itself. It
cannot rename itself. But it can write down what matters, commit the work so it survives,
and spawn a successor that is named, scoped, and clean from its first token.

That is respawn: not a reset button the agent presses on itself, but a fresh start it
hands to the next session in line.
