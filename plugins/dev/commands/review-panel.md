---
description: Guaranteed adversarial review. Claude lens panel plus every cross-family external reviewer this machine configures, run for real
allowed-tools: Bash(git:*), Bash(gh pr view:*), Bash(sha256sum:*), Bash(node:*), Bash(cat:*), Read, Glob, Grep, Workflow, Agent
---

Run one adversarial-review pass with external review ON by default (every
reviewer this machine's `EXTERNAL_REVIEWERS` config lists; none configured
means a Claude-only panel). Each external vote is bound to the artifact by
digest, and any reviewer that could not run is reported, never a phantom
"external" vote.

Contract, stricter than a bare use of the skill:

- `$ARGUMENTS` names ONE explicit artifact: a file path (spec/plan), a diff
  range like `main...HEAD`, a branch, or a GitHub PR number or URL (resolved
  per the skill's step 1, in a temporary worktree, never by switching the
  user's branch); plus an optional "no external" /
  "claude only" modifier. The only allowed inference is a bare invocation on a
  branch with one unambiguous diff against the trunk. Anything else: ask once,
  then proceed.
- `externalReview: true` unless `$ARGUMENTS` explicitly says "no external" or
  "claude only".
- `requireExternal: true` when `$ARGUMENTS` explicitly asks for external review,
  so a machine with no external reviewer configured reports the shortfall
  instead of a quiet Claude-only panel.

With that contract, follow the adversarial-review skill
(`${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/SKILL.md`): step 1 to identify
and pin the artifact, then its **Workflow path** (step 2). When the Workflow
tool is unavailable, follow the skill's manual path (steps 3 to 5) with the same
external contract instead of failing. Present the result per the skill's Output
section, including which cross-family reviewers weighed in and which were absent
and why.

Do not edit the artifact. Do not block. The user decides what to act on.
