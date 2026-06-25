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
higher effort). Surface its findings. If a third-party model is available, also
enlist it as an independent reviewer (see "Enlist a third-party model" below):
a different model family is the most independent second read you can get on a
diff. The lens-based panel in steps 3 and 4 is for documents, not diffs; synthesize a
diff on its own terms (step 6, **Diffs**), where `/code-review` and any
third-party run are the named reviewers and there are no per-lens verdicts.

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
  `{ objection, severity (blocker | major | minor), confidence (verified | speculative), location, suggested_fix }`.
  **verified** = the reviewer opened the artifact / traced the code and confirmed
  the problem; **speculative** = inferred from a smell or a partial read, not
  confirmed. Reviewers must label every finding — a confident-sounding hunch that
  was never checked is the panel's main failure mode.

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

### 5. Enlist a third-party model (optional, when available)

The panel's value is reviewer independence, and a genuinely different model
family is the most independent reviewer you can add: it shares none of Claude's
blind spots. When the artifact matters, enlist one as an extra reviewer
alongside the Claude panel (for docs) or alongside `/code-review` (for diffs).
This is optional, gated on availability and on the user's consent; a missing
third-party tool never blocks the Claude panel.

**Get consent before any artifact leaves the environment.** Enlisting a
third-party model sends the reviewed diff or document to an external vendor's API
(OpenAI for Codex, Cursor for `cursor-agent`). Before running one, confirm with
the user and name where the artifact goes, especially for private repos,
proprietary code, or diffs that may carry secrets or tenant data. Offer to redact
sensitive parts or to skip. If the user does not approve, run the Claude panel
only and report it as Claude-only. Never send an artifact to a third party
silently.

**Codex (first-party plugin).** If the `codex` plugin is installed, the
`/codex:adversarial-review` command runs a challenge review (it questions the
approach, assumptions, and tradeoffs, not just defects); `/codex:review` is the
plainer pass. These are user-invoked commands, so ask the user to run
`/codex:adversarial-review` (foreground for a tiny diff, `--background` for
anything larger) and hand back the output, or fold in a run they already have.
Let the plugin own the Codex invocation and auth; do not hand-roll `codex` CLI
strings. Codex review is read-only. Codex reviews the git diff of the repo it
runs in (scoped by `--base`/`--scope`), so if the artifact lives in a different
repo than your session cwd, run the review from that repo (the companion takes
`--cwd <path>`); otherwise it reviews the wrong tree and returns an empty or
irrelevant diff.

Availability: the `/codex:*` commands exist only once the codex plugin is
installed, and they need the `codex` CLI installed and authenticated. If a run
reports the CLI is missing, tell the user to run `/codex:setup` (it installs via
`npm install -g @openai/codex`, then `codex login`). Until then there is no
Codex reviewer; proceed with the Claude panel.

**Cursor.** There is no first-party Cursor plugin or slash command for Claude
Code. The direct equivalent is to shell out to Cursor's headless CLI, a one-shot
reviewer. Keep the artifact out of argv: a diff pasted into a command argument
leaks through process listings, shell history, and tool logs before it ever
reaches Cursor. Put only instructions on the command line and feed the artifact
on stdin (or a mode-600 temp file):

```bash
cursor-agent -p --output-format text "Adversarially review the diff on stdin.
Find what is wrong, not what is fine." < /path/to/artifact.diff
```

Omit `--force` so it can only report, never edit. Requires `cursor-agent` on
PATH and `CURSOR_API_KEY` set. Check `command -v cursor-agent` first and skip
this reviewer if it is absent.

**Bind every third-party run to the same artifact.** Give the reviewer the
identical target the Claude panel is reviewing: the file path or `base...HEAD`
range (or PR), the same focus and out-of-scope exclusions, and a pinned commit
SHA or diff digest. Require the returned review to state that same target. A
review whose scope you cannot confirm matches the panel's does not count as an
independent vote or as cross-family corroboration in step 6: note it separately
or drop it. A third-party run against the wrong base or repo (see the cwd caveat
above) must never be folded in as agreement.

Treat any third-party output as one more independent reviewer: feed it the same
adversarial framing, then fold its findings into the synthesis. Record which
source raised each finding as private bookkeeping — you need it to count
independent sources and detect cross-family agreement — but do **not** carry
model identity into the scoring step. Synthesize blind to source (see step 6):
agreement across independent reviewers is strong signal, and a lone finding from
a different model family is exactly the blind spot you enlisted it to catch — but
*which* model said it must not move a finding's rank. Naming a prestige source
during scoring biases the synthesizer (Claude systematically over-weights some
third-party models); the count and the cross-family-ness are the signal, the
brand name is not.

### 6. Synthesize

**Score blind to model identity.** Before synthesizing, strip the reviewers'
model names from their findings — work from anonymized handles (Reviewer A/B/C…)
plus each finding's lens. Identity is prestige bias: knowing a finding came from a
particular third-party model makes the synthesizer over- or under-weight it
regardless of merit. What you keep is *how many independent reviewers* raised a
finding and *whether that agreement crosses model families* — those are the real
signals. Re-attach source names only after ranking is fixed, and only if the user
asked who said what.

Once reviewers return (including any third-party model you enlisted): for a
document the reviewers are the lens panel; for a diff they are `/code-review`
plus any third-party run.

1. **Account for who actually voted.** State the panel that returned versus the
   panel you dispatched — e.g. "3 of 4 reviewers returned; the minimax reviewer
   errored and was dropped." A reviewer whose chain failed silently is not a
   missing finding, it is a missing *vote*; never let the synthesis imply a fuller
   panel than actually weighed in.
2. **Dedup** objections that overlap into one entry, recording **how many
   independent reviewers** raised it and **whether they span model families**
   (cross-family agreement is the strongest signal; agreement across lenses within
   one model is weaker).
3. **Rank** by severity (blocker → major → minor), and within a severity put
   **verified before speculative** — a confirmed major outranks an unchecked hunch.
   Rank on merit and corroboration count, never on which model spoke.
4. Produce **one prioritized list**: each entry = objection · severity ·
   confidence · location · suggested fix · corroboration (how many independent
   reviewers / lenses, cross-family or not).
5. **Report verdicts by reviewer.** For a document, report each lens's ship /
   don't-ship verdict. A diff has no lenses: report `/code-review`'s overall
   result and each third-party reviewer's verdict instead. Never invent a
   per-lens verdict for a reviewer that did not produce one.

## Output

Present to the user:

- **The panel that actually voted**: how many reviewers were dispatched, how many
  returned, and which (if any) were dropped because a tool was missing,
  unauthenticated, or errored mid-run. State this up front so the user knows the
  weight behind the verdict — never imply a fuller panel than voted.
- The deduped, severity-ranked objection list, leading with verified findings;
  group speculative ones after so the user can skim them separately. Each entry
  carries its corroboration (how many independent reviewers / lenses, cross-family
  or not) rather than model names.
- The verdicts: per lens for a document panel, or per reviewer (`/code-review`
  plus any third-party run) for a diff.
- Source attribution is available on request, but the ranked list stands on
  merit and corroboration, not on which model raised each point.

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
- **Phantom third-party review.** Never imply Codex or Cursor weighed in when the
  tool was unavailable or unauthenticated. Report the panel as Claude-only
  instead.
- **Prestige-weighted scoring.** Don't let a finding's rank ride on which model
  raised it. Score blind to model identity; the signal is corroboration count and
  cross-family agreement, not the brand name attached to a finding.
