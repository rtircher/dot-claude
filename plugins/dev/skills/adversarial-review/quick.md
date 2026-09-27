# Quick tier

Budget: at most 3 area reviewers, dispatched in one message; the focus-declared
extra lens, if it fires, is a second wave after they return: 4 agents total,
never more than 3 in parallel. 1 agent when the diff is small. This tier never
escalates to full on its own.

You arrive here after the router's Step 0 (input resolved, focus loaded as
`focus` text plus parsed `Areas:`, `Migrations:`, `Extra lens:` values, tier
picked as quick). This file is the quick procedure only; the output contract
belongs to the router.

## Procedure

1. **Size gate.** Use the PR metadata already resolved (`gh pr view`'s
   `files`/`additions`/`deletions`, or `git diff --numstat` for a local diff).
   Run a **single pass** when fewer than 10 files changed and fewer than 200
   lines added plus deleted, or when all files map to one area. Otherwise fan
   out by area.

2. **Areas.** `Areas:` is a plain list of path prefixes. Each file maps to the
   longest matching prefix, else its top-level directory. If the focus names
   a `Migrations:` prefix, that prefix always takes one of the 3 area slots
   and never merges into `misc`. Remaining areas merge smallest-first into
   `misc` until they fit the remaining 2 slots. The cap of 3 area reviewers
   always holds, Migrations included.

3. **Reviewers.** Each reviewer is a `dev:reviewer` agent, dispatched with
   `model: "sonnet"` explicit on every call. Before dispatch, write the
   reviewer orientation list (output contract item 4) from the PR metadata
   and diff already fetched, emitted in the same message as the dispatch. All
   area reviewers go out together in one message.
   - A single pass uses one agent over the whole diff.
   - A fan-out uses one agent per area, each reading its own slice via the
     router's read method: in a clone (2a), `git diff
     <remote>/<base>...<headRefOid> -- <files>` for the slice and `git show
     <headRefOid>:<path>` for context; with no clone (2b), the saved `gh pr
     diff` path plus that area's file list, context via `gh api
     repos/{o}/{r}/contents/<path>?ref=<headRefOid>`.
   - **Extra lens (scoped, not general).** If the focus declares one gated
     lens (`Extra lens: <skill>`), resolve it at
     `~/.claude/skills/<name>/SKILL.md`; if missing, report `extra lens:
     <name>: not_run (skill not found)`. That skill must supply a gate
     section and a prompt template. The main session applies the gate itself,
     against the diff already saved to the scratchpad (2a saves a full `git
     diff` for this; 2b's saved `gh pr diff` output is the same artifact
     there). When the gate fires, create a detached worktree at `headRefOid`
     (quick is otherwise checkout-free), pass it as the lens's `repoDir`,
     point its artifact dir at the scratchpad, never the user's tree, and
     remove the worktree afterwards. Dispatch the one extra agent from that
     skill's prompt template as a **second wave after the area reviewers
     return**, never alongside them, so no more than 3 agents ever run in
     parallel. This is the only way this tier exceeds 3 agents; the cap with
     it is 4 total. In the no-clone case (2b), skip the extra lens outright:
     `extra lens: skipped (no clone)`.

   Each reviewer's brief is fixed: the four diff-lens concerns as one
   checklist, in code order.

   <!-- copied from LENS_PANELS.diff in workflows/adversarial-review.js; keep in sync -->
   - correctness: bugs, broken invariants, security holes, cross-package
     coupling, not style
   - simplicity-yagni: needless complexity, a simpler design that does the
     same, reinvented helpers the codebase already has, abstraction/config/
     generality this change does not need. For every new class, base class,
     registry, flag, setting, or extension point ask how many concrete users
     it has in this diff; one means inline it. Safety floor, per the
     conventions' "Simplicity never trims the safety floor" rule: never
     propose trimming input validation at trust boundaries, data-loss error
     handling, security, accessibility, or migration backfill/lock/rollback
     code. Tag each finding in suggested_fix `cut now` when it can be deleted
     or inlined in this change, `follow-up` when it is pre-existing
     over-build, each with an approximate net-lines figure
   - testing: judge coverage by decision branches, not line percentage: list
     each new or changed if/else, match, except, or early return in the
     production diff and name the test that exercises it; flag branches with
     none. Curate, don't append, per the conventions' "Test suite discipline:
     curate, don't append" rule: flag tests that exercise a branch another
     test already covers, tests that cannot fail such as asserting a mock's
     return, a snapshot of a constant, or a getter/setter/pass-through,
     over-mocking that tests the mock, integration or e2e tests that
     re-assert a unit-covered branch, a missing regression test for the bug
     being fixed, and brittle tests coupled to implementation detail. For each
     redundant test name the surviving test and say `delete` or `merge into a
     parametrize table`; a removal is a finding, same as a gap. Report the
     suite delta as `tests +N added / ~M edited / -K deleted vs B branches
     touched`; added far above branches with zero deleted is a major finding
     by default
   - duplication: the same logic introduced more than once. Two forms: (a)
     copy-pasted or near-identical blocks added within THIS diff, across
     functions or files, that should share one implementation; (b) logic in
     this diff that re-implements something the codebase already has
     elsewhere (a validator, a parser, a business rule) without reusing it.
     Distinct from simplicity-yagni's reinvented-helper check, which flags
     unnecessary abstraction and complexity (this lens flags redundant
     OCCURRENCES of the same logic regardless of how simple each occurrence
     is). For each instance, list every location it appears and name the one
     that should remain or the extraction point

   The brief also carries the focus text, the findings schema
   (`{ objection, severity (blocker | major | minor), confidence (verified |
   speculative), location, suggested_fix }`), and a per-area verdict phrased
   `ship (quick, unverified)` or `don't-ship (quick)`, never a bare `ship`.

4. **Consolidate** in the main session with no extra agent: dedupe, promote
   cross-area findings, then apply the router's output contract. When the
   extra lens ran, cross-check each blocker/major from the area reviewers:
   would the extra lens's model have caught it too? If not, name the
   mechanism it lacks, not just "it missed this".

5. **Offer next steps.** Escalate to the full panel, stating its agent count
   (for example "full panel: about 20 agents" at work with the extra lens),
   fix the verified blockers, draft inline comments, or stop.

This tier omits externals, the verify pass, the digest, and synthesis voting,
and claims no independence beyond one reviewer per area: `quick tier:
single-model, unverified`.

## Subagent mode

With no `Agent` tool, the subagent does one inline single pass itself over the
whole diff, labelled `tier: quick (inline, 0 agents)`, only when the caller
asked it to review someone else's PR. A subagent never reviews a diff it
produced in the same task; hand back instead.

## No `gh` auth

Without `gh` auth, this tier cannot resolve a PR at all. Fall back to the
router's local-diff read (4.4 step 4: `git diff <remote>/<default>...HEAD`),
or report that it cannot read the PR.
