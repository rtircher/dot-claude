---
description: Summarise this session and write a per-repo handover a fresh session can resume from
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git worktree list:*), Bash(gh pr list:*), Bash(mkdir -p:*), Bash(date:*), Bash(ls:*), Bash(mv:*), Write
---

Write a handover that lets a fresh session resume this work with no other context.
Pairs with `/dev:takeover`. State is **scoped per repository** — keyed by the *main*
repo, so all worktrees of a project share one handover, and handovers from different
repos never overwrite each other. A previous handover is archived rather than lost.

## 1. Identify the repo and gather state

- Repo key: the basename of the **main** repo, so every worktree of a project shares
  one handover. Derive it from the shared git dir, not the current worktree:
  `` basename "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" ``.
  Use `default` if you are not in a git repo. Note that main root path too.
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

Record the **main repo root** (the same one used for the key) and branch verbatim —
`/dev:takeover` checks them before it resumes or switches branches. After writing,
report the path and a one-line summary.
