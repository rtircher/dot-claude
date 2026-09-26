import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// A plugin-shipped workflow registers as `<plugin>:<meta.name>`, so a nested
// workflow('<bare meta.name>') call fails with "no workflow with that name".
const DIR = dirname(fileURLToPath(import.meta.url))
const PLUGIN = basename(dirname(DIR))
const scripts = readdirSync(DIR).filter((f) => f.endsWith('.js'))
const src = Object.fromEntries(scripts.map((f) => [f, readFileSync(join(DIR, f), 'utf8')]))

const registered = new Set(
  scripts.map((f) => {
    const m = src[f].match(/export const meta = \{[\s\S]*?\bname:\s*'([^']+)'/)
    assert.ok(m, `${f}: no meta.name`)
    return `${PLUGIN}:${m[1]}`
  }),
)

test('nested workflow() calls use the namespaced name of a sibling workflow', () => {
  const calls = scripts.flatMap((f) =>
    [...src[f].matchAll(/\bworkflow\(\s*'([^']+)'/g)].map((m) => ({ f, name: m[1] })),
  )
  assert.ok(calls.length > 0, 'expected at least one nested workflow() call')
  for (const { f, name } of calls) {
    assert.ok(registered.has(name), `${f}: workflow('${name}') is not one of ${[...registered].join(', ')}`)
  }
})
