---
description: Make one pass over my stale open PRs — close the unambiguously obsolete ones, flag the judgment calls — safe to run unattended on a /loop
allowed-tools: Bash(gh pr list:*), Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr comment:*), Bash(gh pr close:*), Bash(gh api:*), Bash(git branch:*), Bash(git log:*), Bash(git rev-parse:*), Read, Grep, Glob
---

Make **one pass** over my open PRs and clear out the dead wood: close the ones that
are unambiguously obsolete, and surface the merely-stale ones for me to judge. Built
to be driven by `/loop` (e.g. `/loop 1h /dev:pr-pruner`), so running it when nothing
is stale is a harmless no-op.

Optional argument: `close` lets you also close the judgment-call PRs you would
otherwise only flag (use once you trust it). Default is conservative.

## The loop contract — read before acting

- **Idempotent.** Closing an obsolete PR removes it from the open list, so the next
  pass skips it. Do not re-flag a PR you already commented on this cycle with no new
  signal.
- **Quiet.** Report only PRs you closed or are flagging. A pass that found nothing
  stale ends in one line, or silence.
- **Closing is reversible but not free.** A closed PR can be reopened, but closing
  still discards review state and notifies people. So auto-close **only** the
  unambiguously obsolete; everything softer is a flag, not an action.

### Close automatically (unambiguous only)

Close, after leaving a one-line audit comment that says why, when a PR is provably
obsolete:

- **Already merged.** Its head is fully contained in `origin/main` (including via
  squash-merge — compare the diff, not just the merge commit), yet the PR is still
  open.
- **Superseded.** Another open or merged PR clearly replaces it (same branch
  reopened, or an explicit "replaced by #N" trail).
- **Base branch gone.** The PR targets a branch that no longer exists, so it can
  never merge as-is.

### Flag, do not close (judgment calls)

Report these with the reason and a recommendation; close them only under the `close`
argument, and even then comment first:

- **Inactive.** No commits, comments, or review activity for a long stretch (treat
  ~30 days as the default threshold) but not provably obsolete.
- **Abandoned draft.** A draft with no movement and no path to ready.
- **Long-conflicted.** Sitting with merge conflicts, untouched, for weeks.

Anything ambiguous, owned by someone else, or that looks intentionally parked is a
flag, never an auto-close.

## One pass

1. **Enumerate.** `gh pr list --author @me --state open --json
   number,title,headRefName,baseRefName,isDraft,updatedAt,url`. Scope to a single PR
   if a number is passed alongside the mode.
2. **Classify** each against the buckets above. For the "already merged" test, fetch
   and compare against fresh `origin/main`; do not trust a stale local ref.
3. **Act.** Auto-close the unambiguous ones with an audit comment. Collect the
   judgment calls. Under `close`, close those too (comment first); otherwise leave
   them open and flagged.
4. **Report the delta.** List what you closed (with the one-line reason each) and what
   you are flagging for me to decide. Nothing stale means one line, or silence. Never
   restate healthy PRs.

In a cloud session without `gh`, use the GitHub MCP tools for the same reads and
writes (`list_pull_requests`, `pull_request_read`, `add_issue_comment`, and the PR
update/close call). Same behaviour, different transport.
