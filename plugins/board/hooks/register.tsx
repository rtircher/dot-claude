import type { Register } from 'claude-code'

import { renderGlance, textBar, ticketDetail, goalTickets, fileLink } from './render.mjs'

const PANE = 'board-glance'
const POLL_MS = 30_000

// Pane-local state. Lives for one load of the module; the board itself is
// always re-read through the CLI.
let summaryNow: any = null // last good summary
let noBoard = false
let note: string | null = null // stale / busy note shown over the last good view
let sessionId = ''
let detail: string[] | null = null
let fullBoard: string | null = null
let inFlight = false
let timer: { cancel: () => void } | null = null
const expanded = new Set<string>()

function redraw($: any) {
  $.ui.invalidate('ui.render')
}

async function board($: any, args: string[]) {
  const cwd = await $.session.cwd()
  return $.process.run([`${$.plugin.root}/bin/board`, ...args], { cwd, timeoutMs: 20_000 })
}

async function refresh($: any) {
  if (inFlight) return
  inFlight = true
  try {
    sessionId = sessionId || (await $.session.id())
    // Goals are expanded from the full ready list; otherwise the default 5.
    const limit = expanded.size > 0 ? '100' : '5'
    const r = await board($, ['summary', '--json', '--next-limit', limit, '--session', sessionId])
    if (r.exitCode === 2) {
      noBoard = true
      summaryNow = null
      note = null
    } else if (r.exitCode === 5) {
      noBoard = false
      note = summaryNow ? 'busy: showing the last view' : 'busy, try again shortly'
    } else if (r.exitCode !== 0) {
      noBoard = false
      const why = (r.stderr || r.stdout || 'board failed').trim().split('\n')[0]
      note = summaryNow ? `stale: ${why}` : `Board unavailable: ${why}`
    } else {
      noBoard = false
      summaryNow = JSON.parse(r.stdout)
      note = null
    }
  } catch (err: any) {
    const why = String(err?.message || err).split('\n')[0]
    note = summaryNow ? `stale: ${why}` : `Board unavailable: ${why}`
  } finally {
    inFlight = false
  }
  redraw($)
}

async function openPane($: any) {
  await $.ui.open({ id: PANE, title: 'Board' })
  // Poll only while the pane is open; ui.close stops it.
  if (!timer) timer = $.clock.every(POLL_MS, () => refresh($))
  void refresh($)
}

async function showTicket($: any, id: string) {
  try {
    const r = await board($, ['show', id, '--json'])
    detail = r.exitCode === 0 ? ticketDetail(JSON.parse(r.stdout)) : [`Could not load ${id}`]
  } catch {
    detail = [`Could not load ${id}`]
  }
  redraw($)
}

async function openFull($: any) {
  try {
    const r = await board($, ['html', '--json'])
    const path = r.exitCode === 0 ? JSON.parse(r.stdout).path : null
    fullBoard = path ? `[Open the full board](${fileLink(path)})` : 'Could not build the full board page.'
  } catch {
    fullBoard = 'Could not build the full board page.'
  }
  redraw($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'board', description: 'Show the board at a glance in a pane' })
    return next(e)
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && timer) {
      timer.cancel()
      timer = null
    }
    return next(e)
  })

  on('command.run', { command: 'board' }, async $ => {
    await openPane($)
    return { text: 'Board pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown } = $.ui.resolve(e)

    if (noBoard) return <Text dimColor>No board for this repo. Ask Claude to set up a board.</Text>
    if (!summaryNow) return <Text dimColor>{note || 'Loading the board...'}</Text>

    const summary = summaryNow
    const vm = renderGlance(summary, { currentSession: sessionId })

    if (detail) {
      return (
        <Box flexDirection="column">
          <Button key="back" onPress={() => { detail = null; redraw($) }}>Back</Button>
          {detail.map((l, i) => <Text key={`d${i}`}>{l}</Text>)}
        </Box>
      )
    }

    return (
      <Box flexDirection="column">
        {note && <Text dimColor>{note}</Text>}
        {vm.notice && <Text dimColor>{vm.notice}</Text>}
        {vm.unsynced && !vm.notice && <Text dimColor>unsynced: showing the last known board</Text>}
        {vm.sections.map(sec => {
          if (sec.kind === 'project') {
            return (
              <Box key="project" flexDirection="column">
                <Text bold>{sec.title}</Text>
                {sec.bars.map(b => (
                  <Box key={`g-${b.id}`} flexDirection="column">
                    <Button
                      key={`goal-${b.id}`}
                      onPress={() => { expanded.has(b.id) ? expanded.delete(b.id) : expanded.add(b.id); redraw($); void refresh($) }}
                    >
                      {b.title} {textBar(b.fraction)} {b.label}
                    </Button>
                    {expanded.has(b.id) && (
                      goalTickets(summary, b.id).length === 0
                        ? <Text dimColor>  no ready tickets in this goal</Text>
                        : goalTickets(summary, b.id).map((t: any) => (
                            <Button key={`gt-${t.id}`} onPress={() => showTicket($, t.id)}>  {t.id}  {t.title}</Button>
                          ))
                    )}
                  </Box>
                ))}
              </Box>
            )
          }
          if (sec.kind === 'sessions') {
            return (
              <Box key="sessions" flexDirection="column">
                <Text bold>{sec.title}</Text>
                {sec.sessions.map(s => (
                  <Box key={`s-${s.session}`} flexDirection="column">
                    <Text>{s.label} [{s.badge}]</Text>
                    {s.chain.map(c => (
                      <Button key={`c-${s.session}-${c.id}`} onPress={() => showTicket($, c.id)}>
                        <Text dimColor={c.muted} bold={c.current}>{'  '}{c.id}  {c.title}</Text>
                      </Button>
                    ))}
                  </Box>
                ))}
              </Box>
            )
          }
          return (
            <Box key="next" flexDirection="column">
              <Text bold>{sec.title}</Text>
              {sec.items.map(t => (
                <Button key={`n-${t.id}`} onPress={() => showTicket($, t.id)}>{t.id}  {t.title}</Button>
              ))}
              {sec.more && <Text dimColor>{sec.more}</Text>}
            </Box>
          )
        })}
        <Button key="full" onPress={() => openFull($)}>Full board</Button>
        {fullBoard && <Markdown text={fullBoard} />}
      </Box>
    )
  })
}
