/**
 * Adversarial review as a Workflow.
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
 *   externalReview?: boolean,        // pre-authorized third-party review (additive):
 *                                    // drives every wired EXTERNAL_REVIEWERS entry
 *                                    // (currently scripts/external-review.mjs, which
 *                                    // needs EXTERNAL_REVIEW_MODEL / API key in the
 *                                    // environment). Skipped and reported via the
 *                                    // returned `externalReview` field when unwired
 *                                    // or unconfigured, never faked with a Claude vote.
 *   tiers?: {                        // optional per-reviewer re-tiering, decided by the
 *     [key: string]: {               // caller per dispatch ("pick the model per task").
 *       model?: string,              // unversioned alias ('opus', 'sonnet', 'haiku')
 *       effort?: string,             // 'low'|'medium'|'high'|'xhigh'|'max'
 *     },                             // keys: a lens key, 'code-review' (diff reviewer),
 *   },                               // 'verify' (skeptics). Omit to inherit the session
 *                                    // model at session effort.
 * }
 */
export const meta = {
  name: 'dev-adversarial-review',
  description:
    'Independent adversarial review of a spec, plan, or diff: lens-panel fan-out, schema-validated findings, blind synthesis into one ranked objection list. Advisory, never edits, never blocks.',
  phases: [
    { title: 'Review', detail: 'one reviewer per lens (or /code-review for a diff), in parallel' },
    { title: 'Verify', detail: 'skeptics adjudicate each uncorroborated blocker/major finding (confirm / reframe / refute)' },
    { title: 'Synthesize', detail: 'dedup + rank blind to model identity' },
  ],
}

// One lens = one distinct failure mode, never a redundant copy. Reviewers inherit
// the session model (never a downgrade when the session runs a stronger tier);
// set `model` on a lens only to deliberately re-tier an unusually easy/hard one.
const LENS_PANELS = {
  spec: [
    { key: 'hidden-assumptions', brief: 'what is taken for granted that may not hold' },
    { key: 'gaps', brief: "what's undefined, ambiguous, or missing" },
    { key: 'contradiction-feasibility', brief: 'internal conflicts; can it actually be built as described' },
    { key: 'scope-yagni', brief: "speculative scope, over-generalization, extensibility/config/abstraction the requirements don't justify" },
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

// Caller-supplied re-tiering for one reviewer slot. Empty (inherit the session
// model at session effort) unless args.tiers names this key: re-tiering is
// always a deliberate per-dispatch choice, never a baked-in default.
function tierOpts(art, key) {
  const t = (art.tiers || {})[key] || {}
  return { ...(t.model ? { model: t.model } : {}), ...(t.effort ? { effort: t.effort } : {}) }
}

function diffReviewPrompt(art) {
  const range = art.diffRange || 'the current branch diff'
  // SEAM: production wiring delegates to the /code-review skill (or its own
  // workflow form) rather than hand-rolling the pass.
  return `${adversarialPreamble(art)}

Perform a rigorous code review of ${range}. Run \`${gitPrefix(art)} diff ${art.diffRange || ''}\` to see the changes, and read full files with absolute paths under ${art.repoDir || 'the repo'} when you need surrounding context. Hunt for correctness bugs, security holes, broken invariants, and cross-package coupling, not style. End with an overall verdict (ship / don't-ship) and one sentence why. Return findings via the structured output tool.`
}

// SEAM: external (non-Claude) review. Each registry entry drives one genuinely
// different model family and returns REVIEW_SCHEMA-shaped findings, so it folds
// into synthesis as one more independent vote and LEGITIMATELY lights up
// cross-family corroboration. The shipped entry drives the skill's
// scripts/external-review.mjs (any OpenAI-compatible endpoint; Claude-family
// models are refused there). Wire codex (/codex:adversarial-review), cursor-agent,
// or OpenCode-on-a-non-Claude-model by adding entries. Consent to send the
// artifact out is the caller's job (the `externalReview` pre-authorization).
//
// The workflow sandbox cannot run the script itself, so a driver AGENT runs it
// via Bash and transcribes its output. The driver never reviews the artifact
// itself: when the script, model, or credentials are absent, external review is
// SKIPPED and REPORTED (see the returned externalReview field), never faked by a
// Claude agent tagged 'external' (which would falsely light up crossFamily in
// dedupe()). An empty registry is a valid state and skips external review too.

// `ran` is the honest availability signal: a real external vote can legitimately
// return zero findings on a clean artifact, so emptiness alone cannot stand in
// for "did an external model actually weigh in".
const EXTERNAL_DRIVER_SCHEMA = {
  type: 'object',
  required: ['ran', 'findings', 'verdict'],
  additionalProperties: false,
  properties: {
    ran: { type: 'boolean', description: 'true ONLY if the external tool executed and returned valid JSON; false if its script, model, or credentials were absent, or it errored' },
    family: { type: 'string', description: 'the family the tool reported (e.g. "external"); "" when ran=false' },
    model: { type: 'string', description: 'the external model used; "" when ran=false' },
    unavailable_reason: { type: 'string', description: 'when ran=false, the concrete reason (missing script / EXTERNAL_REVIEW_MODEL / API key / API error); "" when ran=true' },
    findings: REVIEW_SCHEMA.properties.findings,
    verdict: REVIEW_SCHEMA.properties.verdict,
  },
}

function externalScriptDriverPrompt(art) {
  const feed =
    art.artifactType === 'diff'
      ? `${gitPrefix(art)} diff ${art.diffRange || ''}`
      : `cat ${JSON.stringify(art.artifactPath)}`
  const target = art.artifactType === 'diff' ? art.diffRange || 'current branch diff' : art.artifactPath
  const scopeFlags = [
    art.focus && `--focus ${JSON.stringify(art.focus)}`,
    art.outOfScope && `--out-of-scope ${JSON.stringify(art.outOfScope)}`,
  ]
    .filter(Boolean)
    .join(' ')
  const repoHint = art.repoDir
    ? JSON.stringify(`${art.repoDir}/plugins/dev/skills/adversarial-review/scripts/external-review.mjs`)
    : '"plugins/dev/skills/adversarial-review/scripts/external-review.mjs"'
  return `You are a NON-REVIEWING driver for a third-party review. You do NOT review the ${art.artifactType} yourself and you NEVER invent, add, drop, or reword findings. Your only job is to run the shipped external-review script and transcribe its JSON output.

Steps:
1. Locate "external-review.mjs": check a repo checkout (${repoHint}) and the installed plugin cache (\`find "$HOME/.claude/plugins" -name external-review.mjs 2>/dev/null | head -1\`). If you cannot find it, return ran=false with that reason.
2. Confirm the environment is configured: run \`printenv EXTERNAL_REVIEW_MODEL\`. If it is unset, return ran=false with that reason. Do NOT set it or any API key yourself; the caller configures those.
3. Get the pinned SHA: \`${gitPrefix(art)} rev-parse --short HEAD\` (if that fails because the artifact is not in a git repo, use the target without the SHA suffix).
4. Run, piping the artifact on stdin (never as an argument):
   \`${feed} | node <script-path> --type ${art.artifactType} --target "${target} @ <sha>"${scopeFlags ? ' ' + scopeFlags : ''}\`
5. On non-zero exit or non-JSON stdout, return ran=false with the script's stderr as unavailable_reason. Do NOT retry with different flags and do NOT review the artifact yourself.
6. On success, parse the script's JSON stdout and transcribe it EXACTLY: ran=true, family=its reviewer.family, model=its reviewer.model, findings=its findings verbatim, verdict=its verdict.

When ran=false, set findings=[] and verdict={ship:true, reason:"external review unavailable: <reason>"} so the Claude panel alone decides. Return via the structured output tool.`
}

function externalScriptReviewer(art) {
  return () =>
    agent(externalScriptDriverPrompt(art), {
      label: 'external:script',
      phase: 'Review',
      schema: EXTERNAL_DRIVER_SCHEMA,
      agentType: 'dev:researcher',
    }).then(foldExternal('external:script'))
}

// Normalize a driver result into the reviewer shape the panel consumes. A
// ran=false result carries NO findings, so it can never tag a finding 'external'
// or move crossFamily; its absence is surfaced via the externalReview field.
function foldExternal(handle) {
  return (r) => {
    if (!r) return null
    if (!r.ran) {
      return { handle, external: true, ran: false, family: 'external', model: null, unavailable: r.unavailable_reason || 'external reviewer unavailable', findings: [], verdict: r.verdict || { ship: true, reason: `external review unavailable: ${r.unavailable_reason || 'unknown'}` } }
    }
    return { handle, external: true, ran: true, family: r.family || 'external', model: r.model || null, findings: r.findings || [], verdict: r.verdict }
  }
}

// Wired external (non-Claude) reviewers. Empty is valid: external review then
// skips and is reported, never faked.
const EXTERNAL_REVIEWERS = [{ key: 'external-review-script', build: externalScriptReviewer }]

function tag(handle, family) {
  return (r) => r && { handle, family, ...r }
}

function buildReviewers(art) {
  const thunks = []
  if (art.artifactType === 'diff') {
    thunks.push(() =>
      agent(diffReviewPrompt(art), { label: 'code-review', phase: 'Review', schema: REVIEW_SCHEMA, agentType: 'dev:researcher', ...tierOpts(art, 'code-review') }).then(tag('code-review', 'claude')),
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
          ...(lens.model ? { model: lens.model } : {}),
          ...tierOpts(art, lens.key),
          agentType: 'dev:researcher',
        }).then(tag(lens.key, 'claude')),
      )
    }
  }
  if (art.externalReview) for (const ext of EXTERNAL_REVIEWERS) thunks.push(ext.build(art))
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
const externalDispatched = art.externalReview ? EXTERNAL_REVIEWERS.length : 0
if (art.externalReview && externalDispatched === 0) {
  log('External review requested but no external reviewer is wired: proceeding Claude-only (no cross-family corroboration this round)')
}
log(`Dispatching ${dispatched} reviewer(s) on ${art.artifactType} ${art.artifactPath || art.diffRange || ''}`.trim())
const returned = (await parallel(reviewers)).filter(Boolean)

// Whether a requested external review actually produced a non-Claude vote, so the
// caller can tell "no cross-family signal" apart from "cross-family never ran".
const externalResults = returned.filter((r) => r.external)
const externalReview = {
  requested: !!art.externalReview,
  dispatched: externalDispatched,
  ran: externalResults.filter((r) => r.ran).map((r) => ({ handle: r.handle, family: r.family, model: r.model })),
  unavailable: externalResults.filter((r) => !r.ran).map((r) => ({ handle: r.handle, reason: r.unavailable })),
}
for (const u of externalReview.unavailable) log(`External reviewer "${u.handle}" unavailable: ${u.reason}`)

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
          agent(verifyPrompt(f, art), { label: `verify:${i}.${k}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'dev:researcher', ...tierOpts(art, 'verify') }).then((v) => v && { i, v }),
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
  // Whether a requested external review produced a real non-Claude vote or was
  // skipped/unavailable, so a skipped pass is reported, never silently faked.
  externalReview,
  // An unavailable external reviewer has no opinion, so it is not listed as a verdict.
  verdicts: returned.filter((r) => !(r.external && !r.ran)).map((r) => ({ reviewer: r.handle, ship: r.verdict.ship, reason: r.verdict.reason })),
  findings,
  // Confirmed AND contested blocker/major findings gate; only unanimously-refuted ones drop out.
  hasBlockerOrMajor: findings.some((f) => f.severity !== 'minor'),
  // Unanimously refuted by skeptics; kept with full reasoning for transparency, not silently dropped.
  refuted,
}
