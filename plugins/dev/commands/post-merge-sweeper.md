---
description: Sweep recently merged PRs for review comments that were deferred but never done, and surface the follow-ups — safe to run unattended on a /loop
allowed-tools: Bash(gh pr list:*), Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh api:*), Bash(git log:*), Bash(git fetch:*), Bash(git rev-parse:*), Read, Grep, Glob
---

Make **one pass** over my recently merged PRs and catch the loose ends: review
comments that were acknowledged as "follow-up" or "separate PR" but never actually
landed. The asymmetry this closes is that a comment can be agreed-to, the PR merges,
and the agreement quietly evaporates. Built for `/loop` (e.g. `/loop 30m
/dev:post-merge-sweeper`), so a pass with no loose ends is a harmless no-op.

Default is **report-only**: it compiles the follow-ups, it does not open PRs on its
own. Pass `pr` to also stand up a follow-up branch + PR per actionable item (use once
you trust the sweep).

## The loop contract — read before acting

- **Idempotent.** Each loose end must key to a self-clearing signal so it stops
  surfacing once handled. Use the comment's own thread: when the follow-up lands (or
  you open its PR), reply on the originating thread linking the resolution and resolve
  it. A resolved thread is skipped next pass. Never re-report an item already linked
  to an open follow-up PR.
- **Quiet.** Report only genuine, still-open loose ends. A clean sweep ends in one
  line, or silence.
- **Surface, do not silently expand scope.** A follow-up is new work. Default to
  *reporting* it; only open a PR under the `pr` argument, and even then keep each PR
  to the single deferred comment it answers — do not bundle or broaden.

## What counts as a loose end

A review comment on a **merged** PR that was acknowledged as deferred but has no
landed change and no tracking issue/PR. Signals of deferral: "follow-up", "separate
PR", "in a later change", "good catch, will fix", "TODO" left in a reply. Require an
explicit acknowledgement; do not invent follow-ups from comments the author rejected,
already addressed in-PR, or never agreed to.

Skip anything that already has a tracking issue, an open follow-up PR, or a resolved
thread. Those are handled.

## One pass

1. **Enumerate** recently merged PRs you authored:
   `gh pr list --author @me --state merged --limit 20 --json
   number,title,mergedAt,url`. A passed PR number scopes to one.
2. **Scan threads.** For each, read the review threads
   (`gh pr view <n> --json reviewThreads` or the MCP `pull_request_read` threads
   view) and pick out unresolved, acknowledged-deferred comments per the rule above.
3. **Compile.** Build the loose-end list: the originating comment, the PR, and a
   one-line description of the follow-up.
4. **Act per mode.**
   - *Default:* report the list, grouped by PR, each with a recommended next step.
   - *`pr`:* for each actionable item, branch from fresh `origin/main`, make the
     change, verify with the project's own tests, open a focused PR, then reply on the
     originating thread linking it and resolve the thread. Honor the conventions: one
     comment per PR, never touch `main`, ping on ambiguity, security, or scope.
5. **Report the delta.** What you surfaced (and any PRs opened). A clean sweep is one
   line, or silence. Do not restate merged PRs with no loose ends.

In a cloud session without `gh`, use the GitHub MCP tools for the same reads and
writes. Same behaviour, different transport.
