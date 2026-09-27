---
description: Guaranteed adversarial review. Claude lens panel plus every cross-family external reviewer this machine configures, run for real
allowed-tools: Bash(git:*), Bash(gh pr view:*), Bash(sha256sum:*), Bash(shasum:*), Bash(node:*), Bash(cat:*), Bash(mktemp:*), Read, Glob, Grep, Workflow, Agent
---

Run one adversarial-review pass with external review ON by default (every
reviewer this machine's `EXTERNAL_REVIEWERS` config lists; none configured
means a Claude-only panel). Each external vote is bound to the artifact by
digest, and any reviewer that could not run is reported, never a phantom
"external" vote.

Contract, stricter than a bare use of the skill:

- `$ARGUMENTS` names ONE explicit artifact: a file path (spec/plan), a diff
  range like `main...HEAD`, a branch, or a GitHub PR number or URL (resolved
  per the router's Step 0, never by switching the
  user's branch); plus an optional "no external" /
  "claude only" modifier. The only allowed inference is a bare invocation on a
  branch with one unambiguous diff against the trunk. Anything else: ask once,
  then proceed.
- `externalReview: true` unless `$ARGUMENTS` explicitly says "no external" or
  "claude only".
- `requireExternal: true` when `$ARGUMENTS` explicitly asks for external review,
  so a machine with no external reviewer configured reports the shortfall
  instead of a quiet Claude-only panel.

With that contract, follow the router
(`${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/SKILL.md`): its Step 0 to
resolve the artifact and its focus loader to load any review focus, forcing
the **full tier** regardless of what Step 0 would otherwise pick. Then follow
`full.md`'s step 1 to pin the artifact and its **Workflow path** (step 2). When
the Workflow tool is unavailable or the run errors, follow `full.md`'s manual
path (steps 3 to 5) with the same external contract instead of failing.
Present the result per the router's output contract, including which
cross-family reviewers weighed in and which were absent and why.

Do not edit the artifact. Do not block. The user decides what to act on.
