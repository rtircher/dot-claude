#!/usr/bin/env node
/**
 * Read-only third-party reviewer dispatcher for the adversarial-review skill.
 *
 * Runs every external reviewer THIS MACHINE configures (none by default) on the
 * artifact on stdin and prints one vote per reviewer, each schema-validated and
 * stamped with a sha256 of the exact bytes reviewed, so the workflow can bind
 * every vote to the caller-pinned artifact. The plugin names no model, vendor
 * or host: which reviewers exist is entirely the machine's config.
 *
 * Reviewer kinds:
 *   openai-compatible  POST to any chat-completions API (OpenAI, hosted
 *                      providers, Ollama / llama.cpp / vLLM). No tools, no
 *                      filesystem access, no agent loop.
 *   codex              the Codex CLI companion via codex-review.mjs (diffs of
 *                      the form <ref>...HEAD only; needs --cwd and --range).
 * The artifact travels on stdin, never argv, so it cannot leak through process
 * listings or shell history.
 *
 * Usage:
 *   git diff main...HEAD | node external-review.mjs --type diff \
 *     --target "main...HEAD @ a1b2c3d" --cwd . --range main...HEAD
 *
 * Config (env):
 *   EXTERNAL_REVIEWERS  JSON array; the complete list when set ("[]" = none):
 *     {"name":"codex","kind":"codex"}
 *     {"name":"qwen","kind":"openai-compatible","model":"qwen3.8:27b",
 *      "baseUrl":"http://gpu-box:11434/v1","private":true}
 *     {"name":"gpt","kind":"openai-compatible","model":"gpt-5",
 *      "baseUrl":"https://api.openai.com/v1","apiKeyEnv":"OPENAI_API_KEY"}
 *   name defaults to the model (or the kind) and must be unique. kind defaults
 *   to openai-compatible. "private": true declares the endpoint is hardware the
 *   user controls (no API key needed, no consent stop); loopback is always
 *   private, anything else without the flag is treated as a hosted vendor.
 *   Optional "family" (e.g. "google") is echoed for reporting.
 *
 *   Unset: the legacy single-reviewer vars below, if present, plus Codex when
 *   its companion is installed (skipped silently when it is not), so a machine
 *   with nothing set and no Codex gets a clean "none configured".
 *     EXTERNAL_REVIEW_MODEL / EXTERNAL_REVIEW_BASE_URL / EXTERNAL_REVIEW_API_KEY
 *
 *   EXTERNAL_REVIEW_TIMEOUT_MS  default 300000, per openai-compatible reviewer
 *
 * Output: {reviewer:{kind:'external-review-script', mode:'multi'}, configured,
 *   artifactSha256, votes:[vote | {name, __error} | {name, skipped}]}.
 *   configured = at least one reviewer applies to this artifact. Exit 0 once
 *   the config parsed: a failed reviewer is one __error entry, never a lost
 *   panel.
 *
 * Flags:
 *   --type spec|plan|diff   what the artifact is (default diff)
 *   --target <desc>         required: the range/path + pinned SHA the caller is
 *                           reviewing, echoed back so the run is bound to the
 *                           same artifact as the rest of the panel
 *   --cwd <repo> / --range <ref>...HEAD   for codex reviewers (diffs)
 *   --focus <note>          optional in-scope note
 *   --out-of-scope <note>   optional exclusions
 *   --allow-same-family     permit a Claude model (defeats cross-family review)
 *   --only <name>           run only the configured reviewer with this name
 *                           (repeatable); an unknown name exits 1
 *   --list                  print {names:[...]} of the configured reviewers and
 *                           exit (no stdin, no --target)
 *
 * Exit codes: 0 ok · 1 usage/config error
 */

import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defaultCompanion } from './codex-review.mjs'

const CODEX_SCRIPT = fileURLToPath(new URL('./codex-review.mjs', import.meta.url))

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
  const opts = { type: 'diff', target: '', cwd: '', range: '', focus: '', outOfScope: '', allowSameFamily: false, only: [], list: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => {
      if (i + 1 >= argv.length) fail(1, `${a} requires a value`)
      return argv[++i]
    }
    if (a === '--type') opts.type = next()
    else if (a === '--target') opts.target = next()
    else if (a === '--cwd') opts.cwd = next()
    else if (a === '--range') opts.range = next()
    else if (a === '--focus') opts.focus = next()
    else if (a === '--out-of-scope') opts.outOfScope = next()
    else if (a === '--allow-same-family') opts.allowSameFamily = true
    else if (a === '--only') opts.only.push(next())
    else if (a === '--list') opts.list = true
    else fail(1, `unknown flag ${a}`)
  }
  if (opts.list) return opts
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

class ReviewError extends Error {
  constructor(code, message) {
    super(message)
    this.code = code
  }
}

export function isLoopback(hostname) {
  const h = hostname.replace(/^\[|\]$/g, '').toLowerCase()
  return h === 'localhost' || h === '::1' || /^127\.\d+\.\d+\.\d+$/.test(h)
}

// Resolves this machine's reviewer list. Throws ReviewError(1) on a config
// problem no reviewer could survive (bad JSON, unknown kind, duplicate names);
// per-reviewer problems (Claude model, bad URL, missing key) come back as
// `problem` so they are reported as one dropped vote each.
export function resolveReviewers(env, { allowSameFamily = false, codexAvailable = () => Boolean(defaultCompanion()) } = {}) {
  let specs
  const explicit = env.EXTERNAL_REVIEWERS !== undefined && env.EXTERNAL_REVIEWERS.trim() !== ''
  if (explicit) {
    try {
      specs = JSON.parse(env.EXTERNAL_REVIEWERS)
    } catch {
      throw new ReviewError(1, 'EXTERNAL_REVIEWERS is not valid JSON')
    }
    if (!Array.isArray(specs)) throw new ReviewError(1, 'EXTERNAL_REVIEWERS must be a JSON array ("[]" for none)')
  } else {
    specs = []
    if (env.EXTERNAL_REVIEW_MODEL) {
      specs.push({ kind: 'openai-compatible', model: env.EXTERNAL_REVIEW_MODEL, baseUrl: env.EXTERNAL_REVIEW_BASE_URL, apiKey: env.EXTERNAL_REVIEW_API_KEY })
    }
    if (codexAvailable()) specs.push({ name: 'codex', kind: 'codex' })
  }

  const seen = new Set()
  return specs.map((spec, i) => {
    if (!spec || typeof spec !== 'object') throw new ReviewError(1, `EXTERNAL_REVIEWERS[${i}] must be an object`)
    const kind = spec.kind || 'openai-compatible'
    if (kind !== 'openai-compatible' && kind !== 'codex') throw new ReviewError(1, `EXTERNAL_REVIEWERS[${i}] has unknown kind "${kind}" (expected openai-compatible | codex)`)
    const model = typeof spec.model === 'string' ? spec.model : ''
    const name = typeof spec.name === 'string' && spec.name ? spec.name : model || (kind === 'codex' ? 'codex' : `reviewer-${i}`)
    if (seen.has(name)) throw new ReviewError(1, `EXTERNAL_REVIEWERS has two reviewers named "${name}"; names must be unique`)
    seen.add(name)
    const r = { name, kind, model, family: typeof spec.family === 'string' ? spec.family : null, problem: null }
    if (kind === 'codex') {
      r.companion = typeof spec.companion === 'string' ? spec.companion : ''
      return r
    }
    r.baseUrl = spec.baseUrl || 'https://api.openai.com/v1'
    r.apiKey = spec.apiKey ?? (spec.apiKeyEnv ? env[spec.apiKeyEnv] || '' : '')
    if (!model) {
      r.problem = explicit ? `EXTERNAL_REVIEWERS[${i}] has no model` : 'EXTERNAL_REVIEW_MODEL is required'
      return r
    }
    if (/claude|anthropic/i.test(model) && !allowSameFamily) {
      r.problem = `"${model}" is a Claude-family model: it shares the panel's blind spots and adds no independence. Pick a different family, or pass --allow-same-family if you really mean it.`
      return r
    }
    try {
      r.host = new URL(r.baseUrl).hostname
    } catch {
      r.problem = `base URL is not a valid URL: "${r.baseUrl}"`
      return r
    }
    r.private = spec.private === true || isLoopback(r.host)
    if (!r.apiKey && !r.private) {
      r.problem = `no API key for ${r.host}: set apiKeyEnv, or "private": true if this endpoint runs on hardware you control`
    }
    return r
  })
}

// Narrows the resolved list to the --only names. Throws ReviewError(1) naming
// the configured reviewers when a requested one does not exist.
export function selectReviewers(reviewers, only) {
  if (!only.length) return reviewers
  const names = reviewers.map((r) => r.name)
  const unknown = only.filter((n) => !names.includes(n))
  if (unknown.length) {
    throw new ReviewError(1, `--only names no configured reviewer: ${unknown.map((n) => `"${n}"`).join(', ')} (configured: ${names.length ? names.join(', ') : 'none'})`)
  }
  return reviewers.filter((r) => only.includes(r.name))
}

// One openai-compatible reviewer, one review. Throws ReviewError(2) on API
// failure, (3) on an unusable response.
async function reviewOne(r, prompt, timeoutMs) {
  const baseBody = { model: r.model, messages: [{ role: 'user', content: prompt }] }
  let status, text
  try {
    ;({ status, text } = await callApi(r.baseUrl, r.apiKey, {
      ...baseBody,
      response_format: { type: 'json_schema', json_schema: { name: 'review', strict: true, schema: REVIEW_SCHEMA } },
    }, timeoutMs))

    // Some OpenAI-compatible servers reject response_format outright; retry once
    // with the schema inlined in the prompt instead.
    if (status === 400) {
      ;({ status, text } = await callApi(r.baseUrl, r.apiKey, {
        ...baseBody,
        messages: [{
          role: 'user',
          content: `${prompt}\n\nRespond with ONLY a JSON object matching this JSON Schema, no prose:\n${JSON.stringify(REVIEW_SCHEMA)}`,
        }],
      }, timeoutMs))
    }
  } catch (e) {
    throw new ReviewError(2, `request to ${r.host} failed: ${e.message}`)
  }
  if (status !== 200) throw new ReviewError(2, `API returned ${status} from ${r.host}: ${text.slice(0, 500)}`)

  let content
  try {
    content = JSON.parse(text).choices?.[0]?.message?.content
  } catch {
    throw new ReviewError(2, `API response from ${r.host} was not JSON: ${text.slice(0, 200)}`)
  }
  if (typeof content !== 'string' || !content) throw new ReviewError(3, `API response from ${r.host} had no message content`)

  const review = validate(extractJson(content))
  if (!review) throw new ReviewError(3, `model output did not match the findings schema: ${content.slice(0, 500)}`)
  return review
}

// Codex reviews the range itself (never stdin) and stamps its own digest over
// `git diff <range>`; its vote passes through unchanged for the workflow's
// digest gate.
function runCodex(r, opts) {
  const args = [CODEX_SCRIPT, '--cwd', opts.cwd, '--range', opts.range, '--target', opts.target]
  if (r.companion) args.push('--companion', r.companion)
  return new Promise((resolve) => {
    execFile(process.execPath, args, { maxBuffer: 64 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) return resolve({ name: r.name, __error: (stderr || err.message).toString().trim() })
      try {
        resolve({ ...JSON.parse(stdout), name: r.name })
      } catch {
        resolve({ name: r.name, __error: `codex-review printed no JSON: ${stdout.slice(0, 200)}` })
      }
    })
  })
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))

  let reviewers
  try {
    reviewers = resolveReviewers(process.env, { allowSameFamily: opts.allowSameFamily })
    if (opts.list) {
      process.stdout.write(JSON.stringify({ names: reviewers.map((r) => r.name) }) + '\n')
      return
    }
    reviewers = selectReviewers(reviewers, opts.only)
  } catch (e) {
    fail(e.code || 1, e.message)
  }

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

  // The digest pins exactly what was reviewed, so the caller can confirm this
  // vote covered the same bytes as the rest of the panel before folding it in.
  const vote = (r, review) => ({
    name: r.name,
    reviewer: { kind: 'external-review-script', name: r.name, model: r.model, endpoint: r.host, private: r.private, family: r.family || 'external' },
    target: opts.target,
    artifactType: opts.type,
    artifactSha256,
    verdict: review.verdict,
    findings: review.findings,
  })

  const votes = await Promise.all(reviewers.map(async (r) => {
    if (r.kind === 'codex') {
      if (opts.type !== 'diff') return { name: r.name, skipped: `not applicable to ${opts.type}` }
      if (!opts.cwd || !opts.range) return { name: r.name, __error: 'codex needs --cwd and --range' }
      return runCodex(r, opts)
    }
    if (r.problem) return { name: r.name, __error: r.problem }
    try {
      return vote(r, await reviewOne(r, prompt, timeoutMs))
    } catch (e) {
      return { name: r.name, __error: e.message }
    }
  }))
  process.stdout.write(JSON.stringify({
    reviewer: { kind: 'external-review-script', mode: 'multi' },
    configured: votes.some((v) => !v.skipped),
    target: opts.target,
    artifactType: opts.type,
    artifactSha256,
    votes,
  }, null, 2) + '\n')
}

// realpath both sides: the plugin cache and symlinked installs put argv[1]
// and import.meta.url on different spellings of the same file.
const invokedDirectly = (() => {
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
})()
if (invokedDirectly) await main()
