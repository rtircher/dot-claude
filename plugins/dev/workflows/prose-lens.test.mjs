import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Runs the whole adversarial-review script with stubbed globals, so these tests
// cover what the workflow returns and dispatches, not what its source says.
const src = readFileSync(fileURLToPath(new URL('./adversarial-review.js', import.meta.url)), 'utf8').replace('export const meta', 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'phase', 'log', src)

const OK_VOTE = { findings: [], verdict: { ship: true, reason: 'ok' } }
const SHA = 'a'.repeat(64)
const verified = { objection: 'comment narrates the code', confidence: 'verified', location: 'foo.py:3 "# loop over items"', suggested_fix: 'say why the loop exists' }
const speculative = { objection: 'wordy commit body', confidence: 'speculative', location: 'commit 2 body', suggested_fix: 'cut the first paragraph' }

const diffArgs = { artifactType: 'diff', diffRange: 'main...HEAD', repoDir: '/tmp/x', externalReview: false }
const DIFF_LENSES = ['correctness', 'simplicity-yagni', 'testing', 'duplication']

// `answers` maps a dispatch label to what that agent returns; every other
// `lens:*` returns a clean ship vote. parallel() mirrors the real one: a
// rejected thunk becomes null.
async function review(args, answers = {}) {
  const dispatched = []
  const agent = async (prompt, opts) => {
    dispatched.push({ prompt, opts })
    if (opts.label in answers) return answers[opts.label]
    if (opts.label.startsWith('lens:')) return OK_VOTE
    throw new Error(`unexpected dispatch ${opts.label}`)
  }
  const parallel = (thunks) => Promise.all(thunks.map((t) => t().catch(() => null)))
  const result = await run(args, agent, parallel, () => {}, () => {})
  return { result, dispatched, labels: dispatched.map((d) => d.opts.label).sort() }
}

const diffCases = [
  ['one finding', { findings: [verified] }, { ran: true, findings: [verified] }],
  ['verified ordered before speculative', { findings: [speculative, verified] }, { ran: true, findings: [verified, speculative] }],
  ['returned with no findings', { findings: [] }, { ran: true, findings: [] }],
  ['returned nothing', null, { ran: false, reason: 'prose lens returned nothing', findings: [] }],
]
for (const [name, answer, expected] of diffCases) {
  test(`diff, prose ${name}: the verdict and panel are untouched`, async () => {
    const { result, labels } = await review(diffArgs, { 'lens:prose': answer })
    assert.deepEqual(labels, ['lens:prose', ...DIFF_LENSES.map((k) => `lens:${k}`)].sort())
    assert.deepEqual(result.prose, expected)
    assert.equal(result.hasBlockerOrMajor, false)
    assert.deepEqual(result.findings, [])
    assert.deepEqual(result.verdicts.map((v) => v.reviewer), DIFF_LENSES)
    assert.deepEqual(result.panel, { dispatched: 4, returned: 4, dropped: 0 })
    assert.deepEqual(result.external.dropped, [])
  })
}

for (const [type, lenses] of [
  ['spec', ['hidden-assumptions', 'gaps', 'contradiction-feasibility', 'scope-yagni']],
  ['plan', ['sequencing', 'risk', 'scope-yagni']],
]) {
  test(`${type}: no prose agent runs and prose is null`, async () => {
    const { result, labels } = await review(
      { artifactType: type, artifactPath: `/tmp/${type}.md`, externalReview: false },
      { 'lens:prose': { findings: [verified] } },
    )
    assert.deepEqual(labels, lenses.map((k) => `lens:${k}`).sort())
    assert.equal(result.prose, null)
    assert.deepEqual(result.panel, { dispatched: lenses.length, returned: lenses.length, dropped: 0 })
  })
}

// Prose sits after the couriers in the one parallel(); an offset slip would
// hand the prose answer to the courier fold (dropped for no fingerprint) or the
// courier vote to the prose field.
test('diff with a courier: prose is read from the tail slot, not folded as external', async () => {
  const vote = { name: 'qwen', reviewer: { kind: 'external-review-script', name: 'qwen', family: 'qwen', model: 'qwen-x' }, artifactSha256: SHA, verdict: { ship: true, reason: 'ok' }, findings: [] }
  const { result } = await review(
    { ...diffArgs, externalReview: true, externalReviewers: ['qwen'], skillScriptsDir: '/tmp/scripts', expectedArtifactSha256: SHA },
    { 'external:qwen': { configured: true, artifactSha256: SHA, votes: [vote] }, 'lens:prose': { findings: [verified] } },
  )
  assert.deepEqual(result.panel, { dispatched: 5, returned: 5, dropped: 0 })
  assert.deepEqual(result.external.ran.map((r) => r.handle), ['external:qwen'])
  assert.deepEqual(result.external.dropped, [])
  assert.equal(result.external.shortfall, false)
  assert.deepEqual(result.prose, { ran: true, findings: [verified] })
})

// A failed panel lens leaves a null in the middle of the one parallel(); the
// prose answer must still be read by position, so filtering nulls before
// slicing would hand it a different slot.
test('diff with a failed panel lens: prose is still read from its own slot', async () => {
  const { result } = await review(diffArgs, { 'lens:correctness': null, 'lens:prose': { findings: [verified] } })
  assert.deepEqual(result.prose, { ran: true, findings: [verified] })
  assert.deepEqual(result.panel, { dispatched: 4, returned: 3, dropped: 1 })
})

test('diff: the prose agent gets the range, the commit log, the preamble, no severity or verdict', async () => {
  const { dispatched } = await review(
    { ...diffArgs, focus: 'auth paths', prDescription: 'Adds the retry wrapper.' },
    { 'lens:prose': { findings: [] } },
  )
  const prose = dispatched.find((d) => d.opts.label === 'lens:prose')
  assert.ok(prose.prompt.includes('git -C "/tmp/x" diff main...HEAD'))
  assert.ok(prose.prompt.includes('In scope: auth paths.'))
  assert.ok(prose.prompt.includes('Adds the retry wrapper.'))
  assert.ok(!prose.prompt.includes('No PR description was given'))
  assert.ok(!prose.prompt.includes("don't-ship"))
  const { opts } = prose
  assert.deepEqual([opts.agentType, opts.phase, opts.model, opts.effort], ['dev:reviewer', 'Review', 'sonnet', 'medium'])
  assert.deepEqual(opts.schema.required, ['findings'])
  assert.deepEqual(opts.schema.properties.findings.items.required, ['objection', 'confidence', 'location', 'suggested_fix'])
  assert.deepEqual(Object.keys(opts.schema.properties), ['findings'])
})

test('diff with no PR description: the prose agent is told not to report its absence', async () => {
  const { dispatched } = await review(diffArgs, { 'lens:prose': { findings: [] } })
  const prose = dispatched.find((d) => d.opts.label === 'lens:prose')
  assert.ok(prose.prompt.includes('No PR description was given: do not report its absence.'))
})

// `git log A...B` is the symmetric difference, so the log takes the two-dot form.
for (const [range, logRange] of [
  ['main...HEAD', 'main..HEAD'],
  ['main..HEAD', 'main..HEAD'],
]) {
  test(`diff ${range}: the diff keeps the range, the commit log reads ${logRange}`, async () => {
    const { dispatched } = await review({ ...diffArgs, diffRange: range }, { 'lens:prose': { findings: [] } })
    const { prompt } = dispatched.find((d) => d.opts.label === 'lens:prose')
    assert.ok(prompt.includes(`git -C "/tmp/x" diff ${range}\``))
    assert.ok(prompt.includes(`git -C "/tmp/x" log --format=%B ${logRange}\``))
  })
}

test('diff with no diffRange: the prose prompt has no commit log command', async () => {
  const { diffRange: _drop, ...noRange } = diffArgs
  const { dispatched } = await review(noRange, { 'lens:prose': { findings: [] } })
  const prose = dispatched.find((d) => d.opts.label === 'lens:prose')
  assert.ok(prose.prompt.includes('git -C "/tmp/x" diff'))
  assert.ok(!/git\b[^`]*\blog\b/.test(prose.prompt))
})
