import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Runs the whole adversarial-review script with stubbed globals and counts the
// verify agents it dispatches: one skeptic per batch of 5, at most 4 agents.
const src = readFileSync(fileURLToPath(new URL('./adversarial-review.js', import.meta.url)), 'utf8').replace('export const meta', 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'phase', 'log', src)

const diffArgs = { artifactType: 'diff', diffRange: 'main...HEAD', repoDir: '/tmp/x', externalReview: false }

// The correctness lens raises n distinct major findings; no other reviewer
// corroborates them, so each needs verification. Skeptics refute everything.
async function verifyRun(n) {
  const findings = Array.from({ length: n }, (_, i) => ({
    objection: `distinct objection number ${i} about module ${i}`,
    severity: 'major',
    confidence: 'verified',
    location: `file${i}.py:${i + 1}`,
    suggested_fix: `fix ${i}`,
  }))
  const verifyLabels = []
  const agent = async (prompt, opts) => {
    if (opts.label.startsWith('verify:')) {
      verifyLabels.push(opts.label)
      const idx = [...prompt.matchAll(/^Finding (\d+) \[/gm)].map((m) => Number(m[1]))
      return { verdicts: idx.map((index) => ({ index, verdict: 'refuted', confidence: 'high', reasoning: 'guarded' })) }
    }
    return { findings: opts.label === 'lens:correctness' ? findings : [], verdict: { ship: true, reason: 'ok' } }
  }
  const parallel = (thunks) => Promise.all(thunks.map((t) => t().catch(() => null)))
  const result = await run(diffArgs, agent, parallel, () => {}, () => {})
  return { result, verifyLabels }
}

test('7 uncorroborated findings dispatch 2 verify agents, one per batch', async () => {
  const { result, verifyLabels } = await verifyRun(7)
  assert.deepEqual(verifyLabels.sort(), ['verify:0.0', 'verify:1.0'])
  assert.equal(result.refuted.length, 7)
})

test('25 findings dispatch 4 verify agents; 5 are capped out and stay contested', async () => {
  const { result, verifyLabels } = await verifyRun(25)
  assert.equal(verifyLabels.length, 4)
  assert.equal(result.refuted.length, 20)
  const unverified = result.findings.filter((f) => f.verification.status === 'contested')
  assert.equal(unverified.length, 5)
  assert.equal(result.hasBlockerOrMajor, true)
})
