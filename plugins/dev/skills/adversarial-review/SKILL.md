---
name: adversarial-review
description: Use when you want independent, adversarial review of a plan, spec/design doc, or PR/diff before committing to it — reviewers prompted to find what's wrong, not rubber-stamp. Triggers on "adversarial review", "independent review", "poke holes in this", "red-team this plan/spec/PR", or when a plan/spec is finalized and about to become implementation.
---

# Adversarial Review

Run independent, skeptical reviewers against a plan, spec, or diff and return one
deduped, severity-ranked list of objections. Reviewers are told to find what is
**wrong** — not to approve. Advisory only: this skill never edits files and never
blocks.

## When this applies

- A plan, spec, or design doc is finalized and about to drive implementation.
- A PR / branch diff is ready and you want a hostile read before merge.
- The user explicitly asks to red-team / poke holes in / independently review an
  artifact.

If the user just wants a quick opinion, that's not this — this dispatches
multiple independent reviewers and costs tokens. Use it when the artifact
matters.

## Procedure

### 1. Identify the artifact

Determine what is under review and its type:

- **Spec / design doc** — a requirements or design document.
- **Plan** — an implementation plan (steps, sequencing, tasks).
- **PR / diff** — code changes (a branch diff or GitHub PR).

If the user pointed at a file or PR, use that. If invoked bare, infer from the
current branch (uncommitted/committed diff) or the most recently written
spec/plan. If genuinely ambiguous, ask which artifact — one question, then
proceed.

### 2. PR / diff → delegate

If the artifact is a **PR or code diff**, do not hand-roll code review. Use the
`/code-review` skill, with effort scaled to diff size (larger or riskier diffs →
higher effort). Surface its findings. Stop here — the lens-based panel below is
for documents.

### 3. Pick lenses scaled to the artifact

Choose independent reviewer lenses by artifact type. Each lens is a distinct
failure mode, not a redundant copy:

| Artifact | Lenses |
|----------|--------|
| Spec / design doc | **hidden-assumptions** (what is taken for granted that may not hold) · **gaps & underspecification** (what's undefined, ambiguous, or missing) · **contradiction & feasibility** (internal conflicts, can it actually be built as described) |
| Plan | **sequencing & dependencies** (wrong order, unstated prerequisites, hidden coupling) · **risk & failure modes** (what breaks, what's unrecoverable, what's untested) · **scope & YAGNI** (over-build, gold-plating, work that serves no stated goal) |

Use all the lenses for the artifact type. Drop a lens only if it is clearly
irrelevant to the specific artifact, and say so.

### 4. Dispatch independent reviewers — in parallel

Dispatch one `Agent` per lens, **all in a single message** so they run
concurrently with fresh, independent context. Each reviewer gets:

- The full artifact (paste it or give the file path).
- Its assigned lens, and only that lens.
- The adversarial framing (below).
- A request to return structured findings:
  `{ objection, severity (blocker | major | minor), location, suggested_fix }`.

**Adversarial framing to give each reviewer (paraphrase into the prompt):**

> Your job is to find what is wrong with this artifact through the lens of
> {lens}. Assume the author is over-confident. Surface real problems, not style
> nits. Be specific — point to the exact part. When you are uncertain whether
> something is a problem, flag it rather than letting it pass. End with a single
> verdict: ship or don't-ship, with one sentence why.

Pick each reviewer's model deliberately based on how hard that lens is for this
artifact — do not default one model across the whole panel. (Subtle
feasibility/assumption reasoning may warrant a stronger model than a
straightforward scope pass.)

### 5. Synthesize

Once reviewers return:

1. **Dedup** objections that overlap across lenses into one entry (note which
   lenses raised it — agreement across lenses is signal).
2. **Rank** by severity (blocker → major → minor).
3. Produce **one prioritized list**: each entry = objection · severity ·
   location · suggested fix · which lens(es) raised it.
4. Report **each lens's ship / don't-ship verdict** alongside the list.

## Output

Present to the user:

- The deduped, severity-ranked objection list.
- The per-lens verdicts.

Then stop. Do not edit the artifact, do not block any next step, do not
re-review. The user decides what to act on. If they ask you to address findings,
that's a separate task.

## Anti-patterns

- **Agreeable review.** If reviewers come back with "looks good, minor nits,"
  the framing was too soft. Reviewers must hunt for real problems.
- **Redundant lenses.** Three reviewers finding the same class of issue wastes
  the panel. Keep lenses distinct.
- **Sequential dispatch.** Reviewers must be independent — dispatch them in one
  message, never feed one reviewer's output to the next.
- **Reinventing code review.** For diffs, delegate to `/code-review`. Don't
  rebuild it here.
