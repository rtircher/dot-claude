---
name: autonomous-feature
description: >-
  Run one feature through spec, review, plan, review, implement, review with
  minimal supervision, stopping only for decisions that need the user. Triggers:
  "run the full pipeline", "spec it, review it, plan it, then build it", "take
  this end to end", "only ping me if you need a decision". Not for an ordinary
  add/build ask or a request for a single phase.
disable-model-invocation: true
---

# Autonomous Feature

Run a feature end to end, spec, adversarial review, plan, adversarial review,
implementation, adversarial review of the code, with as little human input as
the work safely allows. This is the orchestrator that chains the individual
skills you'd otherwise invoke one at a time, plus an explicit contract for *when
to keep going* versus *when to stop and ping the human*.

It is **explicitly invoked only**, as the slash command `/dev:autonomous-feature`
(the skill is hidden from model invocation). The human, by invoking it, has already
decided this feature is low-risk enough to run heads-down. This skill does not
re-judge that decision, but the ping criteria below are the safety net that
catches the cases where "low-risk" turns out to be wrong mid-flight.

## When this applies

- The user explicitly wants the whole pipeline run with minimal back-and-forth.
- The feature is well-enough understood that a spec can be drafted without a long
  interview.

An ordinary "add X" / "build Y" request is not a reason to use this. If the user
wants only a spec, only a plan, only a review, only the implementation, or wants
to drive each step themselves, this is the wrong skill, use the underlying skills
directly (brainstorming, design-doc, writing-plans, adversarial-review,
subagent-driven-development).

`references/` paths below are relative to this skill's base directory; read them with an absolute path from there.

## Modes

Read the invocation argument to pick the mode. Both modes run the **same
pipeline** and honor the **same ping criteria**, the only difference is what a
*phase boundary* means.

- **Default (no argument):** heads-down. At each phase boundary, post a concise
  checkpoint summary and **keep going**. The human can interrupt, but is not
  required to.
- **`pause` (e.g. `/dev:autonomous-feature pause`):** gated. At each phase boundary,
  post the same checkpoint summary and then **stop and wait** for explicit
  approval before starting the next phase.

A phase boundary is the seam between phases (spec done → review, review done →
plan, etc.). Mid-phase, both modes behave identically.

## Third-party review (`external-review` argument)

Adversarial-review phases inherit external-on by default from `dev:review-workflow`; the
local endpoint reviewer and Codex run without a per-phase consent stop (an autonomous-feature
invocation is itself user-initiated consent). The `external-review` argument is **force/confirm**,
not an enable switch: it demands that external reviewers actually ran in round 1. A round-1
`external.shortfall` in a forced run IS ping-worthy; later-round degradation is reported, never pinged.
Read `references/third-party-review.md` when the `external-review` argument is given or an
external reviewer is in play.

## Bias to simplicity, active in every phase

Running heads-down removes the human's chance to say "that's more than we need"
mid-flight, so the bias toward the simplest workable design has to be built into
the pipeline itself. It applies to every phase:

- **Spec and plan the simplest thing that meets the intent.** No speculative
  extensibility, config surfaces, abstraction layers, or generality that no stated
  requirement asks for. Complexity introduced in the spec propagates into the plan
  and multiplies in the code, so this is cheapest to hold the line on early.
- **Every adversarial-review phase carries an over-engineering lens** alongside its
  other lenses: flag speculative generality, unnecessary abstraction, unused
  flexibility, premature optimization, and any flag/knob/layer nothing in the spec
  requires. A simpler design that meets the spec is a valid review finding, not a
  nitpick.
- **Prefer starting too small.** When unsure between a lean design and a richer
  one, spec the lean one and note the heavier option as a deferred alternative.
  Adding structure later is cheap; unwinding an abstraction that never paid off is
  not.

## The ping contract, active in BOTH modes

Stop and ask the human, regardless of mode, even mid-phase, when you hit any of
these. These are the things that are expensive or impossible to undo, or that
invalidate the premise you're working from:

- **Premise-breaking review finding.** An adversarial reviewer surfaces something
  that questions whether the feature should be built as conceived at all (not a
  fixable defect, a "this whole approach is wrong" finding).
- **Requirements ambiguity that changes the design.** Not every ambiguity, only
  one where different reasonable interpretations lead to materially different
  implementations. Resolve trivial ambiguities yourself and note the assumption.
- **Destructive or irreversible action.** Deleting data, schema/data migrations,
  force-push, rewriting history, publishing to an external service, anything
  touching production, anything that spends money. (Third-party review sends are
  pre-authorized, per the Third-party review section above, and never trigger
  this ping; every other external publish still stops.)
- **Scope expansion.** The work is drifting beyond what the agreed spec covers.
  Don't silently grow the feature, surface it and let the human decide.
- **Security-sensitive decision.** Auth, secrets/credentials, cryptography,
  access control, handling of PII. Get a human in the loop rather than guessing.

Every stop costs the human attention, so do not ping outside this list, and do
not stall second-guessing whether the feature is worth building: the spec review
is for that. When you ping, give the human a tight decision: what you found, the
options, and your recommendation. Then wait.

## Confidence gates

Each adversarial-review phase loops until the artifact is *clean* or you hit the
iteration cap. "Clean" has an explicit definition so it can't be satisfied by
hand-waving:

- **No unaddressed blocker or major findings.** Every blocker/major is either
  fixed in the artifact or explicitly deferred with a written rationale (why it's
  safe to defer, and to where).
- **Minor findings** are fixed or consciously waived, a one-line note is enough.

**Iteration cap: 3 review→fix rounds per artifact.** If findings still aren't
resolved after the third round, stop looping and ping the human with the
remaining contested findings and your assessment, repeated rounds that don't
converge usually mean a judgment call only the human can make.

Each fix round must re-run the review on the *revised* artifact, not assume a fix
landed. A finding is only closed when a fresh review no longer raises it.

## Coordinator discipline

The main session is a **thin coordinator**, not a worker: its context holds only the TodoWrite
phase list, file *paths* to the spec and plan, each phase's compact summary, and ping-relevant
findings. Delegate anything that requires reading or producing a lot; pass paths, not inline text;
run verification in a sub-agent that returns pass/fail plus failures only.
Phase 1 stays in the main session (brainstorming is interactive), but writes its output to a spec file.
**Ping signal survives summarization:** only the main session can stop and ask the human, so a
sub-agent's return MUST surface blocker/major findings and any ping-contract trigger verbatim.
Compactness never wins over a lost ping signal.
Read `references/coordinator-discipline.md` when deciding whether to read raw material in the main session.

## Pipeline

Track the phases with TodoWrite so progress is visible. Run them in order.

This pipeline **composes other skills** for the spec, plan, execution, and
verification steps. Resolve each by capability (brainstorming, planning,
subagent-driven execution, verification) from the skills this environment
provides. If none exists for a step (e.g. no verification skill), fall back to
the inline behavior described for that phase.


**Delegate adversarial review to this plugin's Workflow when the Workflow tool is available.** Where
the phases say "the `adversarial-review` skill", dispatch `dev:gated-review` instead
(`dev:review-workflow` for a single advisory pass). The ping contract stays with this coordinator:
read the returned findings and stop per the contract. If the Workflow tool is unavailable, use the
`adversarial-review` skill as written. Read `references/review-delegation.md` before dispatching it,
for how to build its args.

### Phase 1, Spec

Use your brainstorming skill to settle intent and requirements, then follow its
handoff: this plugin's `design-doc` skill writes the spec when the change needs a
design doc, and brainstorming's requirements note is the spec when it does not.
Don't over-interview, this skill exists to move with minimal input; fill
reasonable gaps with stated assumptions and only ping on design-changing
ambiguity.

**The spec MUST include a Non-goals section.** List what this feature
deliberately does not do, the adjacent capabilities, generalizations, and
config surfaces that were considered and excluded. Downstream phases treat the
spec as the scope contract: anything not in its requirements is out of scope
for implementers, and reviewers judge against it. Scope that sneaks into the
spec here gets legitimized by every later phase, so the Non-goals section is
where the line is drawn while it's still one sentence to draw.

**Boundary:** checkpoint with the spec summary. (pause mode: wait for approval.)

### Phase 2, Review the spec

Use the `adversarial-review` skill on the spec, then address findings to the
confidence gate above. Watch specifically for premise-breaking findings here, this is the
cheapest place to discover the feature is wrong, so weight the spec review's ping
threshold lower than later phases.

**Boundary:** checkpoint with what the review found and how it was resolved.
(pause mode: wait for approval.)

### Phase 3, Implementation plan

Use your planning skill to turn the clean spec into a step-by-step
implementation plan.

**Boundary:** checkpoint with the plan summary. (pause mode: wait for approval.)

### Phase 4, Review the plan

Use the `adversarial-review` skill on the plan, then address findings to the
confidence gate.

**Boundary:** checkpoint with the review outcome. (pause mode: wait for approval.)

### Phase 5, Implement

Execute the clean plan. Prefer your subagent-driven execution skill for plans with independent
tasks; use a plan-execution skill or inline implementation when that fits better, and say which
you chose and why. Follow the project's own conventions (TDD, verification) as those skills direct.

**When a subagent-driven mode is chosen, the main session does not edit
implementation files at all.** Every task goes to a fresh implementer subagent
and every review fix goes to a fix subagent, a task that feels too small to
brief gets folded into an adjacent task's brief, not done inline. Inline edits
during plan execution are how the orchestrator quietly becomes the worker and
the session's context (and cost) balloons.

**Every implementer dispatch brief carries the simplicity contract**, since subagents never see this
skill: an implementer building more than its brief describes is the scope-expansion ping firing one
level down, so surface it, don't merge it. Read `references/implementation-dispatch.md` when
dispatching subagents, for agent types, model tiers, and the contract text.

When implementation is complete, verify before claiming done, use your
verification-before-completion skill
if your environment has one; otherwise run the project's full verification
commands and confirm the output before asserting success.

**Boundary:** checkpoint that implementation is complete and verification passes.
(pause mode: wait for approval.)

### Phase 6, Review the implementation

The code is the most consequential artifact, so it gets the same treatment as the spec and plan:
passing tests confirm the code does what you told it to, not that it is right.

Run the `adversarial-review` skill on the completed work (the branch diff), and for a **multi-task**
plan also run the final cross-implementation symmetry pass over the full branch diff. Read
`references/implementation-dispatch.md` (Phase 6 detail) for the lenses and symmetry-pass parameters.

Address findings to the **same confidence gate** as the earlier reviews: no
unaddressed blocker/major (fixed or deferred-with-rationale), fixes re-verified
and re-reviewed, 3-round cap before pinging. A security-relevant finding here is a
ping per the contract, not a silent fix.

**Boundary:** checkpoint with the review outcome, then re-verify, summarize what
was built, and hand back. (pause mode: wait for approval.)
