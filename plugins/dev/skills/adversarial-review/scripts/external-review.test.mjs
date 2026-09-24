import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { fileURLToPath } from 'node:url'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { isLoopback, resolveReviewers } from './external-review.mjs'

const SCRIPT = fileURLToPath(new URL('./external-review.mjs', import.meta.url))

const REVIEW = {
  findings: [{ objection: 'o', severity: 'major', confidence: 'verified', location: 'a.js:1', suggested_fix: 'f' }],
  verdict: { ship: false, reason: 'r' },
}

// Stub OpenAI-compatible server: model "good" returns a valid review, any
// other model gets a 500.
function stubServer() {
  const server = createServer((req, res) => {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', () => {
      const { model } = JSON.parse(body)
      if (model !== 'good') {
        res.writeHead(500).end('boom')
        return
      }
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(REVIEW) } }] }))
    })
  })
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)))
}

// No Codex companion unless a test asks for one.
const NO_CODEX = mkdtempSync(join(tmpdir(), 'no-codex-'))

function run(env, stdin, type = 'diff') {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT, '--type', type, '--target', 't'], {
      env: { PATH: process.env.PATH, CODEX_COMPANION_ROOT: NO_CODEX, ...env },
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (c) => (stdout += c))
    child.stderr.on('data', (c) => (stderr += c))
    child.on('close', (code) => resolve({ code, stdout, stderr }))
    child.stdin.end(stdin)
  })
}

const noCodex = { codexAvailable: () => false }

test('loopback only is private by default', () => {
  for (const h of ['localhost', '127.0.0.1', '127.1.2.3', '[::1]']) assert.equal(isLoopback(h), true, h)
  for (const h of ['box.tailefad8.ts.net', '100.64.0.1', 'api.openai.com', 'localhost.evil.com']) assert.equal(isLoopback(h), false, h)
})

test('nothing configured and no Codex resolves to no reviewers', () => {
  assert.deepEqual(resolveReviewers({}, noCodex), [])
  assert.deepEqual(resolveReviewers({ EXTERNAL_REVIEWERS: '[]' }, { codexAvailable: () => true }), [])
})

test('unset config falls back to the legacy vars plus an installed Codex', () => {
  const rs = resolveReviewers({ EXTERNAL_REVIEW_MODEL: 'qwen', EXTERNAL_REVIEW_BASE_URL: 'http://localhost:11434/v1' }, { codexAvailable: () => true })
  assert.deepEqual(rs.map((r) => [r.name, r.kind]), [['qwen', 'openai-compatible'], ['codex', 'codex']])
  assert.equal(rs[0].problem, null)
  assert.equal(rs[0].private, true)
})

test('EXTERNAL_REVIEWERS is the complete list; private is declared per entry', () => {
  const rs = resolveReviewers({
    EXTERNAL_REVIEW_MODEL: 'ignored',
    OPENAI_KEY: 'sk-x',
    EXTERNAL_REVIEWERS: JSON.stringify([
      { name: 'codex', kind: 'codex' },
      { name: 'mc', model: 'qwen', baseUrl: 'http://box.tailefad8.ts.net:11434/v1', private: true, family: 'alibaba' },
      { model: 'tailnet-undeclared', baseUrl: 'http://box.tailefad8.ts.net:11434/v1' },
      { model: 'gpt', baseUrl: 'https://api.openai.com/v1', apiKeyEnv: 'OPENAI_KEY' },
      { model: 'claude-sonnet', baseUrl: 'http://localhost:1/v1' },
    ]),
  }, { codexAvailable: () => false })
  assert.deepEqual(rs.map((r) => r.name), ['codex', 'mc', 'tailnet-undeclared', 'gpt', 'claude-sonnet'])
  assert.equal(rs[1].problem, null)
  assert.equal(rs[1].family, 'alibaba')
  assert.match(rs[2].problem, /no API key .*"private": true/)
  assert.equal(rs[3].apiKey, 'sk-x')
  assert.equal(rs[3].problem, null)
  assert.match(rs[4].problem, /Claude-family/)
})

test('EXTERNAL_REVIEWERS rejects bad JSON, unknown kinds and duplicate names', () => {
  assert.throws(() => resolveReviewers({ EXTERNAL_REVIEWERS: '[' }, noCodex), /not valid JSON/)
  assert.throws(() => resolveReviewers({ EXTERNAL_REVIEWERS: '{}' }, noCodex), /JSON array/)
  assert.throws(() => resolveReviewers({ EXTERNAL_REVIEWERS: '[{"kind":"cursor"}]' }, noCodex), /unknown kind/)
  assert.throws(
    () => resolveReviewers({ EXTERNAL_REVIEWERS: JSON.stringify([{ model: 'a', baseUrl: 'http://localhost/v1' }, { model: 'a', baseUrl: 'http://localhost/v1' }]) }, noCodex),
    /two reviewers named "a"/,
  )
})

test('one vote per reviewer, failures and skips reported by name, exit 0', async () => {
  const server = await stubServer()
  try {
    const base = `http://127.0.0.1:${server.address().port}/v1`
    const stdin = 'diff --git a/x b/x\n+hello\n'
    const { code, stdout, stderr } = await run({
      EXTERNAL_REVIEWERS: JSON.stringify([
        { name: 'ok', model: 'good', baseUrl: base },
        { name: 'down', model: 'bad', baseUrl: base },
        { name: 'codex', kind: 'codex' },
      ]),
    }, stdin, 'spec')
    assert.equal(code, 0, stderr)
    const out = JSON.parse(stdout)
    const sha = createHash('sha256').update(stdin).digest('hex')
    assert.equal(out.reviewer.mode, 'multi')
    assert.equal(out.configured, true)
    assert.equal(out.artifactSha256, sha)
    const [ok, down, codex] = out.votes
    assert.equal(ok.reviewer.kind, 'external-review-script')
    assert.equal(ok.reviewer.name, 'ok')
    assert.equal(ok.artifactSha256, sha)
    assert.deepEqual(ok.verdict, REVIEW.verdict)
    assert.equal(down.name, 'down')
    assert.match(down.__error, /API returned 500/)
    assert.deepEqual(codex, { name: 'codex', skipped: 'not applicable to spec' })
  } finally {
    server.close()
  }
})

test('a machine with nothing configured reports configured:false, exit 0', async () => {
  const { code, stdout, stderr } = await run({}, 'x\n')
  assert.equal(code, 0, stderr)
  const out = JSON.parse(stdout)
  assert.equal(out.configured, false)
  assert.deepEqual(out.votes, [])
})

test('only-skipped reviewers also count as not configured', async () => {
  const { stdout } = await run({ EXTERNAL_REVIEWERS: '[{"kind":"codex"}]' }, 'x\n', 'plan')
  assert.equal(JSON.parse(stdout).configured, false)
})

test('a config error exits 1 with the reason', async () => {
  const { code, stderr } = await run({ EXTERNAL_REVIEWERS: '[' }, 'x\n')
  assert.equal(code, 1)
  assert.match(stderr, /not valid JSON/)
})
