import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { fileURLToPath } from 'node:url'
import { existsSync, mkdtempSync, utimesSync, writeFileSync } from 'node:fs'
import { hostname, tmpdir } from 'node:os'
import { join } from 'node:path'
import { isLoopback, resolveReviewers, selectReviewers } from './external-review.mjs'
import { hostKey, lockPath } from './host-lock.mjs'

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

// Stub whose "good" responses take delayMs; records peak concurrent requests.
async function slowServer(delayMs) {
  const stats = { inFlight: 0, peak: 0, requests: 0 }
  const server = createServer((req, res) => {
    stats.requests++
    stats.peak = Math.max(stats.peak, ++stats.inFlight)
    req.resume()
    setTimeout(() => {
      stats.inFlight--
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(REVIEW) } }] }))
    }, delayMs)
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  return { server, stats, base: `http://127.0.0.1:${server.address().port}/v1` }
}

// No Codex companion unless a test asks for one.
const NO_CODEX = mkdtempSync(join(tmpdir(), 'no-codex-'))

function run(env, stdin, type = 'diff', extraArgs = []) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT, '--type', type, '--target', 't', ...extraArgs], {
      env: { PATH: process.env.PATH, CODEX_COMPANION_ROOT: NO_CODEX, EXTERNAL_REVIEW_LOCK_DIR: mkdtempSync(join(tmpdir(), 'review-lock-')), ...env },
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

test('only private endpoints queue on the host lock by default; serialize overrides', () => {
  const rs = resolveReviewers({
    K: 'sk-x',
    EXTERNAL_REVIEWERS: JSON.stringify([
      { name: 'local', model: 'q', baseUrl: 'http://LOCALHOST:11434/v1' },
      { name: 'hosted', model: 'g', baseUrl: 'https://api.example.com/v1', apiKeyEnv: 'K' },
      { name: 'hosted-queued', model: 'g', baseUrl: 'https://api.example.com/v1', apiKeyEnv: 'K', serialize: true },
      { name: 'local-free', model: 'q', baseUrl: 'http://localhost:11434/v1', serialize: false },
    ]),
  }, noCodex)
  assert.deepEqual(rs.map((r) => r.serialize), [true, false, true, false])
  assert.equal(rs[0].lockKey, 'localhost:11434')
  assert.equal(rs[1].lockKey, 'api.example.com:443')
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

test('--only runs exactly the named reviewer', async () => {
  const server = await stubServer()
  try {
    const base = `http://127.0.0.1:${server.address().port}/v1`
    const { code, stdout, stderr } = await run({
      EXTERNAL_REVIEWERS: JSON.stringify([
        { name: 'ok', model: 'good', baseUrl: base },
        { name: 'down', model: 'bad', baseUrl: base },
      ]),
    }, 'x\n', 'spec', ['--only', 'ok'])
    assert.equal(code, 0, stderr)
    const out = JSON.parse(stdout)
    assert.deepEqual(out.votes.map((v) => v.name), ['ok'])
    assert.deepEqual(out.votes[0].verdict, REVIEW.verdict)
  } finally {
    server.close()
  }
})

test('--only with an unknown name exits 1 naming the configured reviewers', async () => {
  const { code, stderr } = await run({ EXTERNAL_REVIEWERS: '[{"name":"a","model":"m","baseUrl":"http://localhost/v1"}]' }, 'x\n', 'diff', ['--only', 'nope'])
  assert.equal(code, 1)
  assert.match(stderr, /--only names no configured reviewer: "nope" \(configured: a\)/)
  assert.throws(() => selectReviewers([], ['x']), /configured: none/)
})

test('--list prints the configured names without reading stdin', async () => {
  const { code, stdout, stderr } = await new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT, '--list'], {
      env: { PATH: process.env.PATH, CODEX_COMPANION_ROOT: NO_CODEX, EXTERNAL_REVIEWERS: '[{"name":"codex","kind":"codex"},{"model":"m","baseUrl":"http://localhost/v1"}]' },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (c) => (stdout += c))
    child.stderr.on('data', (c) => (stderr += c))
    child.on('close', (code) => resolve({ code, stdout, stderr }))
  })
  assert.equal(code, 0, stderr)
  assert.deepEqual(JSON.parse(stdout), { names: ['codex', 'm'] })
})

const reviewers = (...entries) => ({ EXTERNAL_REVIEWERS: JSON.stringify(entries) })

test('two processes reviewing on one host send one request at a time', async () => {
  const { server, stats, base } = await slowServer(400)
  try {
    const lockDir = mkdtempSync(join(tmpdir(), 'review-lock-'))
    const env = { ...reviewers({ name: 'ok', model: 'good', baseUrl: base }), EXTERNAL_REVIEW_LOCK_DIR: lockDir }
    const results = await Promise.all([run(env, 'x\n', 'spec'), run(env, 'y\n', 'spec')])
    for (const { code, stdout, stderr } of results) {
      assert.equal(code, 0, stderr)
      assert.deepEqual(JSON.parse(stdout).votes[0].verdict, REVIEW.verdict)
    }
    assert.equal(stats.requests, 2)
    assert.equal(stats.peak, 1)
    assert.equal(existsSync(lockPath(lockDir, hostKey(base))), false)
  } finally {
    server.close()
  }
})

test('different hosts are reviewed in parallel', async () => {
  const a = await slowServer(600)
  const b = await slowServer(600)
  try {
    const started = Date.now()
    const { code, stdout, stderr } = await run(reviewers(
      { name: 'a', model: 'good', baseUrl: a.base },
      { name: 'b', model: 'good', baseUrl: b.base },
    ), 'x\n', 'spec')
    assert.equal(code, 0, stderr)
    assert.deepEqual(JSON.parse(stdout).votes.map((v) => v.verdict), [REVIEW.verdict, REVIEW.verdict])
    // Serialized, the two 600 ms responses alone would take 1200 ms.
    assert.ok(Date.now() - started < 1150, `took ${Date.now() - started} ms`)
  } finally {
    a.server.close()
    b.server.close()
  }
})

test('time queued for the host lock does not count against the request timeout', async () => {
  const { server, stats, base } = await slowServer(700)
  try {
    const env = { ...reviewers({ name: 'ok', model: 'good', baseUrl: base }), EXTERNAL_REVIEW_LOCK_DIR: mkdtempSync(join(tmpdir(), 'review-lock-')), EXTERNAL_REVIEW_TIMEOUT_MS: '1000' }
    // The second process waits ~700 ms, then needs 700 ms more: 1400 ms > timeout.
    const results = await Promise.all([run(env, 'x\n', 'spec'), run(env, 'y\n', 'spec')])
    for (const { stdout } of results) assert.equal(JSON.parse(stdout).votes[0].__error, undefined, stdout)
    assert.equal(stats.peak, 1)
  } finally {
    server.close()
  }
})

test('a host busy past the max wait drops the vote as queued past max wait', async () => {
  const { server, stats, base } = await slowServer(0)
  try {
    const lockDir = mkdtempSync(join(tmpdir(), 'review-lock-'))
    writeFileSync(lockPath(lockDir, hostKey(base)), JSON.stringify({ pid: process.pid, host: hostname(), token: 'held' }))
    const { code, stdout } = await run({ ...reviewers({ name: 'ok', model: 'good', baseUrl: base }), EXTERNAL_REVIEW_LOCK_DIR: lockDir, EXTERNAL_REVIEW_MAX_WAIT_MS: '300' }, 'x\n', 'spec')
    assert.equal(code, 0)
    assert.match(JSON.parse(stdout).votes[0].__error, /^queued past max wait: 127\.0\.0\.1:\d+ was busy/)
    assert.equal(stats.requests, 0)
  } finally {
    server.close()
  }
})

test('a lock left by a dead process or with a stale heartbeat is recovered', async () => {
  const { server, base } = await slowServer(0)
  try {
    const deadPid = spawnSync(process.execPath, ['-e', '']).pid
    const lockDir = mkdtempSync(join(tmpdir(), 'review-lock-'))
    const path = lockPath(lockDir, hostKey(base))
    const env = { ...reviewers({ name: 'ok', model: 'good', baseUrl: base }), EXTERNAL_REVIEW_LOCK_DIR: lockDir, EXTERNAL_REVIEW_MAX_WAIT_MS: '2000' }

    writeFileSync(path, JSON.stringify({ pid: deadPid, host: hostname(), token: 'dead' }))
    let out = JSON.parse((await run(env, 'x\n', 'spec')).stdout)
    assert.deepEqual(out.votes[0].verdict, REVIEW.verdict)

    // Live pid, but no heartbeat for an hour (hung holder, or written elsewhere).
    writeFileSync(path, JSON.stringify({ pid: process.pid, host: 'other-machine', token: 'old' }))
    const hourAgo = new Date(Date.now() - 3_600_000)
    utimesSync(path, hourAgo, hourAgo)
    out = JSON.parse((await run(env, 'x\n', 'spec')).stdout)
    assert.deepEqual(out.votes[0].verdict, REVIEW.verdict)
    assert.equal(existsSync(path), false)
  } finally {
    server.close()
  }
})
