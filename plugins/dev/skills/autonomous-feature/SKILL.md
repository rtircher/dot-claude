---
name: autonomous-feature
description: Use when the user explicitly asks to run a whole feature through the full spec → adversarial-review → plan → adversarial-review → implement → adversarial-review pipeline with minimal supervision — e.g. "run the full pipeline", "spec it, review it, plan it, then build it", "take this all the way through with minimal input from me", "handle it end to end and only ping me if you need a decision", or the /autonomous-feature command. Do NOT trigger on an ordinary "add X" / "build Y" request, or on a request for only a spec, only a plan, only a review, or only the implementation — those belong to the individual skills (brainstorming, writing-plans, adversarial-review, subagent-driven-development). Pass a "pause" argument to gate for approval after each phase instead of running heads-down.
---

# Autonomous Feature

Run a feature end to end — spec, adversarial review, plan, adversarial review,
implementation, adversarial review of the code — with as little human input as
the work safely allows. This is the orchestrator that chains the individual
skills you'd otherwise invoke one at a time, plus an explicit contract for *when
to keep going* versus *when to stop and ping the human*.

It is **explicitly invoked only**. The human, by invoking it, has already
decided this feature is low-risk enough to run heads-down. This skill does not
re-judge that decision — but the ping criteria below are the safety net that
catches the cases where "low-risk" turns out to be wrong mid-flight.

## When this applies

- The user explicitly wants the whole pipeline run with minimal back-and-forth.
- The feature is well-enough understood that a spec can be drafted without a long
  interview.

If the user wants only a spec, only a plan, only a review, or wants to drive each
step themselves, this is the wrong skill — use the underlying skills directly.

## Modes

Read the invocation argument to pick the mode. Both modes run the **same
pipeline** and honor the **same ping criteria** — the only difference is what a
*phase boundary* means.

- **Default (no argument):** heads-down. At each phase boundary, post a concise
  checkpoint summary and **keep going**. The human can interrupt, but is not
  required to.
- **`pause` (e.g. `/autonomous-feature pause`):** gated. At each phase boundary,
  post the same checkpoint summary and then **stop and wait** for explicit
  approval before starting the next phase.

A phase boundary is the seam between phases (spec done → review, review done →
plan, etc.). Mid-phase, both modes behave identically.

## The ping contract — active in BOTH modes

Stop and ask the human — regardless of mode, even mid-phase — when you hit any of
these. These are the things that are expensive or impossible to undo, or that
invalidate the premise you're working from:

- **Premise-breaking review finding.** An adversarial reviewer surfaces something
  that questions whether the feature should be built as conceived at all (not a
  fixable defect — a "this whole approach is wrong" finding).
- **Requirements ambiguity that changes the design.** Not every ambiguity — only
  one where different reasonable interpretations lead to materially different
  implementations. Resolve trivial ambiguities yourself and note the assumption.
- **Destructive or irreversible action.** Deleting data, schema/data migrations,
  force-push, rewriting history, publishing to an external service, anything
  touching production, anything that spends money.
- **Scope expansion.** The work is drifting beyond what the agreed spec covers.
  Don't silently grow the feature — surface it and let the human decide.
- **Security-sensitive decision.** Auth, secrets/credentials, cryptography,
  access control, handling of PII. Get a human in the loop rather than guessing.

When you ping, give the human a tight decision: what you found, the options, and
your recommendation. Then wait.

## Confidence gates

Each adversarial-review phase loops until the artifact is *clean* or you hit the
iteration cap. "Clean" has an explicit definition so it can't be satisfied by
hand-waving:

- **No unaddressed blocker or major findings.** Every blocker/major is either
  fixed in the artifact or explicitly deferred with a written rationale (why it's
  safe to defer, and to where).
- **Minor findings** are fixed or consciously waived — a one-line note is enough.

**Iteration cap: 3 review→fix rounds per artifact.** If findings still aren't
resolved after the third round, stop looping and ping the human with the
remaining contested findings and your assessment — repeated rounds that don't
converge usually mean a judgment call only the human can make.

Each fix round must re-run the review on the *revised* artifact, not assume a fix
landed. A finding is only closed when a fresh review no longer raises it.

## Pipeline

Track the phases with TodoWrite so progress is visible. Run them in order.

### Phase 1 — Spec

Use the `superpowers:brainstorming` skill to turn the feature request into a spec
/ design doc. Capture intent, requirements, and the shape of the design. Don't
over-interview — this skill exists to move with minimal input; fill reasonable
gaps with stated assumptions and only ping on design-changing ambiguity.

**Boundary:** checkpoint with the spec summary. (pause mode: wait for approval.)

### Phase 2 — Review the spec

Use the `adversarial-review` skill on the spec. Then address findings to the
confidence gate above. Watch specifically for premise-breaking findings here —
this is the cheapest place to discover the feature is wrong, so weight the spec
review's ping threshold lower than later phases.

**Boundary:** checkpoint with what the review found and how it was resolved.
(pause mode: wait for approval.)

### Phase 3 — Implementation plan

Use the `superpowers:writing-plans` skill to turn the clean spec into a
step-by-step implementation plan.

**Boundary:** checkpoint with the plan summary. (pause mode: wait for approval.)

### Phase 4 — Review the plan

Use the `adversarial-review` skill on the plan (sequencing, risk, scope lenses).
Address findings to the confidence gate.

**Boundary:** checkpoint with the review outcome. (pause mode: wait for approval.)

### Phase 5 — Implement

Execute the clean plan. Prefer the `superpowers:subagent-driven-development`
skill for plans with independent tasks; use `superpowers:executing-plans` or
inline implementation when that fits better — use judgment, and say which you
chose and why. Follow the project's own conventions (TDD, verification) as those
skills direct.

When implementation is complete, verify before claiming done
(`superpowers:verification-before-completion`).

**Boundary:** checkpoint that implementation is complete and verification passes.
(pause mode: wait for approval.)

### Phase 6 — Review the implementation

The spec and plan were reviewed; the code is the most consequential artifact, so
it gets the same treatment. Reviewing only the upstream documents and trusting
the build is the asymmetry this phase exists to close — passing tests confirm the
code does what you told it to, not that what you told it to do is right.

Run the `adversarial-review` skill on the completed work (the branch diff). For a
code diff it delegates to `/code-review` with effort scaled to diff size/risk —
let it. For a **multi-task** plan, also run the final cross-implementation
symmetry pass (sonnet+) over the full branch diff to catch type asymmetry,
parallel-structure drift, undocumented behavior, and cross-package coupling that
per-task work misses.

Address findings to the **same confidence gate** as the earlier reviews: no
unaddressed blocker/major (fixed or deferred-with-rationale), fixes re-verified
and re-reviewed, 3-round cap before pinging. A security-relevant finding here is a
ping per the contract, not a silent fix.

**Boundary:** checkpoint with the review outcome, then re-verify, summarize what
was built, and hand back. (pause mode: wait for approval.)

## Anti-patterns

- **Re-judging risk.** The human chose to run this autonomously. Don't stall by
  second-guessing whether the feature is worth building — that's what the spec
  review is for. Use the ping criteria, not general anxiety.
- **Pinging on the trivial.** Every stop costs the human attention, which defeats
  the purpose. Reserve pings for the contract above; resolve small ambiguities
  yourself and record the assumption.
- **Soft confidence gates.** "The review looks mostly fine" is not the gate. No
  unaddressed blocker/major, or it's not clean.
- **Skipping the re-review.** Applying a fix is not the same as confirming it.
  Closed findings must survive a fresh review.
- **Silent scope creep.** If you find yourself building more than the spec
  describes, that's a ping, not a bonus.
- **Treating green tests as the code review.** Verification confirms behavior
  matches the plan; it does not surface bad abstractions, security holes, or
  cross-package drift. Phase 6 is not optional just because the build is green.
