---
name: design-doc
description: Draft a design doc (RFC) using a standard 8-section structure (Summary, Problem, Goals, Architecture, Risks, Testing & Rollout, Alternatives, Open Questions) with per-section guidance. Use this whenever the user wants to write, draft, or structure a new design document, design doc, technical design, or RFC for a feature, system, or service before implementation. Triggers include explicit phrases like "write a design doc", "design doc for X", "draft an RFC", or "technical design for", and also requests that describe the artifact by its parts without naming it, like "write it up properly before we build, with goals, risks, and a rollout plan". This skill authors the written artifact. Do not use it to break an already-agreed design into implementation steps (use writing-plans), to review or poke holes in an existing doc (use adversarial-review), to summarize or edit a doc that already exists, or for an open-ended "walk me through the architecture options" conversation with no doc in mind (use brainstorming).
---

# Design Doc

Produce a design doc: the written artifact that captures *what* we're building,
*why*, the chosen approach, and what could go wrong, so a reader who was not in
the room can evaluate it. It sits between exploration and execution in the flow:
brainstorming (explore intent) then this design doc (commit the approach to
writing) then `adversarial-review` (poke holes) then `writing-plans` (break it
into steps) then implement.

## When this applies

- A non-trivial feature, system, or service that benefits from a written design
  before code, especially one with meaningful trade-offs or cross-team impact.
- The user asks for a design doc, RFC, or technical design.

Not this: a quick exploratory conversation with no artifact yet (use
brainstorming), turning an already-agreed design into ordered implementation
steps (use writing-plans), or reviewing existing code or a PR (use your
code-review skill).

## How to use the template

The 8 sections below are a skeleton, not a checklist to fill mechanically. Each
section must earn its place: if one adds nothing for this particular doc, cut it
and say you cut it, because empty-but-present sections train readers to skim past
everything. Write for a teammate or a future version of yourself who lacks
today's context.

This template is stack-agnostic on purpose. For house specifics (the diagram
format, the interface and API style, how features roll out, the observability
stack, where design docs are stored), follow the repo's `AGENTS.md` or
`CLAUDE.md` and fill any gap with the project's sensible default. The template
says *what* each section needs; the project's conventions say *how* it's
expressed here.

## The template

### 1. Summary

A TL;DR a busy reader absorbs in thirty seconds: what we're building, why, and
the chosen approach in two or three sentences. Write it last. If a reader reads
only this, they should know what is changing and why it matters.

### 2. Problem Statement / Background

What is broken or missing, who is affected, and why now. Give the context a
newcomer needs: current state, constraints (team size, timeline, existing
stack), and the assumptions you are treating as given. State assumptions
explicitly so reviewers can challenge the ones that may not hold, that is usually
where a design quietly goes wrong.

### 3. Goals

What success looks like, stated so you can tell whether you hit it.

- **Functional goals**: what it does.
- **Non-functional goals**: scale, latency, availability, cost. Put numbers on
  them where you can (targets and budgets), so the architecture can be checked
  against them later.
- **Out of scope** (only when the boundary is genuinely ambiguous): if a
  reviewer could reasonably ask "why not also X", say what you are deliberately
  not doing and why. Skip it when the scope is obvious, a list of trivial
  non-goals reads as filler.

Measurable beats aspirational. "p95 under 200ms at 1k rps" is a goal; "fast and
scalable" is not.

### 4. Architecture / System Design

The heart of the doc. Show the shape before the detail.

- **High-level**: a component or data-flow diagram of the main pieces and how
  requests and data move between them.
- **Interfaces and contracts**: service or API boundaries, message or event
  shapes, the key data models, and storage choices.
- **Mechanics worth calling out**: caching, queues and events, error handling
  and retries, idempotency, and failure or fallback behavior.
- **Scale and reliability**: a rough load estimate, where it scales, single
  points of failure, and how it is observed (the metrics and alerts that matter).
- **Cross-cutting concerns**: security, privacy, and observability. Call these
  out next to the design that raises them rather than leaving them implicit, they
  are the easiest concerns to skip and the most expensive to retrofit. Note who
  is allowed to do what, how sensitive data is handled, and how the behavior is
  traced.

Make each non-obvious decision explicit with its rationale. Leave the menu of
options you rejected for the Alternatives section.

### 5. Risks, Mitigations & Unknowns

For each material risk: what could go wrong, its likelihood and impact, and the
mitigation or fallback. Separate known risks (you have a plan) from genuine
unknowns (you need a spike or data to resolve them). Include what you would
revisit as the system grows: the decisions that are fine now but will not hold at
ten times the load or scope.

### 6. Testing & Rollout

How you will know it works, and how it reaches production safely.

- **Test strategy**: what is unit vs integration vs e2e, following the project's
  testing conventions. Cover new behavior with tests.
- **Observability**: the metrics, logs, and alerts that confirm health after
  launch.
- **Success metrics**: the few measurements that show the Goals were actually
  met, not just that the system is healthy, each tied back to a goal. This is the
  launch acceptance bar.
- **Rollout**: staged so it can be turned off or backed out (a feature flag,
  canary, or phased ramp), any migration or backfill steps, and the explicit
  rollback trigger.

### 7. Alternatives considered (if any)

The options you rejected and why. For each: a one-line description and the
trade-off that killed it (complexity, cost, team familiarity, time to market,
maintainability). This is where reviewers check your reasoning, so be honest
about the close calls. Omit the section only if there genuinely were no real
alternatives, and say so rather than leaving it blank.

### 8. Open Questions

Unresolved decisions, things you want feedback on, and dependencies on other
people or teams. Make each a concrete question with an owner where known, so the
doc drives decisions instead of stalling on them. As a question resolves, fold
the answer into the relevant section and clear it.

## After the draft

- Run the `adversarial-review` skill on the finalized doc (hidden-assumptions,
  gaps, and feasibility lenses) before it drives implementation. The doc review
  is the cheapest place to catch a wrong approach.
- Once the design is agreed, use `writing-plans` to turn it into ordered
  implementation steps.

## Anti-patterns

- **Filling every section to look thorough.** Cut what does not apply and say so.
  A padded doc gets skimmed, which defeats the point.
- **Solution in search of a problem.** If the Problem Statement is thin, the doc
  is premature. Go back to brainstorming.
- **Aspirational goals.** A goal you cannot test against is a slogan. Put numbers
  on the non-functional ones.
- **Hiding the trade-offs.** A design with no alternatives and no risks reads as
  unconsidered, not as bulletproof.
- **Diagram as decoration.** A diagram that only restates the prose adds nothing.
  Show structure the words cannot.
- **Letting open questions rot.** Stale unanswered questions mean the doc has
  stopped being the source of truth.
