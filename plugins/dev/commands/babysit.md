---
description: Shepherd my open PRs one pass at a time (address review comments, rebase, chase CI) — safe to run unattended on a /loop
allowed-tools: Bash(gh pr list:*), Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr checks:*), Bash(gh pr review:*), Bash(gh api:*), Bash(git fetch:*), Bash(git rebase:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git switch:*), Bash(git push:*), Read, Edit, Write, Grep, Glob
---

Make **one pass** over my open PRs and nudge each one closer to merge: address new
review comments, rebase what has fallen behind, and chase down red CI. Built to be
driven by `/loop` (e.g. `/loop 5m /dev:babysit`), so the overriding design rule is
that running it when there is nothing to do is a harmless no-op.

Optional argument: a single PR number scopes the pass to just that PR. With no
argument, it sweeps every open PR you authored.

## The loop contract — read before acting

This runs unattended on a timer. Those three properties are what keep that safe:

- **Idempotent.** Every action is keyed to a self-clearing signal (an *unresolved*
  review thread, a *behind* branch, a *red* check). Resolve / fix the signal and the
  next pass skips it. Never invent work that re-fires every pass.
- **Quiet.** Report only when you *acted* or you *need a decision*. If a full pass
  found nothing actionable, end with a single terse line (or silence) — do not
  re-summarise PRs that did not change.
- **Bounded blast radius.** You operate only on open PRs **you authored**. You push
  only to a PR's *own* branch, never to `main`. You never force-push, rewrite shared
  history, merge, or close a PR on your own. Those are pings, not actions.

### When to stop and ping (same contract as `autonomous-feature`)

Surface to the human and wait, rather than guessing, on any of:

- **Ambiguous review comment** — different reasonable readings imply different fixes.
  Address the clear ones; ping on the rest with the comment quoted and your options.
- **Destructive or irreversible action** — force-push, history rewrite, merge, close,
  a data/schema migration, anything spending money or touching production.
- **Scope expansion** — a comment or fix is growing the PR beyond what it set out to
  do. Flag it; do not silently broaden the change.
- **Security-sensitive change** — auth, secrets, crypto, access control, PII.
- **Non-converging CI** — a check still red after you have pushed a fix for it twice,
  or a failure you cannot diagnose. Report the diagnosis and where you are stuck.

## One pass

Track progress with TodoWrite when a PR needs more than a trivial touch.

### 1. Enumerate candidates

`gh fetch` is not needed first; start from the PR list. Use
`gh pr list --author @me --state open` (or just the PR number from the argument).
For each, pull state with the read-only `gh` views you need: `gh pr view <n>
--json number,title,headRefName,mergeable,reviewDecision,reviewThreads,statusCheckRollup`,
`gh pr checks <n>`, `gh pr diff <n>`. Do not guess a PR's state; observe it.

In a cloud session where `gh` is absent, use the GitHub MCP tools for the same reads
and writes (`pull_request_read`, `get_job_logs`, `add_reply_to_pull_request_comment`,
`resolve_review_thread`, `push_files`, and so on). Same behaviour, different transport.

### 2. Triage each PR by signal, act on the clear ones

Work a PR only when it shows one of these. Otherwise leave it untouched.

- **Unresolved review threads.** For each actionable thread: make the change on the
  PR's branch, verify it (below), push, then resolve the thread so it does not
  re-fire next pass. If you decline a suggestion, reply on the thread with the
  one-line reason and resolve it — do not leave it dangling. Ambiguous threads are a
  ping, not a guess.
- **Behind base / merge conflict.** `git fetch origin` then rebase the PR branch onto
  fresh `origin/main` (never a stale local `main`). Resolve only *mechanical*
  conflicts; a semantic conflict is a ping. Re-verify after rebasing, then push.
- **Red CI.** Read the failing job's logs and diagnose. Fix only clear, in-scope
  failures (lint, formatting, an obvious bug, an import). A genuinely flaky check may
  be re-run once. A real design failure, or one still red after two fix attempts, is
  a ping per the contract.
- **Approved, green, mergeable.** Do **not** merge — merges are gated on explicit
  approval. Report the PR as ready to merge and stop there.

### 3. Verify before every push

Never push a fix you have not checked. Run the project's own verification (its tests
/ lint / build, per `AGENTS.md` and the TDD convention) and confirm it is green
before pushing. A fix that breaks the build is worse than the comment it answered.
Rebase the branch so history stays linear; one tidy commit per addressed unit.

### 4. Report the delta only

Close the pass with a tight summary of what *changed* this pass — per PR, what you
addressed and pushed, and any PR now flagged for a human decision (ready-to-merge, or
a ping). If nothing was actionable across the sweep, say so in one line, or end
silently. Do not restate unchanged PRs.
