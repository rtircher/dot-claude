/**
 * Adversarial review as a Workflow. PROTOTYPE.
 *
 * One faithful review PASS of the `adversarial-review` skill: fan a panel of
 * independent lens reviewers (or /code-review for a diff) at an artifact, force
 * each to return schema-validated findings, then synthesize one deduped,
 * severity-ranked objection list, blind to model identity.
 *
 * Advisory only. This workflow never edits the artifact and never blocks. The
 * review/fix/re-review gate loop (3-round cap, "clean" judgement, human ping)
 * lives in the CALLER (the autonomous-feature coordinator), which invokes this
 * workflow once per round on the revised artifact. Keeping the fix loop out of
 * here preserves the skill's advisory contract. See the seam at the bottom.
 *
 * args: {
 *   artifactPath?: string,           // file to review (spec/plan); reviewers Read it
 *   artifactType: 'spec'|'plan'|'diff',
 *   diffRange?: string,              // e.g. 'main...HEAD' for artifactType 'diff'
 *   repoDir?: string,                // repo the diff lives in; reviewers use `git -C`.
 *                                    // Needed when the orchestrator runs outside that repo.
 *   focus?: string,                  // optional in-scope note, bound to every reviewer
 *   outOfScope?: string,             // optional exclusions, bound to every reviewer
 *   externalReview?: boolean,        // pre-authorized third-party reviewer (additive)
 * }
 */
export const meta = {
  name: 'adversarial-review',
  description:
    'Independent adversarial review of a spec, plan, or diff: lens-panel fan-out, schema-validated findings, blind synthesis into one ranked objection list. Advisory, never edits, never blocks.',
  phases: [
    { title: 'Review', detail: 'one reviewer per lens (or /code-review for a diff), in parallel' },
    { title: 'Verify', detail: 'skeptics adjudicate each uncorroborated blocker/major finding (confirm / reframe / refute)' },
    { title: 'Synthesize', detail: 'dedup + rank blind to model identity' },
  ],
}

// One lens = one distinct failure mode, never a redundant copy. Model defaults
// to opus (work convention); override per-lens when a lens is unusually easy/hard.
const LENS_PANELS = {
  spec: [
    { key: 'hidden-assumptions', brief: 'what is taken for granted that may not hold' },
    { key: 'gaps', brief: "what's undefined, ambiguous, or missing" },
    { key: 'contradiction-feasibility', brief: 'internal conflicts; can it actually be built as described' },
  ],
  plan: [
    { key: 'sequencing', brief: 'wrong order, unstated prerequisites, hidden coupling' },
    { key: 'risk', brief: 'what breaks, what is unrecoverable, what is untested' },
    { key: 'scope-yagni', brief: 'over-build, gold-plating, work serving no stated goal' },
  ],
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['findings', 'verdict'],
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['objection', 'severity', 'confidence', 'location', 'suggested_fix'],
        additionalProperties: false,
        properties: {
          objection: { type: 'string', description: 'What is wrong, specifically.' },
          severity: { enum: ['blocker', 'major', 'minor'] },
          confidence: {
            enum: ['verified', 'speculative'],
            description: 'verified = opened the artifact / traced the code and confirmed; speculative = inferred from a smell or partial read',
          },
          location: { type: 'string', description: 'Exact section / line / identifier the objection points at' },
          suggested_fix: { type: 'string' },
        },
      },
    },
    verdict: {
      type: 'object',
      required: ['ship', 'reason'],
      additionalProperties: false,
      properties: {
        ship: { type: 'boolean' },
        reason: { type: 'string', description: 'One sentence.' },
      },
    },
  },
}

// Adversarial verify, aimed at the diff path's blind spot. A diff is reviewed by
// a single reviewer, so a blocker rides on one read with no second opinion.
// Skeptics adjudicate each such finding (confirm / reframe / refute); a finding is
// demoted to `refuted` ONLY on unanimous refutation, so a real-but-mis-framed issue
// is never buried by a wording nitpick.
const VERIFY_VOTES = 3

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'reasoning'],
  additionalProperties: false,
  properties: {
    verdict: {
      enum: ['confirmed', 'reframe', 'refuted'],
      description:
        'confirmed = a real underlying issue exists essentially as described; reframe = a real issue exists but the objection mis-states it (supply corrected_framing); refuted = no real issue, backed by positive evidence (a guard, invariant, or unreachable path), not mere doubt',
    },
    reasoning: { type: 'string', description: 'what you traced and why you reached this verdict' },
    corrected_framing: { type: 'string', description: 'when verdict=reframe, the accurate statement of the real issue' },
    confidence: { enum: ['high', 'low'] },
  },
}

const SEVERITY_RANK = { blocker: 0, major: 1, minor: 2 }

function adversarialPreamble(art) {
  const scope = [
    art.focus && `In scope: ${art.focus}.`,
    art.outOfScope && `Out of scope (ignore): ${art.outOfScope}.`,
  ]
    .filter(Boolean)
    .join(' ')
  return `You are an adversarial reviewer. Assume the author is over-confident. Find what is WRONG, not what is fine; surface real problems, not style nits. When unsure whether something is a problem, flag it rather than let it pass. Label each finding's confidence honestly: "verified" only if you opened the artifact / traced the code and confirmed it; "speculative" if inferred from a smell or a partial read. ${scope}`.trim()
}

function lensPrompt(lens, art) {
  return `${adversarialPreamble(art)}

Review the ${art.artifactType} at ${art.artifactPath} through ONE lens only: ${lens.key} (${lens.brief}). Read the file first. Report only findings that fall under this lens. End with a single verdict (ship / don't-ship) and one sentence why. Return everything via the structured output tool.`
}

// `git -C <repoDir>` so reviewers target the artifact's repo even when the
// orchestrating session runs elsewhere (a workflow's cwd is the orchestrator's).
function gitPrefix(art) {
  return art.repoDir ? `git -C "${art.repoDir}"` : 'git'
}

function diffReviewPrompt(art) {
  const range = art.diffRange || 'the current branch diff'
  // SEAM: production wiring delegates to the /code-review skill (or its own
  // workflow form) rather than hand-rolling the pass. Kept inline for the proto.
  return `${adversarialPreamble(art)}

Perform a rigorous code review of ${range}. Run \`${gitPrefix(art)} diff ${art.diffRange || ''}\` to see the changes, and read full files with absolute paths under ${art.repoDir || 'the repo'} when you need surrounding context. Hunt for correctness bugs, security holes, broken invariants, and cross-package coupling, not style. End with an overall verdict (ship / don't-ship) and one sentence why. Return findings via the structured output tool.`
}

function thirdPartyReviewer(art) {
  // SEAM: production wiring invokes the codex plugin (/codex:adversarial-review)
  // or cursor-agent, a genuinely different model family. Consent is the caller's
  // job (the `external-review` pre-authorization). It runs on the SAME artifact
  // with the SAME framing and returns the SAME schema, so it folds into synthesis
  // as one more independent vote and lights up cross-family corroboration.
  const instruction =
    art.artifactType === 'diff'
      ? `Review the diff ${art.diffRange || '(current branch)'} (run \`${gitPrefix(art)} diff ${art.diffRange || ''}\`).`
      : `Review the ${art.artifactType} at ${art.artifactPath} (read it first).`
  return () =>
    agent(`${adversarialPreamble(art)}\n\nYou are an INDEPENDENT third-party reviewer. ${instruction} End with a verdict (ship / don't-ship) and one sentence why. Return findings via the structured output tool.`, {
      label: 'third-party',
      phase: 'Review',
      schema: REVIEW_SCHEMA,
    }).then(tag('third-party', 'external'))
}

function tag(handle, family) {
  return (r) => r && { handle, family, ...r }
}

function buildReviewers(art) {
  const thunks = []
  if (art.artifactType === 'diff') {
    thunks.push(() =>
      agent(diffReviewPrompt(art), { label: 'code-review', phase: 'Review', schema: REVIEW_SCHEMA }).then(tag('code-review', 'claude')),
    )
  } else {
    const lenses = LENS_PANELS[art.artifactType]
    if (!lenses) throw new Error(`unknown artifactType "${art.artifactType}" (expected spec | plan | diff)`)
    for (const lens of lenses) {
      thunks.push(() =>
        agent(lensPrompt(lens, art), {
          label: `lens:${lens.key}`,
          phase: 'Review',
          schema: REVIEW_SCHEMA,
          model: lens.model || 'opus',
        }).then(tag(lens.key, 'claude')),
      )
    }
  }
  if (art.externalReview) thunks.push(thirdPartyReviewer(art))
  return thunks
}

// Synthesis: plain JS between agent stages, blind to model identity.
// We anonymize to lens/source handles before ranking. Brand name never moves a
// finding's rank; the real signals are corroboration count and whether agreement
// crosses model families.

function normLocation(loc) {
  return String(loc || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

// Coarse fingerprint so near-duplicate objections collapse without over-merging
// distinct ones: same location plus the first handful of significant words.
function signature(f) {
  const words = (String(f.objection || '').toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => w.length > 3)
  return `${normLocation(f.location)} :: ${words.slice(0, 6).join(' ')}`
}

function dedupe(findings) {
  const byKey = new Map()
  for (const f of findings) {
    const key = signature(f)
    const existing = byKey.get(key)
    if (!existing) {
      byKey.set(key, { ...f, sources: [f.source], families: [f.family] })
      continue
    }
    if (SEVERITY_RANK[f.severity] < SEVERITY_RANK[existing.severity]) existing.severity = f.severity
    // a confirmed finding outranks a hunch: adopt the verified phrasing and fix
    if (f.confidence === 'verified' && existing.confidence !== 'verified') {
      existing.confidence = 'verified'
      existing.objection = f.objection
      existing.suggested_fix = f.suggested_fix
    }
    existing.sources.push(f.source)
    existing.families.push(f.family)
  }
  return [...byKey.values()].map((f) => {
    const sources = [...new Set(f.sources)]
    const families = [...new Set(f.families)]
    return {
      objection: f.objection,
      severity: f.severity,
      confidence: f.confidence,
      location: f.location,
      suggested_fix: f.suggested_fix,
      corroboration: { reviewers: sources.length, crossFamily: families.length > 1, sources },
    }
  })
}

function rank(findings) {
  return [...findings].sort((a, b) => {
    if (SEVERITY_RANK[a.severity] !== SEVERITY_RANK[b.severity]) return SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]
    const av = a.confidence === 'verified' ? 0 : 1
    const bv = b.confidence === 'verified' ? 0 : 1
    if (av !== bv) return av - bv
    return b.corroboration.reviewers - a.corroboration.reviewers
  })
}

// A finding "needs verification" when it gates ship (blocker/major) yet rests on
// a single reviewer. That is exactly the diff path, and any lone-lens doc finding.
function needsVerification(f) {
  return f.severity !== 'minor' && f.corroboration.reviewers === 1
}

function verifyPrompt(f, art) {
  const inspect =
    art.artifactType === 'diff'
      ? `Inspect the code in ${art.repoDir || 'the repo'}: run \`${gitPrefix(art)} diff ${art.diffRange || ''}\` and read full files for surrounding context.`
      : `Read the ${art.artifactType} at ${art.artifactPath}.`
  return `A reviewer raised this ${f.severity} objection:

Objection: ${f.objection}
Location: ${f.location}

Judge whether a REAL underlying issue exists, independent of how precisely the objection is worded. ${inspect} Trace the actual control flow and facts, then return one verdict:
- "confirmed": a real issue exists essentially as described.
- "reframe": a real issue exists but the objection mis-states it (wrong end-state, severity, or trigger). Put the accurate statement in corrected_framing. Do NOT discard a real issue just because its wording is imperfect.
- "refuted": there is no real issue. Use this ONLY with positive evidence the problem cannot occur (a guard, an invariant, an unreachable path), never merely because you are unsure or the wording is loose.

This is a ${f.severity}-severity finding: when in doubt, prefer confirmed or reframe over refuted. Refuting means proving the issue is not real, not pointing out that the objection is imprecise. Return your verdict via the structured output tool.`
}

// Adjudicate skeptic ballots into a verification verdict. Demote (refuted) ONLY on
// unanimous refutation; any high-confidence support, or a non-unanimous split, keeps
// the finding (confirmed/contested) so a real-but-mis-framed issue is never buried.
function adjudicate(votes) {
  const skeptics = votes.length
  const refuted = votes.filter((v) => v.verdict === 'refuted').length
  const supports = skeptics - refuted // confirmed or reframe
  const supportsHigh = votes.some((v) => v.verdict !== 'refuted' && v.confidence === 'high')
  const reframedAs = (votes.find((v) => v.verdict === 'reframe' && v.corrected_framing) || {}).corrected_framing || null
  let status
  if (skeptics === 0) status = 'contested' // unverifiable, do not clear it
  else if (refuted === skeptics) status = 'refuted' // unanimous refutation, demote
  else if (supportsHigh || supports > refuted) status = 'confirmed'
  else status = 'contested'
  return {
    status,
    skeptics,
    supports,
    refuted,
    reframedAs,
    // Full reasoning, surfaced so a verdict is auditable and a buried consensus is visible.
    votes: votes.map((v) => ({ verdict: v.verdict, confidence: v.confidence || null, reasoning: v.reasoning, corrected_framing: v.corrected_framing || null })),
  }
}

// Body

// Tolerate args arriving either as a parsed object or a JSON string, since
// callers (and the Workflow tool) vary in how they marshal it.
const art = typeof args === 'string' ? JSON.parse(args) : args || {}
if (art.artifactType !== 'diff' && !art.artifactPath) {
  throw new Error('adversarial-review requires args.artifactPath (or artifactType "diff" with diffRange)')
}

phase('Review')
const reviewers = buildReviewers(art)
const dispatched = reviewers.length
log(`Dispatching ${dispatched} reviewer(s) on ${art.artifactType} ${art.artifactPath || art.diffRange || ''}`.trim())
const returned = (await parallel(reviewers)).filter(Boolean)

// Dedup across the full panel BEFORE verifying, so a finding is never skeptic-checked
// once per reviewer that raised it (a justified barrier: dedup needs all reviewers in).
const deduped = dedupe(returned.flatMap((r) => r.findings.map((f) => ({ ...f, source: r.handle, family: r.family }))))

phase('Verify')
const toVerify = deduped.filter(needsVerification)
const ballots = new Map() // finding index -> skeptic verdicts that returned
if (toVerify.length) {
  log(`Verifying ${toVerify.length} uncorroborated blocker/major finding(s), ${VERIFY_VOTES} skeptics each`)
  const votes = (
    await parallel(
      toVerify.flatMap((f, i) =>
        Array.from({ length: VERIFY_VOTES }, (_unused, k) => () =>
          agent(verifyPrompt(f, art), { label: `verify:${i}.${k}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: 'opus' }).then((v) => v && { i, v }),
        ),
      ),
    )
  ).filter(Boolean)
  for (const { i, v } of votes) {
    const list = ballots.get(i) || []
    list.push(v)
    ballots.set(i, list)
  }
}

// toVerify holds the same object refs as deduped, so map verdicts back by identity.
const verificationByFinding = new Map()
toVerify.forEach((f, i) => verificationByFinding.set(f, adjudicate(ballots.get(i) || [])))
const annotated = deduped.map((f) => ({ ...f, verification: verificationByFinding.get(f) || null }))

phase('Synthesize')
// Demote only the unanimously-refuted; confirmed and contested findings stay in the
// ranked list, so a contested blocker still gates ship.
const findings = rank(annotated.filter((f) => !f.verification || f.verification.status !== 'refuted'))
const refuted = annotated.filter((f) => f.verification && f.verification.status === 'refuted')

return {
  artifact: { path: art.artifactPath || null, type: art.artifactType, range: art.diffRange || null },
  // What actually voted, so the caller never implies a fuller panel than weighed in.
  panel: { dispatched, returned: returned.length, dropped: dispatched - returned.length },
  verdicts: returned.map((r) => ({ reviewer: r.handle, ship: r.verdict.ship, reason: r.verdict.reason })),
  findings,
  // Confirmed AND contested blocker/major findings gate; only unanimously-refuted ones drop out.
  hasBlockerOrMajor: findings.some((f) => f.severity !== 'minor'),
  // Unanimously refuted by skeptics; kept with full reasoning for transparency, not silently dropped.
  refuted,
}
