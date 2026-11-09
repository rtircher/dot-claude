---
name: pr-comments
description: Fetch and address unresolved review comments across all open PRs. Use when the user shares a PR comment URL, says "address comments", "fix PR feedback", or "what comments are open on my PRs".
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/unresolved-threads.sh *), Bash(gh *), Bash(git worktree add *), Bash(git ls-remote *), Bash(jj *), Read
---

## Step 1: List unresolved review threads

One row per thread, from its first comment (`url` ends in `discussion_r<id>`).
With no argument it covers my open PRs in every repo; a PR URL names its own
repo, and a bare number uses the current directory's repo (`-R owner/repo` to
override). Read the full text before acting:
`gh api repos/<owner>/<repo>/pulls/comments/<id>`, with `<owner>/<repo>` from
the row's `pr` column.

!`bash ${CLAUDE_SKILL_DIR}/scripts/unresolved-threads.sh "$ARGUMENTS" 2>&1 || echo "unresolved-threads.sh failed; check gh auth status"`

## Your task

$ARGUMENTS

If no specific PR/comment was given, for each PR:
1. Triage the threads above: group by file, deduplicate (claude[bot] and cursor[bot] often flag the same issue), rank by severity (🔴 high / 🟡 medium / ⚪ low)
2. Show the organised list and ask which ones to address
3. **Do not make any changes yet**: wait for confirmation

If a specific comment URL or PR was given, go straight to addressing it.

---

## Rules

- Work in the PR's own repo. Get on the branch via a scratch worktree (`git worktree add <path> <branch>`), or via jj in a jj repo (flow below); never `git checkout`
- A PR under review gets a new commit, never an amend (rewritten SHAs break "changes since last review")
- Commit with the tool that owns the checkout: `git commit` in a git worktree; in a jj workspace or jj main repo:
  1. `jj new -A <bookmark>` (inserts after the branch tip; stacked dependents restack)
  2. edit, then `jj describe -m "<scope>: <why>"`
  3. `jj bookmark set <bookmark> -r @`, then `jj new` so later edits don't amend it
  4. verify: `jj log -r <bookmark>` shows the new commit at the tip, and `jj log -r '(trunk()..bookmarks()) & conflicts()'` is empty
- Run the affected tests with the repo's own test command (its AGENTS.md / CLAUDE.local.md says how)
- **Close every addressed thread: reply, then resolve.** A thread is addressed when it is fixed (the fix is pushed) or pushed back on (the reason is given). For each one:
  1. Reply in the thread: `gh api -X POST repos/<owner>/<repo>/pulls/<pr>/comments/<first-comment-id>/replies -f body="Fixed in <sha>."`, or the one-line reason for a pushback.
  2. Resolve it, using `thread_id` from Step 1: `gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<thread_id>"}){thread{isResolved}}}'`.
  3. Re-run `bash ${CLAUDE_SKILL_DIR}/scripts/unresolved-threads.sh <pr-url>`; the thread must be gone.
  Bot threads: do all three as soon as the fix is pushed. Human threads: the user posts the reply themselves; resolve only after their reply is on the thread, and only when they say to.
- Push only when asked: `jj git push --bookmark <name>` (`git push origin <branch>` from a git worktree), then verify with `git ls-remote origin <branch>`
