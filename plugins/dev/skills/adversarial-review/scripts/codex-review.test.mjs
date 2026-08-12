import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { adaptCodexReview, sha256Hex, assertReviewableRange } from './codex-review.mjs'

const SCRIPT = fileURLToPath(new URL('./codex-review.mjs', import.meta.url))

test('approve verdict maps to ship:true, summary carried as reason', () => {
  const out = adaptCodexReview({ verdict: 'approve', summary: 'Looks fine.', findings: [], next_steps: [] })
  assert.equal(out.verdict.ship, true)
  assert.equal(out.verdict.reason, 'Looks fine.')
  assert.deepEqual(out.findings, [])
})

test('needs-attention maps to ship:false', () => {
  const out = adaptCodexReview({ verdict: 'needs-attention', summary: 'Problems.', findings: [], next_steps: [] })
  assert.equal(out.verdict.ship, false)
})

test('severity and confidence mapping', () => {
  const codex = {
    verdict: 'needs-attention',
    summary: 's',
    findings: [
      { severity: 'critical', title: 'A', body: 'ba', file: 'x.js', line_start: 3, line_end: 3, confidence: 0.9, recommendation: 'fix a' },
      { severity: 'high', title: 'B', body: 'bb', file: 'y.js', line_start: 5, line_end: 8, confidence: 0.5, recommendation: 'fix b' },
      { severity: 'medium', title: 'C', body: 'bc', file: 'z.js', line_start: 1, line_end: 1, confidence: 0.3, recommendation: '' },
      { severity: 'low', title: 'D', body: 'bd', file: 'w.js', line_start: 2, line_end: 2, confidence: 0.95, recommendation: 'fix d' },
    ],
    next_steps: [],
  }
  const out = adaptCodexReview(codex)
  assert.deepEqual(out.findings.map(f => f.severity), ['blocker', 'major', 'minor', 'minor'])
  assert.deepEqual(out.findings.map(f => f.confidence), ['verified', 'speculative', 'speculative', 'verified'])
  assert.equal(out.findings[0].location, 'x.js:3')
  assert.equal(out.findings[1].location, 'y.js:5-8')
  assert.equal(out.findings[0].objection, 'A. ba')
  assert.equal(out.findings[0].suggested_fix, 'fix a')
})

test('throws on non-conforming input (no silent empty vote)', () => {
  assert.throws(() => adaptCodexReview({ verdict: 'maybe', summary: 's', findings: [], next_steps: [] }))
  assert.throws(() => adaptCodexReview(null))
})

test('sha256Hex produces the sha256 of the given bytes', () => {
  // ONE smoke vector only (sha256("hello\n") is well-known): node:crypto does
  // the real work, and Task 2 Step 6 assertion 3 (independent sha256sum
  // cross-check) covers the actual byte path end to end.
  assert.equal(sha256Hex(Buffer.from('hello\n')), '5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03')
})

test('range validator accepts only <ref>...HEAD and returns the base', () => {
  assert.equal(assertReviewableRange('main...HEAD'), 'main')
  assert.equal(assertReviewableRange('HEAD~1...HEAD'), 'HEAD~1')
  assert.throws(() => assertReviewableRange('main..HEAD'))        // two-dot: different diff semantics
  assert.throws(() => assertReviewableRange('main...feature-x'))  // right side is not HEAD
  assert.throws(() => assertReviewableRange('main'))              // not a range at all
  assert.throws(() => assertReviewableRange(''))
})

test('CLI exits 2 with a companion-not-found reason when no companion is installed', () => {
  // The personal-machine-without-Codex negative (v5: availability is enforced
  // here, at tool run time, instead of by a discovery probe).
  const empty = mkdtempSync(join(tmpdir(), 'codex-review-test-'))
  try {
    const out = spawnSync(process.execPath, [SCRIPT, '--cwd', '.', '--range', 'HEAD~1...HEAD'], {
      encoding: 'utf8',
      env: { ...process.env, CODEX_COMPANION_ROOT: empty },
    })
    assert.equal(out.status, 2)
    assert.match(out.stderr, /companion not found/)
  } finally {
    rmSync(empty, { recursive: true, force: true })
  }
})
