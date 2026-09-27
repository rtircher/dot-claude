import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const src = readFileSync(fileURLToPath(new URL('./adversarial-review.js', import.meta.url)), 'utf8')
const body = (name) => {
  const start = src.indexOf(`function ${name}(`)
  assert.ok(start >= 0, `${name} not found`)
  const next = src.indexOf('\nfunction ', start + 1)
  return src.slice(start, next < 0 ? undefined : next)
}

test('the external courier passes focus and out-of-scope as files', () => {
  const b = body('externalCourier')
  assert.match(b, /art\.focusFile/)
  assert.match(b, /--focus-file/)
  assert.match(b, /art\.outOfScopeFile/)
  assert.match(b, /--out-of-scope-file/)
})

test('verifyPrompt carries focus and out-of-scope to the skeptics', () => {
  const b = body('verifyPrompt')
  assert.match(b, /art\.focus\b/)
  assert.match(b, /art\.outOfScope\b/)
})

test('args doc names focusFile and outOfScopeFile', () => {
  assert.match(src, /focusFile\?: string/)
  assert.match(src, /outOfScopeFile\?: string/)
})
