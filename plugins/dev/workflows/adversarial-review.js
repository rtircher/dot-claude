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
 *   externalReview?: boolean,        // defaults TRUE: real cross-family couriers run
 *                                    // alongside the Claude panel; pass false to opt out
 *   skillScriptsDir?: string,        // absolute path to the adversarial-review skill's
 *                                    // scripts/ dir; plugin commands pass
 *                                    // `${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts`.
 *                                    // Required for external review (courier command paths).
 *   expectedArtifactSha256?: string, // sha256 hex of the exact artifact bytes
 *                                    // (`git diff <range>` output for a diff, file bytes
 *                                    // for spec/plan), computed by the CALLER and never
 *                                    // shown to couriers; each external vote must
 *                                    // self-report an EQUAL digest to count.
 *                                    // Required for external review.
 *                                    // (There is no separate diff-base arg: base derives
 *                                    // from the range, and a second artifact-selection
 *                                    // knob could skew from the hashed range.)
 *                                    // diffRange is additionally required for diff
 *                                    // artifacts, and must be `<ref>...HEAD` for the
 *                                    // Codex reviewer to participate (the companion
 *                                    // reviews only that form).
 *   requireExternal?: boolean,       // shortfall suppressor. external.shortfall fires by
 *                                    // DEFAULT whenever external review was requested and
 *                                    // zero external votes counted (config drop, courier
 *                                    // failure, digest mismatch — never a silent
 *                                    // degradation to Claude-only). Pass false to
 *                                    // suppress it for a round where external absence is
 *                                    // the documented degradation (gated-review rounds
 *                                    // 2+, stale digest). `true` is the old force form
 *                                    // and is now redundant with the default.
 *                                    // Advisory only: the workflow never blocks on it.
 *   tiers?: {                        // optional per-reviewer re-tiering, decided by the
 *     [key: string]: {               // caller per dispatch ("pick the model per task").
 *       model?: string,              // unversioned alias ('opus', 'sonnet', 'haiku')
 *       effort?: string,             // 'low'|'medium'|'high'|'xhigh'|'max'
 *     },                             // keys: a lens key, 'code-review' (diff reviewer),
 *   },                               // 'verify' (skeptics). DEFAULT_TIERS routes the
 *                                    // mechanical lenses (scope-yagni, gaps) to sonnet;
 *                                    // every other slot inherits the session model at
 *                                    // session effort. Explicit tiers override per key.
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
//
// Fan-out is BOUNDED. The naive shape (VERIFY_VOTES agents per finding) is
// unbounded in the finding count and has blown up in practice: a spec review
// with 21 uncorroborated blocker/major findings dispatched 63 verify agents
// (run wf_ce42497d-830). Instead, skeptics adjudicate BATCHES: findings are
// ranked, chunked into groups of VERIFY_BATCH, and each chunk gets VERIFY_VOTES
// skeptics, capped at MAX_VERIFY_AGENTS dispatches total. Findings beyond the
// cap are kept, annotated as contested-unverified (they still gate ship), and
// the drop is logged — never a silent truncation.
const VERIFY_VOTES = 3
const VERIFY_BATCH = 5 // findings adjudicated per skeptic agent
const MAX_VERIFY_AGENTS = 12 // hard ceiling on verify dispatches per run

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

// One skeptic adjudicates a whole batch: one verdict per numbered finding.
const BATCH_VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  additionalProperties: false,
  properties: {
    verdicts: {
      type: 'array',
      items: {
        ...VERDICT_SCHEMA,
        required: ['index', ...VERDICT_SCHEMA.required],
        properties: {
          index: { type: 'integer', description: 'the finding number this verdict answers, exactly as listed in the prompt' },
          ...VERDICT_SCHEMA.properties,
        },
      },
    },
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

// Default routing: the mechanical lenses run on sonnet; the reasoning-heavy
// lenses (hidden-assumptions, contradiction-feasibility, sequencing, risk),
// the diff reviewer, and the verify skeptics inherit the session model (no
// entry). Callers who pass nothing get this; args.tiers overrides per key.
const DEFAULT_TIERS = {
  'scope-yagni': { model: 'sonnet' },
  gaps: { model: 'sonnet' },
}

// Effective tiering for one reviewer slot: DEFAULT_TIERS under any
// caller-supplied override for the same key.
function tierOpts(art, key) {
  const t = { ...(DEFAULT_TIERS[key] || {}), ...((art.tiers || {})[key] || {}) }
  return { ...(t.model ? { model: t.model } : {}), ...(t.effort ? { effort: t.effort } : {}) }
}

function diffReviewPrompt(art) {
  const range = art.diffRange || 'the current branch diff'
  // SEAM: production wiring delegates to the /code-review skill (or its own
  // workflow form) rather than hand-rolling the pass.
  return `${adversarialPreamble(art)}

Perform a rigorous code review of ${range}. Run \`${gitPrefix(art)} diff ${art.diffRange || ''}\` to see the changes, and read full files with absolute paths under ${art.repoDir || 'the repo'} when you need surrounding context. Hunt for correctness bugs, security holes, broken invariants, and cross-package coupling, not style. End with an overall verdict (ship / don't-ship) and one sentence why. Return findings via the structured output tool.`
}

// Stamp AFTER the spread: a courier's returned payload is schema-legal with any
// top-level keys (EXTERNAL_VOTE_SCHEMA requires nothing), so stamping first
// would let it override handle/family and masquerade past the partition. Safe
// for Claude votes too: REVIEW_SCHEMA is additionalProperties:false, so they
// never carry stray handle/family keys for this spread to clobber.
function tag(handle, family) {
  return (r) => r && { ...r, handle, family }
}

// External courier reviewers. A courier's ONLY job is to run the real external
// tool and hand back its stdout; the honesty guarantee is the digest gate
// (externalVoteProblem), not the courier's obedience: couriers never see
// art.expectedArtifactSha256, so a courier that skips the tool cannot fabricate
// a passing vote. Couriers run as the default workflow subagent (full tools):
// dev:reviewer/dev:researcher are ruled out because their RULES forbid exactly what these do
// (POSTing the artifact to an endpoint; spawning the Codex app-server).
// The pipelines carry no env prefix: external-review.mjs reads its own
// environment (which courier shells inherit) and fails fast with the exact
// reason when EXTERNAL_REVIEW_MODEL is unset; codex-review.mjs defaults
// --companion itself and exits 2 when no companion is installed. Those stderr
// reasons come back as __error and surface in external.dropped.

const EXTERNAL_VOTE_SCHEMA = {
  type: 'object', additionalProperties: true,
  properties: {
    reviewer: { type: 'object', additionalProperties: true },
    artifactSha256: { type: 'string' },
    __error: { type: 'string' },
    findings: REVIEW_SCHEMA.properties.findings,
    verdict: REVIEW_SCHEMA.properties.verdict,
  },
}

function scriptCourier(art) {
  const target = art.artifactType === 'diff'
    ? `${art.diffRange} @ ${art.pinnedSha || 'HEAD'}`
    : `${art.artifactPath} @ ${art.artifactType}`
  const feed = art.artifactType === 'diff'
    ? `${gitPrefix(art)} diff ${art.diffRange}`
    : `cat "${art.artifactPath}"`
  return () => agent(
    `You are a COURIER, not a reviewer. Run EXACTLY this pipeline and return the script's stdout parsed as JSON via the structured output tool. Do not review anything yourself; do not alter the findings. If the command errors or prints no JSON, return {"__error":"<stderr>"}.\n\n${feed} | node "${art.skillScriptsDir}/external-review.mjs" --type ${art.artifactType} --target "${target}"`,
    { label: 'external:script', phase: 'Review', schema: EXTERNAL_VOTE_SCHEMA },
  ).then(tag('external:script', 'script'))
}

function codexCourier(art) {
  // codex-review.mjs derives base internally from the range's left side and
  // refuses any range that is not <ref>...HEAD (the only form the companion
  // reviews), so the courier passes the caller-pinned range and nothing else.
  return () => agent(
    `You are a COURIER, not a reviewer. Run EXACTLY this command and return its stdout parsed as JSON via the structured output tool. Do not review anything yourself. If it errors or prints no JSON, return {"__error":"<stderr>"}.\n\nnode "${art.skillScriptsDir}/codex-review.mjs" --cwd "${art.repoDir || '.'}" --range "${art.diffRange}" --target "${art.diffRange} @ ${art.pinnedSha || 'HEAD'}"`,
    { label: 'external:codex', phase: 'Review', schema: EXTERNAL_VOTE_SCHEMA },
  ).then(tag('external:codex', 'openai'))
}

// Static dispatch (no discovery pre-pass): the script courier always runs (any
// artifact type); the codex courier runs for diffs only, reported "not
// applicable" otherwise. Availability is enforced by the tools themselves at
// run time; a tool failure returns as __error and is dropped plus reported.
function externalReviewerThunks(art) {
  const dropped = []
  const thunks = [scriptCourier(art)]
  if (art.artifactType === 'diff') thunks.push(codexCourier(art))
  else dropped.push({ kind: 'codex', family: 'openai', dropReason: `not applicable to ${art.artifactType}` })
  return { thunks, dropped }
}

// Returns null for a countable external vote, else the exact drop reason.
// Checks, in order: courier-declared failure, tool fingerprint, digest
// EQUALITY against the caller-pinned value (never mere presence; the expected
// value lives only in args, couriers never see it, so a courier that skipped
// the tool cannot fabricate a passing vote), then vote SHAPE (verdict +
// schema-valid findings), because EXTERNAL_VOTE_SCHEMA deliberately requires
// nothing and the fold reads r.verdict.ship / r.findings unconditionally.
function externalVoteProblem(art, r) {
  if (!r) return 'courier returned nothing'
  if (r.__error) return r.__error
  const kind = r.reviewer && r.reviewer.kind
  if (kind !== 'external-review-script' && kind !== 'codex-review-script') {
    return `no tool fingerprint (reviewer.kind = ${JSON.stringify(kind)})`
  }
  if (r.artifactSha256 !== art.expectedArtifactSha256) {
    return 'digest mismatch: vote does not cover the caller-pinned bytes'
  }
  if (typeof r.verdict?.ship !== 'boolean' || typeof r.verdict?.reason !== 'string') {
    return `tool ran but vote malformed: verdict = ${JSON.stringify(r.verdict)}`
  }
  if (!Array.isArray(r.findings)) return 'tool ran but vote malformed: findings is not an array'
  const requiredKeys = REVIEW_SCHEMA.properties.findings.items.required
  for (const [i, f] of r.findings.entries()) {
    for (const k of requiredKeys) {
      if (!f || !(k in f)) return `tool ran but vote malformed: findings[${i}] missing "${k}"`
    }
  }
  return null
}

function buildReviewers(art) {
  const thunks = []
  if (art.artifactType === 'diff') {
    thunks.push(() =>
      agent(diffReviewPrompt(art), { label: 'code-review', phase: 'Review', schema: REVIEW_SCHEMA, agentType: 'dev:reviewer', ...tierOpts(art, 'code-review') }).then(tag('code-review', 'claude')),
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
          agentType: 'dev:reviewer',
        }).then(tag(lens.key, 'claude')),
      )
    }
  }
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

function verifyPrompt(batch, art) {
  const inspect =
    art.artifactType === 'diff'
      ? `Inspect the code in ${art.repoDir || 'the repo'}: run \`${gitPrefix(art)} diff ${art.diffRange || ''}\` and read full files for surrounding context.`
      : `Read the ${art.artifactType} at ${art.artifactPath}.`
  const items = batch
    .map(({ f, index }) => `Finding ${index} [${f.severity}]:\nObjection: ${f.objection}\nLocation: ${f.location}`)
    .join('\n\n')
  return `Reviewers raised the following blocker/major objections. Adjudicate EACH one independently — do not let a verdict on one color another.

${items}

For each finding, judge whether a REAL underlying issue exists, independent of how precisely the objection is worded. ${inspect} Trace the actual control flow and facts, then return one verdict per finding (carrying its finding number as "index"):
- "confirmed": a real issue exists essentially as described.
- "reframe": a real issue exists but the objection mis-states it (wrong end-state, severity, or trigger). Put the accurate statement in corrected_framing. Do NOT discard a real issue just because its wording is imperfect.
- "refuted": there is no real issue. Use this ONLY with positive evidence the problem cannot occur (a guard, an invariant, an unreachable path), never merely because you are unsure or the wording is loose.

These are blocker/major-severity findings: when in doubt, prefer confirmed or reframe over refuted. Refuting means proving the issue is not real, not pointing out that the objection is imprecise. Return one verdict for EVERY finding listed, via the structured output tool.`
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

// External review is ON by default; opt out with externalReview:false (or "no-external").
const externalRequested = art.externalReview !== false
let runExternal = externalRequested
const externalDroppedPre = [] // config failures, recorded before any courier runs
if (runExternal && !art.skillScriptsDir) {
  runExternal = false
  externalDroppedPre.push({ kind: 'config', dropReason: 'skillScriptsDir not provided by caller' })
}
if (runExternal && !art.expectedArtifactSha256) {
  runExternal = false
  externalDroppedPre.push({ kind: 'config', dropReason: 'expectedArtifactSha256 not provided by caller' })
}
if (runExternal && art.artifactType === 'diff' && !art.diffRange) {
  runExternal = false
  externalDroppedPre.push({ kind: 'config', dropReason: 'diffRange not provided for a diff artifact (couriers never guess a range)' })
}

phase('Review')
const ext = runExternal ? externalReviewerThunks(art) : { thunks: [], dropped: [] }
const claudeThunks = buildReviewers(art)
const reviewers = [...claudeThunks, ...ext.thunks]
const dispatched = reviewers.length
log(`Dispatching ${dispatched} reviewer(s) on ${art.artifactType} ${art.artifactPath || art.diffRange || ''}`.trim())
// ONE parallel; parallel preserves order, so slots [0, claudeThunks.length)
// are Claude votes and the rest are external couriers. The split is by
// DISPATCH IDENTITY (index offset), never by any field on the returned
// object: the payload is courier-controlled. Do NOT filter nulls before
// slicing; that would shift the offsets. A null in an EXTERNAL slot is
// deliberately KEPT: externalVoteProblem turns it into a visible
// external.dropped entry instead of a silent absence.
const returnedAll = await parallel(reviewers)
const claudeVotes = returnedAll.slice(0, claudeThunks.length).filter(Boolean)
const externalReturned = returnedAll.slice(claudeThunks.length)

// Partition external returns by the digest-EQUALITY plus vote-shape gate:
// verdicts, panel counts, and the dedupe fold are built ONLY from Claude votes
// plus real external votes; everything else is dropped WITH its reason.
const realExternalVotes = []
const externalDropped = []
for (const [i, r] of externalReturned.entries()) {
  const problem = externalVoteProblem(art, r)
  if (problem) externalDropped.push({ handle: r?.handle || `external[${i}]`, family: r?.family || null, dropReason: problem })
  else realExternalVotes.push(r)
}
const panelVotes = [...claudeVotes, ...realExternalVotes]

// Dedup across the full panel BEFORE verifying, so a finding is never skeptic-checked
// once per reviewer that raised it (a justified barrier: dedup needs all reviewers in).
const deduped = dedupe(panelVotes.flatMap((r) => r.findings.map((f) => ({ ...f, source: r.handle, family: r.family }))))

phase('Verify')
// Rank first so the cap (if it bites) drops the least severe findings; capped-out
// findings are kept and adjudicated as contested (zero skeptics), so they still
// gate ship — the cap bounds spend, never silently clears a finding.
const toVerify = rank(deduped.filter(needsVerification))
const maxVerifiable = Math.floor(MAX_VERIFY_AGENTS / VERIFY_VOTES) * VERIFY_BATCH
const verified = toVerify.slice(0, maxVerifiable)
const capSkipped = toVerify.slice(maxVerifiable)
const ballots = new Map() // finding index (into `verified`) -> skeptic verdicts that returned
if (verified.length) {
  const indexed = verified.map((f, index) => ({ f, index }))
  const batches = []
  for (let i = 0; i < indexed.length; i += VERIFY_BATCH) batches.push(indexed.slice(i, i + VERIFY_BATCH))
  log(
    `Verifying ${verified.length} uncorroborated blocker/major finding(s): ${batches.length} batch(es) x ${VERIFY_VOTES} skeptics = ${batches.length * VERIFY_VOTES} agent(s)` +
      (capSkipped.length ? `; ${capSkipped.length} finding(s) beyond the ${MAX_VERIFY_AGENTS}-agent cap stay unverified (kept as contested)` : ''),
  )
  const votes = (
    await parallel(
      batches.flatMap((batch, b) =>
        Array.from({ length: VERIFY_VOTES }, (_unused, k) => () =>
          // dev:researcher, NOT dev:reviewer: verify agents adjudicate an objection, and the
          // reviewer persona's flag-when-uncertain bias would stack with verifyPrompt's own
          // prefer-confirmed bias and neuter the pass's ability to refute false positives.
          agent(verifyPrompt(batch, art), { label: `verify:${b}.${k}`, phase: 'Verify', schema: BATCH_VERDICT_SCHEMA, agentType: 'dev:researcher', ...tierOpts(art, 'verify') }).then(
            (r) => r && { batch, verdicts: r.verdicts },
          ),
        ),
      ),
    )
  ).filter(Boolean)
  for (const { batch, verdicts } of votes) {
    // Fold by the skeptic-echoed index, accepting only indices this batch actually
    // carried (a stray index must not vote on someone else's finding).
    const valid = new Set(batch.map((b) => b.index))
    for (const v of verdicts || []) {
      if (!valid.has(v.index)) continue
      const list = ballots.get(v.index) || []
      list.push(v)
      ballots.set(v.index, list)
    }
  }
}

// `verified`/`capSkipped` hold the same object refs as deduped, so map verdicts
// back by identity. adjudicate([]) = contested: an unverified blocker/major
// (capped out, or all its skeptics failed to return) never silently clears.
const verificationByFinding = new Map()
verified.forEach((f, i) => verificationByFinding.set(f, adjudicate(ballots.get(i) || [])))
capSkipped.forEach((f) => verificationByFinding.set(f, adjudicate([])))
const annotated = deduped.map((f) => ({ ...f, verification: verificationByFinding.get(f) || null }))

phase('Synthesize')
// Demote only the unanimously-refuted; confirmed and contested findings stay in the
// ranked list, so a contested blocker still gates ship.
const findings = rank(annotated.filter((f) => !f.verification || f.verification.status !== 'refuted'))
const refuted = annotated.filter((f) => f.verification && f.verification.status === 'refuted')

return {
  artifact: { path: art.artifactPath || null, type: art.artifactType, range: art.diffRange || null },
  // Counts cover votes that actually folded in: Claude panel + digest-verified external.
  panel: { dispatched, returned: panelVotes.length, dropped: dispatched - panelVotes.length },
  verdicts: panelVotes.map((r) => ({ reviewer: r.handle, ship: r.verdict.ship, reason: r.verdict.reason })),
  findings,
  // Confirmed AND contested blocker/major findings gate; only unanimously-refuted ones drop out.
  hasBlockerOrMajor: findings.some((f) => f.severity !== 'minor'),
  // Unanimously refuted by skeptics; kept with full reasoning for transparency, not silently dropped.
  refuted,
  external: {
    requested: externalRequested,
    ran: realExternalVotes.map((r) => ({ family: r.family, kind: r.reviewer.kind })),
    // config failures + not-applicable + failed couriers, each with a reason
    dropped: [...externalDroppedPre, ...ext.dropped, ...externalDropped],
    // Loud-failure hook (advisory: the workflow NEVER blocks on it). Fires by
    // DEFAULT whenever external review was requested (the default) and zero
    // external votes counted — config drops included — so a run never silently
    // degrades to Claude-only. requireExternal:false suppresses it for rounds
    // where external absence is the documented degradation (gated-review
    // forwards false on rounds 2+, where the pinned digest is stale by design).
    shortfall: art.requireExternal !== false && externalRequested && realExternalVotes.length === 0,
  },
}
