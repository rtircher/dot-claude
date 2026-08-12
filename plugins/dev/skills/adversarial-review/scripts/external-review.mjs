#!/usr/bin/env node
/**
 * One-shot, read-only third-party reviewer for the adversarial-review skill.
 *
 * Sends the artifact on stdin to any OpenAI-compatible chat-completions API
 * (OpenAI, most hosted providers, Ollama / llama.cpp locally) with the skill's
 * adversarial framing, and prints schema-validated findings as JSON on stdout —
 * the same finding shape the dev-adversarial-review workflow synthesizes, so
 * the output folds straight into the panel as one more independent vote.
 *
 * Read-only by construction: no tools, no filesystem access, no agent loop.
 * The artifact travels on stdin, never argv, so it cannot leak through process
 * listings or shell history.
 *
 * Usage:
 *   git diff main...HEAD | \
 *     EXTERNAL_REVIEW_MODEL=gpt-5 EXTERNAL_REVIEW_API_KEY=sk-... \
 *     node external-review.mjs --type diff --target "main...HEAD @ a1b2c3d"
 *
 * Env:
 *   EXTERNAL_REVIEW_MODEL     required; refused if it names a Claude model
 *                             (a same-family reviewer adds no independence) —
 *                             override with --allow-same-family
 *   EXTERNAL_REVIEW_BASE_URL  default https://api.openai.com/v1; point at
 *                             http://localhost:11434/v1 for Ollama
 *   EXTERNAL_REVIEW_API_KEY   required unless the base URL host is local
 *   EXTERNAL_REVIEW_TIMEOUT_MS  default 300000
 *
 * Flags:
 *   --type spec|plan|diff   what the artifact is (default diff)
 *   --target <desc>         required: the range/path + pinned SHA the caller is
 *                           reviewing, echoed back so the run is bound to the
 *                           same artifact as the rest of the panel
 *   --focus <note>          optional in-scope note
 *   --out-of-scope <note>   optional exclusions
 *   --allow-same-family     permit a Claude model (defeats cross-family review)
 *
 * Exit codes: 0 ok · 1 usage/env error · 2 API error · 3 unusable response
 */

import { createHash } from 'node:crypto'

// Mirrors REVIEW_SCHEMA in workflows/adversarial-review.js — keep in sync.
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['findings', 'verdict'],
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['objection', 'severity', 'confidence', 'location', 'suggested_fix'],
        additionalProperties: false,
        properties: {
          objection: { type: 'string', description: 'What is wrong, specifically.' },
          severity: { enum: ['blocker', 'major', 'minor'] },
          confidence: {
            enum: ['verified', 'speculative'],
            description: 'verified = demonstrable entirely within the artifact text; speculative = inferred from a smell or partial view',
          },
          location: { type: 'string', description: 'Exact section / file / hunk the objection points at' },
          suggested_fix: { type: 'string' },
        },
      },
    },
    verdict: {
      type: 'object',
      required: ['ship', 'reason'],
      additionalProperties: false,
      properties: {
        ship: { type: 'boolean' },
        reason: { type: 'string', description: 'One sentence.' },
      },
    },
  },
}

// Past this size the tail silently falls off most context windows; refuse
// loudly instead so the caller narrows scope (the skill bans silent caps).
const MAX_ARTIFACT_CHARS = 400_000

function fail(code, msg) {
  process.stderr.write(`external-review: ${msg}\n`)
  process.exit(code)
}

function parseArgs(argv) {
  const opts = { type: 'diff', target: '', focus: '', outOfScope: '', allowSameFamily: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => {
      if (i + 1 >= argv.length) fail(1, `${a} requires a value`)
      return argv[++i]
    }
    if (a === '--type') opts.type = next()
    else if (a === '--target') opts.target = next()
    else if (a === '--focus') opts.focus = next()
    else if (a === '--out-of-scope') opts.outOfScope = next()
    else if (a === '--allow-same-family') opts.allowSameFamily = true
    else fail(1, `unknown flag ${a}`)
  }
  if (!['spec', 'plan', 'diff'].includes(opts.type)) fail(1, `--type must be spec|plan|diff, got "${opts.type}"`)
  if (!opts.target) fail(1, '--target is required: the range/path + pinned SHA this review is bound to')
  return opts
}

async function readStdin() {
  if (process.stdin.isTTY) fail(1, 'no artifact on stdin (pipe the diff or document in; never pass it as an argument)')
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return Buffer.concat(chunks) // raw bytes; caller hashes BEFORE decoding
}

function buildPrompt(opts, artifact) {
  const scope = [
    opts.focus && `In scope: ${opts.focus}.`,
    opts.outOfScope && `Out of scope (ignore): ${opts.outOfScope}.`,
  ].filter(Boolean).join(' ')
  return `You are an INDEPENDENT adversarial reviewer. Assume the author is over-confident. Find what is WRONG with this ${opts.type}, not what is fine; surface real problems, not style nits. When unsure whether something is a problem, flag it rather than let it pass. ${scope}

You have no tools and cannot open files: label a finding "verified" only when the problem is demonstrable entirely within the artifact text below; anything inferred from a smell or a partial view is "speculative".

Review target (pinned by the caller): ${opts.target}

End with a single verdict: ship or don't-ship, with one sentence why.

--- ARTIFACT (${opts.type}) ---
${artifact}
--- END ARTIFACT ---`
}

async function callApi(baseUrl, apiKey, body, timeoutMs) {
  const res = await fetch(`${baseUrl.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(apiKey ? { authorization: `Bearer ${apiKey}` } : {}) },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  })
  return { status: res.status, text: await res.text() }
}

// Salvage a JSON object from prose for servers without structured-output support.
function extractJson(text) {
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start === -1 || end <= start) return null
  try {
    return JSON.parse(text.slice(start, end + 1))
  } catch {
    return null
  }
}

function validate(review) {
  if (!review || !Array.isArray(review.findings) || typeof review.verdict?.ship !== 'boolean' || typeof review.verdict?.reason !== 'string') return null
  for (const f of review.findings) {
    if (typeof f.objection !== 'string' || typeof f.location !== 'string' || typeof f.suggested_fix !== 'string') return null
    if (!['blocker', 'major', 'minor'].includes(f.severity)) return null
    if (!['verified', 'speculative'].includes(f.confidence)) return null
  }
  return { findings: review.findings, verdict: { ship: review.verdict.ship, reason: review.verdict.reason } }
}

const opts = parseArgs(process.argv.slice(2))

const model = process.env.EXTERNAL_REVIEW_MODEL || ''
if (!model) fail(1, 'EXTERNAL_REVIEW_MODEL is required (e.g. gpt-5, or a local model served via Ollama)')
if (/claude|anthropic/i.test(model) && !opts.allowSameFamily) {
  fail(1, `"${model}" is a Claude-family model: it shares the panel's blind spots and adds no independence. Pick a different family, or pass --allow-same-family if you really mean it.`)
}

const baseUrl = process.env.EXTERNAL_REVIEW_BASE_URL || 'https://api.openai.com/v1'
let host
try {
  host = new URL(baseUrl).hostname
} catch {
  fail(1, `EXTERNAL_REVIEW_BASE_URL is not a valid URL: "${baseUrl}"`)
}
const isLocal = host === 'localhost' || host === '127.0.0.1' || host === '::1'
const apiKey = process.env.EXTERNAL_REVIEW_API_KEY || ''
if (!apiKey && !isLocal) fail(1, `EXTERNAL_REVIEW_API_KEY is required for non-local endpoint ${host}`)

const timeoutMs = Number(process.env.EXTERNAL_REVIEW_TIMEOUT_MS) || 300_000

// Hash the RAW stdin bytes before decoding: for artifacts containing invalid
// UTF-8 (non-UTF-8 text files, some binary hunks in a diff) the lossy decode
// changes the bytes, and the digest must stay byte-exact against the caller's
// raw-byte sha256sum for the workflow's equality gate to hold.
const artifactBytes = await readStdin()
const artifactSha256 = createHash('sha256').update(artifactBytes).digest('hex')
const artifact = artifactBytes.toString('utf8')
if (!artifact.trim()) fail(1, 'stdin was empty — nothing to review')
if (artifact.length > MAX_ARTIFACT_CHARS) {
  fail(1, `artifact is ${artifact.length} chars (max ${MAX_ARTIFACT_CHARS}); narrow the diff range or split the document instead of truncating`)
}

const prompt = buildPrompt(opts, artifact)
const baseBody = { model, messages: [{ role: 'user', content: prompt }] }

let { status, text } = await callApi(baseUrl, apiKey, {
  ...baseBody,
  response_format: { type: 'json_schema', json_schema: { name: 'review', strict: true, schema: REVIEW_SCHEMA } },
}, timeoutMs)

// Some OpenAI-compatible servers reject response_format outright; retry once
// with the schema inlined in the prompt instead.
if (status === 400) {
  ;({ status, text } = await callApi(baseUrl, apiKey, {
    ...baseBody,
    messages: [{
      role: 'user',
      content: `${prompt}\n\nRespond with ONLY a JSON object matching this JSON Schema, no prose:\n${JSON.stringify(REVIEW_SCHEMA)}`,
    }],
  }, timeoutMs))
}
if (status !== 200) fail(2, `API returned ${status} from ${host}: ${text.slice(0, 500)}`)

let content
try {
  content = JSON.parse(text).choices?.[0]?.message?.content
} catch {
  fail(2, `API response from ${host} was not JSON: ${text.slice(0, 200)}`)
}
if (typeof content !== 'string' || !content) fail(3, 'API response had no message content')

const review = validate(extractJson(content))
if (!review) fail(3, `model output did not match the findings schema: ${content.slice(0, 500)}`)

// The digest pins exactly what was reviewed, so the caller can confirm this
// vote covered the same bytes as the rest of the panel before folding it in.
process.stdout.write(JSON.stringify({
  reviewer: { kind: 'external-review-script', model, endpoint: host, family: 'external' },
  target: opts.target,
  artifactType: opts.type,
  artifactSha256,
  verdict: review.verdict,
  findings: review.findings,
}, null, 2) + '\n')
