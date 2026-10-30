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

1. **Size gate and areas.** Pipe the diff's numstat into
   `<plugin>/skills/adversarial-review/scripts/bucket-areas.sh --areas "<areas:>" --migrations "<migrations:>"`
   (values from the router's focus output, flags omitted when none declared).
   Numstat is `git diff --numstat <remote>/<base>...<headRefOid>` in a clone,
   `git diff --numstat <remote>/<default>...HEAD` for a local diff, or with no
   clone `gh pr view <n> --json files -q '.files[]|[.additions,.deletions,.path]|@tsv'`.
   Its `mode` line is the gate: `single-pass`, or `fan-out` with `bucket` lines
   (one area reviewer each; at most 3, a migrations bucket always keeping a
   slot) and `file` lines mapping each path to its bucket.

3. **Reviewers.** Each reviewer is a `dev:reviewer` agent, dispatched with
   `model: "sonnet"` and `effort: "high"` explicit on every call. Before dispatch, write the
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
   - **Extra lens (scoped, not general).** `<name>` is the first token after
     `Extra lens:`; any parenthetical is a note. If the focus declares one
     gated lens (`Extra lens: <name>`), resolve it at
     `~/.claude/skills/<name>/SKILL.md`; if missing, report `extra lens:
     <name>: not_run (skill not found)`. That skill must supply a gate
     section and a prompt template. The main session applies the gate itself,
     against the diff already saved to the scratchpad (2a saves a full `git
     diff` for this; 2b's saved `gh pr diff` output is the same artifact
     there). If a clone exists but the gate does not fire, report `extra
     lens: <name>: not applicable (<gate reason>)`, with no second wave. When
     the gate fires, create a detached worktree at `headRefOid` (quick is
     otherwise checkout-free), pass it as the lens's `repoDir`, point its
     artifact dir at the scratchpad, never the user's tree, and remove the
     worktree afterwards. Dispatch the one extra agent from that skill's
     prompt template as a **second wave after the area reviewers return**,
     never alongside them, so no more than 3 agents ever run in parallel: use
     the agent type, model, and tools per the declared skill's Dispatch
     section (e.g. a lens that writes model files needs a writing agent);
     default to `dev:reviewer` with `model: "sonnet"` and `effort: "high"`
     only when the skill names none. This overrides any same-message instruction in the skill's
     Dispatch section. This is the only way this tier exceeds 3 agents; the
     cap with it is 4 total. In the no-clone case (2b), the gate cannot run
     at all: report `extra lens: <name>: not_run (no clone)`.

   Each reviewer's brief is fixed: the four `brief`s of the `diff` panel in
   `LENS_PANELS` (`<plugin>/workflows/adversarial-review.js`) as one checklist,
   in code order, verbatim, then the `brief` of `PROSE_LENS` (the constant beside
   it) marked advisory: its findings carry no severity, go to the Prose section,
   and never move the area verdict. Only the reviewer whose slice is first (or
   the single pass) covers the PR description and commit messages, so they are
   not reviewed once per area.

   The brief also carries the focus text, the PR description fenced as in
   the router's PR description section, the findings schema
   (`{ objection, severity (blocker | major | minor), confidence (verified |
   speculative), location, suggested_fix }`; prose findings drop `severity`),
   and a per-area verdict phrased `ship (quick, unverified)` or
   `don't-ship (quick)`, never a bare `ship`.

4. **Consolidate** in the main session with no extra agent: dedupe, promote
   cross-area findings, route the prose findings to `## Prose` (never the punch
   list or the verdict), then apply the router's output contract. When the
   extra lens ran, cross-check each blocker/major from the area reviewers:
   would the extra lens's model have caught it too? If not, name the
   mechanism it lacks, not just "it missed this".

5. **Offer next steps.** Escalate to the full panel, stating its agent count
   (for example "full panel: about 13 agents" at work with the extra lens),
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
router's local-diff read (Step 0 item 3: `git diff <remote>/<default>...HEAD`),
or report that it cannot read the PR.
