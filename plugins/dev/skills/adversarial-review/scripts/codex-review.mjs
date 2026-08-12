#!/usr/bin/env node
/**
 * Codex CLI reviewer for the adversarial-review workflow (DIFF ONLY).
 *
 * Drives the codex plugin's companion (read-only, structured output), adapts its
 * review-output schema into the workflow's REVIEW_SCHEMA, and prints one JSON
 * object stamped `reviewer.kind: 'codex-review-script'` so the workflow can bind
 * this vote to the artifact and refuse to count a run that did not really happen.
 *
 * Binding is BY-DIGEST over an ENFORCED range form: the companion always reviews
 * merge-base(base, HEAD)...HEAD (lib/git.mjs buildBranchComparison), so the only
 * range this wrapper can honestly hash is `<ref>...HEAD`. Any other range is
 * refused (exit 1) rather than hashed: hashing `git diff main..HEAD` or
 * `main...feature-x` while Codex reviews something else would make the digest
 * gate pass on bytes Codex never saw. Base is derived internally from the range
 * (its left side); there is deliberately NO independent --base flag.
 *
 * The digest is sha256 over the exact bytes of `git -C <cwd> diff <range>`
 * (node:crypto, no deps), emitted as TOP-LEVEL `artifactSha256`, the same
 * contract external-review.mjs uses, so the workflow can compare it to the
 * caller-pinned expectedArtifactSha256.
 *
 * Usage:
 *   node codex-review.mjs --cwd <repo> --range <ref>...HEAD \
 *     [--companion <path>] [--target "main...HEAD @ <sha>"]
 * Exit: 0 ok, 1 usage (including a refused range), 2 codex error or no
 *       usable companion, 3 unusable/non-conforming output
 */

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

// critical/high/medium/low (4) -> blocker/major/minor (3). medium and low both
// map to minor DELIBERATELY: the panel's scale has no fourth slot, and skeptic
// verify re-adjudicates every uncorroborated blocker/major, so this lossiness
// cannot bury a gating finding; it only flattens the non-gating tail. Tunable.
const SEVERITY_MAP = { critical: 'blocker', high: 'major', medium: 'minor', low: 'minor' }
// numeric confidence -> verified/speculative; >= 0.8 is "verified".
const VERIFIED_AT = 0.8

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
function defaultCompanion() {
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
    if (!['--companion', '--cwd', '--range', '--target'].includes(flag) || value === undefined) {
      fail(1, `usage: codex-review.mjs --cwd <repo> --range <ref>...HEAD [--companion <path>] [--target <label>] (got "${flag}")`)
    }
    opts[flag.slice(2)] = value
  }
  if (!opts.cwd || !opts.range) fail(1, 'usage: codex-review.mjs --cwd <repo> --range <ref>...HEAD [--companion <path>] [--target <label>]')
  return opts
}

function main() {
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

  // Foreground structured run: `adversarial-review --cwd <cwd> --base <base> --json`
  // prints execution.payload as JSON on stdout (codex-companion.mjs 628-639,
  // handleReviewCommand 682-723, dispatch 995-999); the parsed codex-schema
  // object lands in payload.result (executeReviewRun 415-438).
  let stdout
  try {
    stdout = execFileSync(process.execPath, [companion, 'adversarial-review', '--cwd', opts.cwd, '--base', base, '--json'], {
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    })
  } catch (err) {
    fail(2, `codex run failed: ${(err.stderr || '').toString().trim() || err.message}`)
  }

  let payload
  try {
    payload = JSON.parse(stdout)
  } catch {
    fail(3, `companion printed no parseable JSON: ${stdout.slice(0, 400)}`)
  }
  if (!payload.result) {
    fail(3, `companion returned no structured review object: ${payload.parseError || payload.codex?.stderr || 'payload.result missing'}`)
  }

  let review
  try {
    review = adaptCodexReview(payload.result)
  } catch (err) {
    fail(3, `companion output does not conform to the review schema: ${err.message}`)
  }

  // Binding checkpoint (Task 2 Step 5): OUTCOME 3. The companion does not
  // expose the exact context it reviewed (payload.context carries only
  // repoRoot/branch/summary, codex-companion.mjs 423-427), and the reviewed
  // content is NOT byte-identical to `git diff <range>`: it is markdown-wrapped
  // `git diff --binary --no-ext-diff --submodule=diff <mergeBase>..HEAD`
  // (lib/git.mjs collectBranchContext 261-289), or a stat-only summary with
  // self-collection when the diff exceeds maxInlineDiffBytes (collectReviewContext
  // 299-346, inputMode 'self-collect'). So we hash `git diff <range>` (the same
  // commit span: a three-dot diff IS the diff from merge-base(base, HEAD), the
  // range buildBranchComparison resolves, lib/git.mjs 68-75) and echo the
  // companion's RESOLVED target below so the caller can assert the range
  // identity; content-shape drift (flags, wrapping, truncation) is the
  // documented residual in the plan's self-review risks.
  const diffBytes = execFileSync('git', ['-C', opts.cwd, 'diff', opts.range], { maxBuffer: 64 * 1024 * 1024 })
  process.stdout.write(JSON.stringify({
    reviewer: { kind: 'codex-review-script', family: 'openai', model: null },
    target: opts.target || `${opts.range} @ HEAD`,
    artifactType: 'diff',
    artifactSha256: sha256Hex(diffBytes),
    // Audit metadata: the companion's own resolved review target, for the
    // outcome-3 binding assertion (never part of the digest gate).
    companionTarget: {
      mode: payload.target?.mode ?? null,
      baseRef: payload.target?.baseRef ?? null,
      summary: payload.context?.summary ?? null,
    },
    verdict: review.verdict,
    findings: review.findings,
  }, null, 2) + '\n')
}

if (import.meta.url === `file://${process.argv[1]}`) main()
