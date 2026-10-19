import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const root = join(import.meta.dirname, '..')
const plugin = JSON.parse(readFileSync(join(root, '.claude-plugin/plugin.json'), 'utf8')).name
const skills = readdirSync(join(root, 'skills')).map(dir => {
  const head = readFileSync(join(root, 'skills', dir, 'SKILL.md'), 'utf8')
  return head.match(/^name:\s*(\S+)/m)[1]
})
const registered = [...readFileSync(join(import.meta.dirname, 'register.tsx'), 'utf8')
  .matchAll(/command\.register\(\{\s*name:\s*'([^']+)'/g)].map(m => m[1])

test('register.tsx registers the /board pane command', () => {
  assert.deepEqual(registered, ['board'])
})

// A skill named after its plugin takes the bare /<plugin> name, and the engine
// then refuses $.command.register for it ("it is the plugin's /board:board").
test('no skill shares the plugin name, so the bare command stays free', () => {
  assert.ok(!skills.includes(plugin), `a skill named "${plugin}" shadows /${plugin}`)
})

