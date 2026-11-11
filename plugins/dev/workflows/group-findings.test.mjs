import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Runs the whole adversarial-review script with stubbed globals and checks the
// grouping step: findings from different lenses that name one defect become one.
const src = readFileSync(fileURLToPath(new URL('./adversarial-review.js', import.meta.url)), 'utf8').replace('export const meta', 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'phase', 'log', src)

const specArgs = { artifactType: 'spec', artifactPath: '/tmp/spec.md', externalReview: false }
const finding = (objection, severity, location) => ({ objection, severity, confidence: 'verified', location, suggested_fix: 'fix it' })

// The same defect in two lenses' words, plus one unrelated finding.
const BY_LENS = {
  'lens:gaps': [finding('Section 6 blockers have no chosen decision', 'blocker', 'Section 6 items 1-2')],
  'lens:comprehension': [finding('Sections 2 to 5 describe a design section 6 calls broken', 'major', 'Sections 2-5')],
  'lens:scope-yagni': [finding('The dot-files self-fix mode is out of scope', 'major', 'Section 4')],
}

// `group` is what the grouping agent returns, or a function that throws.
async function review(group) {
  const dispatched = []
  const agent = async (prompt, opts) => {
    dispatched.push({ prompt, opts })
    if (opts.label === 'group') return typeof group === 'function' ? group() : group
    if (opts.label.startsWith('verify:')) {
      const idx = [...prompt.matchAll(/^Finding (\d+) \[/gm)].map((m) => Number(m[1]))
      return { verdicts: idx.map((index) => ({ index, verdict: 'confirmed', confidence: 'high', reasoning: 'checked' })) }
    }
    return { findings: BY_LENS[opts.label] || [], verdict: { ship: false, reason: 'no' } }
  }
  const parallel = (thunks) => Promise.all(thunks.map((t) => t().catch(() => null)))
  const result = await run(specArgs, agent, parallel, () => {}, () => {})
  return { result, dispatched }
}

test('a group becomes one finding led by its most severe member, corroborated by both lenses', async () => {
  const { result, dispatched } = await review({ groups: [{ ids: [0, 2], lead: 0 }] })
  const groupPrompt = dispatched.find((d) => d.opts.label === 'group').prompt
  // Indexes follow the fold's order, which follows the panel order: gaps before scope-yagni before comprehension.
  assert.ok(groupPrompt.includes('[0] (blocker) Section 6 items 1-2'))
  assert.ok(!groupPrompt.includes('lens:') && !groupPrompt.includes('comprehension'))
  const lead = result.findings.find((f) => f.objection.startsWith('Section 6 blockers'))
  assert.deepEqual(lead.corroboration, { reviewers: 2, crossFamily: false, sources: ['gaps', 'comprehension'] })
  assert.deepEqual(lead.merged.map((m) => m.objection), ['Sections 2 to 5 describe a design section 6 calls broken'])
  assert.equal(result.findings.length, 2)
})

test('grouped findings skip the skeptics; the rest are verified', async () => {
  const { dispatched } = await review({ groups: [{ ids: [0, 2], lead: 0 }] })
  const verifyPrompts = dispatched.filter((d) => d.opts.label.startsWith('verify:')).map((d) => d.prompt).join('\n')
  assert.ok(verifyPrompts.includes('The dot-files self-fix mode is out of scope'))
  assert.ok(!verifyPrompts.includes('Section 6 blockers'))
})

for (const [name, group] of [
  ['the grouping agent throws', () => { throw new Error('agent died') }],
  ['it returns no groups', { groups: [] }],
  ['it returns only invalid groups', { groups: [{ ids: [0], lead: 0 }, { ids: [7, 9], lead: 7 }, { ids: [1, 1], lead: 1 }, [0, 2]] }],
]) {
  test(`${name}: every finding is kept as the fold left it`, async () => {
    const { result } = await review(group)
    assert.equal(result.findings.length, 3)
    assert.ok(result.findings.every((f) => !f.merged && f.corroboration.reviewers === 1))
  })
}

test('an id already in a group is not grouped twice', async () => {
  const { result } = await review({ groups: [{ ids: [0, 1], lead: 0 }, { ids: [1, 2], lead: 2 }] })
  assert.equal(result.findings.length, 2)
  assert.equal(result.findings.filter((f) => f.merged).length, 1)
})

test('the chosen lead supplies the wording; the group keeps the highest severity', async () => {
  const { result } = await review({ groups: [{ ids: [0, 2], lead: 2 }] })
  const group = result.findings.find((f) => f.merged)
  assert.equal(group.objection, 'Sections 2 to 5 describe a design section 6 calls broken')
  assert.equal(group.severity, 'blocker')
  assert.deepEqual(group.merged.map((m) => m.objection), ['Section 6 blockers have no chosen decision'])
})

test('a lead outside its group falls back to the most severe member', async () => {
  const { result } = await review({ groups: [{ ids: [0, 2], lead: 1 }] })
  const group = result.findings.find((f) => f.merged)
  assert.equal(group.objection, 'Section 6 blockers have no chosen decision')
})

test('a minor finding is kept out of a group with a major or blocker one', async () => {
  BY_LENS['lens:code-grounding'] = [finding('The dot-files memory rule is narrower than v1', 'minor', 'Section 4')]
  try {
    // ids: 0 gaps (blocker), 1 scope-yagni (major), 2 comprehension (major), 3 code-grounding (minor)
    const { result } = await review({ groups: [{ ids: [1, 3], lead: 3 }, { ids: [0, 2], lead: 0 }] })
    assert.equal(result.findings.length, 3)
    assert.ok(result.findings.some((f) => f.objection.startsWith('The dot-files memory rule') && !f.merged))
  } finally {
    delete BY_LENS['lens:code-grounding']
  }
})

test('minor findings still group with each other', async () => {
  BY_LENS['lens:code-grounding'] = [finding('Term A is undefined', 'minor', 'Section 1'), finding('Section 1 never defines A', 'minor', 'Section 1 para 2')]
  try {
    const { result } = await review({ groups: [{ ids: [3, 4], lead: 3 }] })
    assert.equal(result.findings.filter((f) => f.merged).length, 1)
  } finally {
    delete BY_LENS['lens:code-grounding']
  }
})

test('a single finding dispatches no grouping agent', async () => {
  const saved = { ...BY_LENS }
  delete BY_LENS['lens:comprehension']
  delete BY_LENS['lens:scope-yagni']
  try {
    const { dispatched } = await review({ groups: [] })
    assert.ok(!dispatched.some((d) => d.opts.label === 'group'))
  } finally {
    Object.assign(BY_LENS, saved)
  }
})
