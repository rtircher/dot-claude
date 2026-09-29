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
