import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderGlance, textBar, barSvg, repoName, ruleSvg, ticketDetail, goalTickets, fileLink, bandText, moveArgs, MOVES } from './render.mjs'

const next = (n) =>
  Array.from({ length: n }, (_, i) => ({ id: `t${i + 1}`, title: `Example task ${i + 1}`, goal: 'g1' }))

const fixture = () => ({
  repo: 'example/project',
  synced: true,
  goals: [
    { id: 'g1', title: 'Example goal', done: 2, total: 5 },
    { id: 'g2', title: 'Set up backups', done: 0, total: 0 },
  ],
  sessions: [
    { session: 'other', label: 'alpha', where: 'laptop', state: 'idle', chain: [{ id: 'a', title: 'A' }] },
    {
      session: 'me',
      label: 'beta',
      where: 'laptop',
      state: 'waiting',
      chain: [
        { id: 'p', title: 'Parent' },
        { id: 'c', title: 'Child' },
      ],
    },
    { session: 'far', label: 'gamma', where: 'cloud', state: 'remote', chain: [{ id: 'r', title: 'R' }] },
  ],
  next: next(5),
  next_more: 3,
  stale: [],
})

test('sections come in the approved order', () => {
  const vm = renderGlance(fixture(), { currentSession: 'me' })
  assert.deepEqual(vm.sections.map((s) => s.kind), ['project', 'sessions', 'next'])
  assert.equal(vm.sections[0].title, 'Project · example/project')
  assert.equal(vm.sections[1].title, 'In progress · 3 sessions')
  assert.equal(vm.sections[2].title, 'Next up')
})

test('one bar per goal with done/total and a fraction', () => {
  const [p] = renderGlance(fixture(), {}).sections
  assert.equal(p.bars.length, 2)
  assert.equal(p.bars[0].label, '2/5')
  assert.equal(p.bars[0].fraction, 0.4)
  assert.equal(p.bars[1].fraction, 0)
  assert.equal(textBar(0.5, 10), '█'.repeat(5) + '░'.repeat(5))
})

test('8 ready items show 5 and +3 more', () => {
  const s = fixture()
  s.next = next(5)
  s.next_more = 3
  const nx = renderGlance(s, {}).sections[2]
  assert.equal(nx.items.length, 5)
  assert.equal(nx.more, '+3 more')
  const raw = fixture()
  raw.next = next(8)
  raw.next_more = 0
  const nx2 = renderGlance(raw, {}).sections[2]
  assert.equal(nx2.items.length, 5)
  assert.equal(nx2.more, '+3 more')
})

test('current session first, badges, chain emphasis', () => {
  const ss = renderGlance(fixture(), { currentSession: 'me' }).sections[1].sessions
  assert.deepEqual(ss.map((x) => x.label), ['beta', 'alpha', 'gamma'])
  assert.deepEqual(ss.map((x) => x.badge), ['waiting on you', 'idle', 'remote'])
  assert.deepEqual(ss[0].chain.map((c) => [c.id, c.muted, c.current]), [
    ['p', true, false],
    ['c', false, true],
  ])
})

test('unsynced badge only when synced is false', () => {
  assert.equal(renderGlance(fixture(), {}).unsynced, false)
  const s = fixture()
  s.synced = false
  assert.equal(renderGlance(s, {}).unsynced, true)
})

test('empty sessions and next sections are omitted', () => {
  const s = fixture()
  s.sessions = []
  s.next = []
  s.next_more = 0
  assert.deepEqual(renderGlance(s, {}).sections.map((x) => x.kind), ['project'])
})

test('ticket detail lists fields and log lines', () => {
  const lines = ticketDetail({
    id: 't1', title: 'Example task', status: 'todo', goal: 'g1', parent: null,
    owner: { label: 'beta', where: 'laptop' }, links: ['https://example.invalid/x'],
    log: [{ at: '2026-01-01T00:00:00Z', session: 's', text: 'created' }],
  })
  assert.equal(lines[0], 't1  Example task')
  assert.ok(lines.includes('status: todo'))
  assert.ok(lines.includes('owner: beta (laptop)'))
  assert.ok(lines.some((l) => l.includes('created')))
})

test('not fetched yet gives a hint and no sections', () => {
  const vm = renderGlance({ repo: 'example/project', synced: false, fetched: false }, {})
  assert.deepEqual(vm.sections, [])
  assert.equal(vm.unsynced, true)
  assert.match(vm.notice, /not fetched/)
  assert.equal(renderGlance(fixture(), {}).notice, null)
})

test('missing goals still render a project section', () => {
  const vm = renderGlance({ repo: 'x', synced: true }, {})
  assert.deepEqual(vm.sections.map((s) => s.kind), ['project'])
  assert.deepEqual(vm.sections[0].bars, [])
})

test('goalTickets filters ready items by goal', () => {
  const s = fixture()
  s.next = [...next(3), { id: 'z', title: 'Other', goal: 'g2' }]
  assert.deepEqual(goalTickets(s, 'g2').map((t) => t.id), ['z'])
  assert.equal(goalTickets(s, 'g1').length, 3)
})

test('fileLink escapes parentheses and spaces', () => {
  assert.equal(fileLink('/a b/c(1).html'), 'file:///a%20b/c%281%29.html')
})

test('sections carry small uppercase headings', () => {
  const vm = renderGlance(fixture(), { currentSession: 'me' })
  assert.deepEqual(vm.sections.map((s) => s.heading), [
    'PROJECT · PROJECT',
    'IN PROGRESS · 3 SESSIONS',
    'NEXT UP (UNCLAIMED, UNBLOCKED)',
  ])
})

test('idle and waiting badges are flagged for the warning color', () => {
  const ss = renderGlance(fixture(), { currentSession: 'me' }).sections[1].sessions
  assert.deepEqual(ss.map((x) => [x.badge, x.warn]), [
    ['waiting on you', true],
    ['idle', true],
    ['remote', false],
  ])
})

test('side-quest chain items after the first get a chevron', () => {
  const ss = renderGlance(fixture(), { currentSession: 'me' }).sections[1].sessions
  assert.deepEqual(ss[0].chain.map((c) => c.text), ['Parent', '› Child'])
})

test('barSvg fills the accent rect to the fraction and clamps', () => {
  assert.match(barSvg(0.5, 300, 6), /<rect width="150" height="6" rx="3" fill="#3b82f6"\/>/)
  assert.match(barSvg(2, 300, 6), /<rect width="300" height="6" rx="3" fill="#3b82f6"\/>/)
  assert.doesNotMatch(barSvg(0, 300, 6), /#3b82f6/)
  assert.match(barSvg(0.4), /^<svg [^>]*preserveAspectRatio="none"/)
})

test('ruleSvg is one pixel tall', () => {
  assert.match(ruleSvg(), /height="1"/)
})

test('repoName keeps the last path segment', () => {
  assert.equal(repoName('example.invalid/someone/project'), 'project')
  assert.equal(repoName('git@example.invalid:someone/project.git'), 'project')
  assert.equal(repoName(undefined), '')
})

test('band: counts in-progress sessions and names the first next-up ticket', () => {
  assert.equal(bandText(fixture()), 'Quests: 3 in progress · next: Example task 1')
  const one = fixture()
  one.sessions = one.sessions.slice(0, 1)
  assert.equal(bandText(one), 'Quests: 1 in progress · next: Example task 1')
})

test('band: says so when nothing is in progress or ready', () => {
  const s = fixture()
  s.sessions = []
  s.next = []
  s.next_more = 0
  assert.equal(bandText(s), 'Quests: nothing in progress · nothing ready')
})

test('band: flags an unsynced quest log', () => {
  const s = fixture()
  s.synced = false
  assert.equal(bandText(s), 'Quests: 3 in progress · next: Example task 1 · unsynced')
})

test('band: a quest log not fetched yet says only that', () => {
  const s = fixture()
  s.fetched = false
  assert.equal(bandText(s), 'Quests: not fetched yet (remote unreachable)')
})

test('band: hidden without a summary', () => {
  assert.equal(bandText(null), null)
  assert.equal(bandText(undefined), null)
})

test('band: the next-up title is cut to fit the width, the rest stays whole', () => {
  const s = fixture()
  s.next = [{ id: 't1', title: 'A very long ticket title that will not fit', goal: 'g1' }]
  s.synced = false
  const text = bandText(s, { width: 50 })
  assert.equal(text.length, 50)
  assert.ok(text.startsWith('Quests: 3 in progress · next: A very'))
  assert.ok(text.endsWith('… · unsynced'))
  // Too narrow for any title: drop the next-up part rather than show a stub.
  assert.equal(bandText(s, { width: 35 }), 'Quests: 3 in progress · unsynced')
  // No width: never cut.
  assert.ok(bandText(s).includes('will not fit'))
})

test('moveArgs builds the quest and main quest move commands', () => {
  assert.deepEqual(MOVES.map((m) => m.dir), ['top', 'up', 'down', 'bottom'])
  assert.deepEqual(MOVES.map((m) => m.label), ['Top', 'Up', 'Down', 'Bottom'])
  assert.deepEqual(moveArgs('quest', 't-1', 'top'), ['move', 't-1', '--top'])
  assert.deepEqual(moveArgs('main', 'g-1', 'down'), ['main', 'move', 'g-1', '--down'])
  assert.throws(() => moveArgs('quest', 't-1', 'sideways'))
})

test('a too-new log shows its message and not the unsynced warning', () => {
  const vm = renderGlance({ ...fixture(), synced: false, format_error: 'needs a newer plugin' })
  assert.equal(vm.formatError, 'needs a newer plugin')
  assert.equal(vm.unsynced, false)
  assert.equal(renderGlance(fixture()).formatError, null)
})
