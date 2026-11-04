#!/usr/bin/env node
/**
 * Codex CLI reviewer for the adversarial-review workflow (DIFF ONLY).
 *
 * Drives the codex plugin's read-only app-server adapter with structured output,
 * adapts its review schema into the workflow's REVIEW_SCHEMA, and prints one JSON
 * object stamped `reviewer.kind: 'codex-review-script'` so the workflow can bind
 * this vote to the artifact and refuse to count a run that did not really happen.
 *
 * Binding is BY-DIGEST over an ENFORCED `<ref>...HEAD` range. Any other range is
 * refused rather than hashing bytes outside the review target. Base is derived
 * from the range's left side; there is no independent --base flag.
 *
 * The digest is sha256 over the exact bytes of `git -C <cwd> diff <range>`
 * (node:crypto, no deps), emitted as TOP-LEVEL `artifactSha256`, the same
 * contract external-review.mjs uses, so the workflow can compare it to the
 * caller-pinned expectedArtifactSha256.
 *
 * Usage:
 *   node codex-review.mjs --cwd <repo> --range <ref>...HEAD \
 *     [--model gpt-6.1-sol] [--effort high] \
 *     [--companion <path>] [--target "main...HEAD @ <sha>"]
 * Exit: 0 ok, 1 usage (including a refused range), 2 codex error or no
 *       usable companion, 3 unusable/non-conforming output
 */

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

// critical/high/medium/low (4) -> blocker/major/minor (3). medium and low both
// map to minor DELIBERATELY: the panel's scale has no fourth slot, and skeptic
// verify re-adjudicates every uncorroborated blocker/major, so this lossiness
// cannot bury a gating finding; it only flattens the non-gating tail. Tunable.
const SEVERITY_MAP = { critical: 'blocker', high: 'major', medium: 'minor', low: 'minor' }
// numeric confidence -> verified/speculative; >= 0.8 is "verified".
const VERIFIED_AT = 0.8
const DEFAULT_MODEL = 'gpt-6.1-sol'
const DEFAULT_EFFORT = 'high'
const EFFORTS = new Set(['none', 'minimal', 'low', 'medium', 'high', 'xhigh'])

const CODEX_REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'summary', 'findings', 'next_steps'],
  properties: {
    verdict: { enum: ['approve', 'needs-attention'] },
    summary: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['severity', 'title', 'body', 'file', 'line_start', 'line_end', 'confidence', 'recommendation'],
        properties: {
          severity: { enum: ['critical', 'high', 'medium', 'low'] },
          title: { type: 'string' },
          body: { type: 'string' },
          file: { type: 'string' },
          line_start: { type: 'integer' },
          line_end: { type: 'integer' },
          confidence: { type: 'number' },
          recommendation: { type: 'string' },
        },
      },
    },
    next_steps: { type: 'array', items: { type: 'string' } },
  },
}

export function sha256Hex(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

// The companion resolves its own review target from --base as
// merge-base(base, HEAD)...HEAD; only a range of the exact form <ref>...HEAD
// can coincide with that. Returns the base (the range's left side).
export function assertReviewableRange(range) {
  const m = /^(.+?)\.\.\.HEAD$/.exec(range || '')
  if (!m || m[1].includes('..')) {
    throw new Error(`--range must be <ref>...HEAD (the companion always reviews merge-base(base, HEAD)...HEAD, so no other range can be honestly hashed); got "${range}"`)
  }
  return m[1]
}

export function adaptCodexReview(codex) {
  if (!codex || (codex.verdict !== 'approve' && codex.verdict !== 'needs-attention')) {
    throw new Error(`codex output missing/invalid verdict: ${JSON.stringify(codex?.verdict)}`)
  }
  const findings = (Array.isArray(codex.findings) ? codex.findings : []).map((f) => {
    const severity = SEVERITY_MAP[f.severity]
    if (!severity) throw new Error(`unknown codex severity "${f.severity}"`)
    const loc = f.line_end && f.line_end !== f.line_start ? `${f.file}:${f.line_start}-${f.line_end}` : `${f.file}:${f.line_start}`
    return {
      objection: [f.title, f.body].filter(Boolean).join('. '),
      severity,
      confidence: typeof f.confidence === 'number' && f.confidence >= VERIFIED_AT ? 'verified' : 'speculative',
      location: loc,
      suggested_fix: f.recommendation || '',
    }
  })
  return { findings, verdict: { ship: codex.verdict === 'approve', reason: codex.summary || '' } }
}

// --- CLI (kept out of the tested adapter) ---

function fail(code, message) {
  process.stderr.write(`${message}\n`)
  process.exit(code)
}

// Newest installed companion under the plugin cache (version-sorted).
// CODEX_COMPANION_ROOT exists so tests can point at an empty dir and simulate
// a machine without the codex plugin. Returns null when none is installed;
// the caller exits 2 with the reason (this IS the availability report: v5
// dropped the discovery probe, so absence surfaces here, at tool run time).
export function defaultCompanion() {
  const root = process.env.CODEX_COMPANION_ROOT
    || join(homedir(), '.claude', 'plugins', 'cache', 'openai-codex', 'codex')
  let versions
  try {
    versions = readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)
  } catch {
    return null
  }
  const candidates = versions
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
    .map((v) => join(root, v, 'scripts', 'codex-companion.mjs'))
    .filter((p) => existsSync(p))
  return candidates.length ? candidates[candidates.length - 1] : null
}

function parseArgs(argv) {
  const opts = {}
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (!['--companion', '--cwd', '--range', '--target', '--model', '--effort'].includes(flag) || value === undefined) {
      fail(1, `usage: codex-review.mjs --cwd <repo> --range <ref>...HEAD [--model <model>] [--effort <effort>] [--companion <path>] [--target <label>] (got "${flag}")`)
    }
    opts[flag.slice(2)] = value
  }
  if (!opts.cwd || !opts.range) fail(1, 'usage: codex-review.mjs --cwd <repo> --range <ref>...HEAD [--model <model>] [--effort <effort>] [--companion <path>] [--target <label>]')
  opts.model ||= DEFAULT_MODEL
  opts.effort ||= DEFAULT_EFFORT
  if (!EFFORTS.has(opts.effort)) fail(1, `--effort must be one of ${[...EFFORTS].join(', ')}; got "${opts.effort}"`)
  return opts
}

function parseStructuredOutput(raw) {
  const text = String(raw || '').trim()
  try {
    return JSON.parse(text)
  } catch {
    const fenced = /^```(?:json)?\s*([\s\S]*?)\s*```$/.exec(text)
    if (fenced) return JSON.parse(fenced[1])
    throw new Error(`Codex returned no parseable JSON: ${text.slice(0, 400)}`)
  }
}

async function runStructuredReview(companion, opts) {
  const library = join(dirname(companion), 'lib', 'codex.mjs')
  if (!existsSync(library)) throw new Error(`Codex companion library not found: ${library}`)
  const { runAppServerTurn } = await import(pathToFileURL(library).href)
  if (typeof runAppServerTurn !== 'function') throw new Error(`Codex companion does not export runAppServerTurn: ${library}`)
  const prompt = `Review the code changes in ${opts.range} as an independent adversarial reviewer. Use git and read-only filesystem tools to inspect the diff and any context needed to verify behavior. Find concrete correctness, security, reliability, compatibility, and test gaps. Ignore style preferences with no consequence. Return findings only for changed behavior or regressions caused by this range.\n\nReview target: ${opts.target || `${opts.range} @ HEAD`}`
  const result = await runAppServerTurn(opts.cwd, {
    prompt,
    model: opts.model,
    effort: opts.effort,
    sandbox: 'read-only',
    outputSchema: CODEX_REVIEW_SCHEMA,
  })
  if (result.status !== 0) throw new Error(result.error?.message || result.stderr || 'Codex review failed')
  return parseStructuredOutput(result.finalMessage)
}

async function main() {
  const opts = parseArgs(process.argv.slice(2))

  let base
  try {
    base = assertReviewableRange(opts.range)
  } catch (err) {
    fail(1, err.message)
  }

  const companion = opts.companion || defaultCompanion()
  if (!companion) {
    fail(2, `codex companion not found: no */scripts/codex-companion.mjs under ${process.env.CODEX_COMPANION_ROOT || join(homedir(), '.claude', 'plugins', 'cache', 'openai-codex', 'codex')} (is the openai-codex plugin installed?)`)
  }

  let codex
  try {
    codex = await runStructuredReview(companion, opts)
  } catch (err) {
    fail(2, `codex run failed: ${err.message}`)
  }

  let review
  try {
    review = adaptCodexReview(codex)
  } catch (err) {
    fail(3, `Codex output does not conform to the review schema: ${err.message}`)
  }

  // Pin the vote to the exact diff bytes the workflow supplied. Codex can read
  // wider repository context, but findings must concern this range.
  const diffBytes = execFileSync('git', ['-C', opts.cwd, 'diff', opts.range], { maxBuffer: 64 * 1024 * 1024 })
  process.stdout.write(JSON.stringify({
    reviewer: { kind: 'codex-review-script', family: 'openai', model: opts.model, effort: opts.effort },
    target: opts.target || `${opts.range} @ HEAD`,
    artifactType: 'diff',
    artifactSha256: sha256Hex(diffBytes),
    // Audit metadata for the requested review range, never part of the digest gate.
    companionTarget: { mode: 'range', baseRef: base, summary: opts.range },
    verdict: review.verdict,
    findings: review.findings,
  }, null, 2) + '\n')
}

if (import.meta.url === `file://${process.argv[1]}`) await main()
