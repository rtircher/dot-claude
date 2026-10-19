import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Workflows are scripts, not modules, so load resolveModel's source from each
// and run it. Both copies must behave identically.
const load = (file) => {
  const src = readFileSync(fileURLToPath(new URL(file, import.meta.url)), 'utf8')
  const start = src.indexOf('function resolveModel(')
  assert.ok(start >= 0, `resolveModel not found in ${file}`)
  const end = src.indexOf('\n}\n', start) + 2
  return new Function(`${src.slice(start, end)}; return resolveModel`)()
}
const copies = { 'adversarial-review.js': load('./adversarial-review.js'), 'gated-review.js': load('./gated-review.js') }

for (const [file, resolveModel] of Object.entries(copies)) {
  test(`${file}: no map keeps the alias`, () => {
    for (const m of ['fable', 'opus', 'sonnet']) assert.equal(resolveModel(m, undefined, 'x'), m)
  })
  test(`${file}: fable falls back to opus`, () => {
    assert.equal(resolveModel('fable', { fable: 'opus' }, 'x'), 'opus')
    assert.equal(resolveModel('sonnet', { fable: 'opus' }, 'x'), 'sonnet')
  })
  test(`${file}: sonnet may be upgraded`, () => {
    assert.equal(resolveModel('sonnet', { sonnet: 'opus' }, 'x'), 'opus')
  })
  test(`${file}: a remap never targets sonnet`, () => {
    assert.throws(() => resolveModel('fable', { fable: 'sonnet' }, 'x'), /never targets sonnet/)
  })
  test(`${file}: unknown aliases throw`, () => {
    assert.throws(() => resolveModel('haiku', undefined, 'tiers.verify.model'), /tiers\.verify\.model must be/)
    assert.throws(() => resolveModel('fable', { fable: 'haiku' }, 'x'), /must be 'fable' or 'opus'/)
  })
}

// An omitted effort falls to the agent definition's default (medium for
// dev:researcher, which the verify skeptics run as), so every slot pins one.
test('adversarial-review.js: every DEFAULT_TIERS slot pins model and effort', () => {
  const src = readFileSync(fileURLToPath(new URL('./adversarial-review.js', import.meta.url)), 'utf8')
  const start = src.indexOf('const DEFAULT_TIERS = {')
  const end = src.indexOf('\n}\n', start) + 2
  const tiers = new Function(`${src.slice(start, end)}; return DEFAULT_TIERS`)()
  const efforts = ['low', 'medium', 'high', 'xhigh', 'max']
  for (const [key, t] of Object.entries(tiers)) {
    assert.ok(t.model, `${key} has no model`)
    assert.ok(efforts.includes(t.effort), `${key} has no valid effort`)
    // xhigh and max are per-run overrides, never defaults (conventions, "Model selection").
    assert.ok(efforts.indexOf(t.effort) <= efforts.indexOf('high'), `${key} defaults above high`)
  }
  assert.ok(efforts.indexOf(tiers.verify.effort) >= efforts.indexOf('high'), 'verify skeptics below high')
})
