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

// The part of a function body that is actually returned (from its first
// `return` to the end of the slice), so a variable that is computed but
// never interpolated into what ships cannot pass these assertions.
const returned = (b) => {
  const at = b.indexOf('return')
  assert.ok(at >= 0, 'no return found')
  return b.slice(at)
}

test('the external courier passes focus and out-of-scope as files', () => {
  const b = body('externalCourier')
  assert.match(b, /art\.focusFile/)
  assert.match(b, /art\.outOfScopeFile/)
  const r = returned(b)
  assert.match(r, /\$\{scope\}/)
  assert.match(b, /--focus-file/)
  assert.match(b, /--out-of-scope-file/)
})

test('scopeText names focus and out-of-scope', () => {
  const b = body('scopeText')
  assert.match(b, /art\.focus\b/)
  assert.match(b, /art\.outOfScope\b/)
})

test('verifyPrompt carries focus and out-of-scope to the skeptics', () => {
  const b = body('verifyPrompt')
  assert.match(b, /scopeText\(art\)/)
  const r = returned(b)
  assert.match(r, /\$\{scopeLine\}/)
})

test('args doc names focusFile and outOfScopeFile', () => {
  assert.match(src, /focusFile\?: string/)
  assert.match(src, /outOfScopeFile\?: string/)
})

test('a *File arg without its matching text arg is rejected at parse time', () => {
  assert.match(src, /art\.focusFile && !art\.focus/)
  assert.match(src, /art\.outOfScopeFile && !art\.outOfScope/)
})
