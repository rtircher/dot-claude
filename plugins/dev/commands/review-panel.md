---
description: Guaranteed adversarial review. Claude lens panel plus every available cross-family external reviewer, run for real
allowed-tools: Bash(git:*), Bash(sha256sum:*), Read, Glob, Grep, Workflow
---

Run one adversarial-review pass with external review ON by default (all
reviewers the environment actually has). Takes ONE explicit artifact argument:
a file path (spec/plan), a diff range like `main...HEAD`, or a PR/branch; plus
an optional "no external" / "claude only" modifier. This command is the
*guaranteed* path: it always dispatches the `dev-adversarial-review` Workflow
with `externalReview: true`, pins the artifact with a digest, and the workflow
really runs each cross-family reviewer, verifies every returned vote against
that digest, and reports any reviewer it could not run (never a phantom
"external" vote).

Steps:

1. Identify the artifact from `$ARGUMENTS` (a file path, a PR/branch, or a
   range like `main...HEAD`). An explicit argument is REQUIRED; the only
   allowed inference is a bare invocation on a branch with one unambiguous
   diff against the trunk (use `<trunk>...HEAD`). Anything else: ask once,
   then proceed. Never guess by recency or "most recently written" anything.
   Determine `artifactType` (`spec`, `plan`, or `diff`).
2. For a diff, prefer a COMMITTED range of the exact form `<ref>...HEAD`
   (Codex reviews only that form; other shapes drop the Codex vote with a
   refusal). Pin the SHA: `git rev-parse --short HEAD`. Set `diffRange`,
   `pinnedSha`, `repoDir`. If the artifact is an UNCOMMITTED working-tree
   diff, warn that any write between digest and review (this session, an
   editor autosave, a hook) will drop the external votes, and offer to commit
   or stash first.
3. Compute the expected artifact digest from the repo root. This pins the
   exact bytes every external tool must have reviewed:

   For a diff (use the exact range from step 2):

       expected="$(git diff main...HEAD | sha256sum | cut -d' ' -f1)"

   For a spec/plan file:

       expected="$(sha256sum "docs/superpowers/plans/the-plan.md" | cut -d' ' -f1)"

   For an uncommitted working-tree diff, RE-RUN this immediately before step 4
   (minimizes, does not eliminate, the pin-to-review window; a committed range
   has no such window). The digest goes ONLY into the Workflow args. NEVER
   paste it into any prompt, agent instruction, or chat text: the workflow
   holds it and compares each external vote's self-reported sha to it after
   the couriers return. A digest a courier has seen proves nothing.
4. Invoke the Workflow tool with `name: "dev-adversarial-review"` and args:
   `{ artifactType, artifactPath, diffRange, pinnedSha, repoDir,
   externalReview: true, expectedArtifactSha256: "<expected>",
   skillScriptsDir: "${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts",
   focus, outOfScope }`.
   Pass `externalReview: false` ONLY if `$ARGUMENTS` explicitly says
   "no external" or "claude only".
5. Present the result per the adversarial-review skill's Output section,
   including `external.ran` and `external.dropped` so the user sees exactly
   which cross-family reviewers weighed in and which were absent and why.

Do not edit the artifact. Do not block. The user decides what to act on.
