---
description: Summarise this session and write a per-repo handover a fresh session can resume from
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git worktree list:*), Bash(gh pr list:*), Bash(mkdir -p:*), Bash(date:*), Bash(ls:*), Bash(mv:*), Write
---

Write a handover that lets a fresh session resume this work with no other context.
Pairs with `/dev:takeover`. State is **scoped per repository**, so handovers from
different repos never overwrite each other, and a previous handover is archived
rather than lost.

## 1. Identify the repo and gather state

- Repo key: run `git rev-parse --show-toplevel`; the handover key is its basename
  (use `default` if you are not in a git repo). Note the full root path too.
- Ground the handover in fact with read-only commands you need — `git status`,
  `git branch --show-current`, `git diff --stat`, `git log --oneline -5`,
  `git worktree list`. Do not guess; if you didn't observe it, leave it out.

## 2. Preserve the previous handover (no data loss)

`mkdir -p ~/.claude/state/handover ~/.claude/state/handover-archive`. The per-repo
path is `~/.claude/state/handover/<repo-key>.md`. If a file already exists there,
move it into the archive with a UTC-timestamped name before writing the new one:
`~/.claude/state/handover-archive/<repo-key>-$(date -u +%Y%m%dT%H%M%SZ).md`. This
keeps an unconsumed handover from being silently clobbered.

## 3. Write the handover

Write `~/.claude/state/handover/<repo-key>.md` (use a real UTC timestamp from
`date -u +%Y-%m-%dT%H:%M:%SZ`). Keep it tight; omit a genuinely empty section.

```markdown
# Session handover — <ISO 8601 UTC timestamp>
Repo: <full repo root path>
Branch: <current branch>

## Task & goal
What this session is doing and why.

## Current state
Worktree path, committed vs uncommitted changes, what's done vs in-progress.

## Key decisions
Non-obvious context: approaches ruled out, paths not to take, constraints learned.

## Next steps
Concrete actions to resume, in order.

## Open questions / blockers
What's unresolved or waiting on input.
```

Record the repo root and branch verbatim — `/dev:takeover` checks them before it
resumes or switches branches. After writing, report the path and a one-line summary.
