import type { Register } from 'claude-code'

import { renderGlance, textBar, barSvg, ruleSvg, ticketDetail, goalTickets, fileLink, bandText } from './render.mjs'

const PANE = 'board-glance'
const POLL_MS = 30_000
// The band above the prompt polls slower and for the whole session.
const BAND_POLL_MS = 60_000
// Cells the band's [ Open ] button and the gap before it take.
const BAND_BUTTON_CELLS = 10

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
let bandTimer: { cancel: () => void } | null = null
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
    // Feed the band first, so a refused command cannot leave it empty; the
    // refresh is never awaited, so the prompt is not held up.
    if (!bandTimer) bandTimer = $.clock.every(BAND_POLL_MS, () => refresh($))
    void refresh($)
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

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // Hidden in a repo without a board, before the first summary, and while a
    // survey holds the band.
    if (e.props.hasSurvey || noBoard) return next(e)
    const width = Math.max(0, e.props.bodyColumns - BAND_BUTTON_CELLS)
    const text = bandText(summaryNow, { width })
    if (!text) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e) as any
    return (
      <Box flexDirection="row" gap={1}>
        <Text dimColor wrap="truncate-end">{text}</Text>
        <Button key="board-open" label="Open" onPress={() => openPane($)} />
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown, Svg } = $.ui.resolve(e) as any
    // Graphical surfaces (desktop, mobile) take type sizes, weights and SVG;
    // the terminal gets text bars and bold, which every engine accepts.
    const gfx = e.surface !== 'terminal' && Boolean(Svg)
    const small = gfx ? { size: 'caption' } : {}
    const note2 = gfx ? { size: 'footnote' } : {}
    const count = gfx ? { size: 'footnote', tabular: true } : {}
    const strong = gfx ? { weight: 'semibold' } : { bold: true }
    const heading = (key: string, text: string) => (
      <Text key={key} {...small} {...strong} dimColor>{text}</Text>
    )
    const rule = (key: string) => gfx && <Svg key={key} source={ruleSvg()} alt="" height={1} />

    if (noBoard) return <Text dimColor>No board for this repo. Ask Claude to set up a board.</Text>
    if (!summaryNow) return <Text dimColor>{note || 'Loading the board...'}</Text>

    const summary = summaryNow
    const vm = renderGlance(summary, { currentSession: sessionId })

    if (detail) {
      const [head, ...rest] = detail
      return (
        <Box flexDirection="column" gap={1}>
          <Button key="back" onPress={() => { detail = null; redraw($) }}>Back</Button>
          <Text {...strong}>{head}</Text>
          <Box flexDirection="column">
            {rest.map((l, i) => <Text key={`d${i}`} {...note2} dimColor={l.startsWith('  ')}>{l}</Text>)}
          </Box>
        </Box>
      )
    }

    const toggleGoal = (id: string) => {
      expanded.has(id) ? expanded.delete(id) : expanded.add(id)
      redraw($)
      void refresh($)
    }

    return (
      <Box flexDirection="column" gap={2}>
        {(note || vm.notice || vm.unsynced) && (
          <Box flexDirection="column">
            {note && <Text {...note2} dimColor>{note}</Text>}
            {vm.notice && <Text {...note2} dimColor>{vm.notice}</Text>}
            {vm.unsynced && !vm.notice && <Text {...note2} color="warning">unsynced: showing the last known board</Text>}
          </Box>
        )}
        {vm.sections.map(sec => {
          if (sec.kind === 'project') {
            return (
              <Box key="project" flexDirection="column" gap={1}>
                {heading('project-h', sec.heading)}
                {sec.bars.map(b => (
                  <Box key={`g-${b.id}`} flexDirection="column">
                    <Box flexDirection="row" justifyContent="space-between" gap={1}>
                      <Box flexGrow={1} flexShrink={1} minWidth={0}>
                        <Button key={`goal-${b.id}`} plain label={b.title} onPress={() => toggleGoal(b.id)} />
                      </Box>
                      <Box flexShrink={0}>
                        <Text {...count} dimColor>{b.label}</Text>
                      </Box>
                    </Box>
                    {gfx
                      ? <Svg source={barSvg(b.fraction)} alt={`${b.title}: ${b.label} done`} height={6} />
                      : <Text color="suggestion">{textBar(b.fraction)}</Text>}
                    {expanded.has(b.id) && (
                      <Box flexDirection="column" paddingLeft={2} marginTop={1}>
                        {goalTickets(summary, b.id).length === 0
                          ? <Text {...note2} dimColor>no ready tickets in this goal</Text>
                          : goalTickets(summary, b.id).map((t: any) => (
                              <Button key={`gt-${t.id}`} plain dimColor label={t.title} onPress={() => showTicket($, t.id)} />
                            ))}
                      </Box>
                    )}
                  </Box>
                ))}
              </Box>
            )
          }
          if (sec.kind === 'sessions') {
            return (
              <Box key="sessions" flexDirection="column" gap={1}>
                {heading('sessions-h', sec.heading)}
                {sec.sessions.map((s, si) => (
                  <Box key={`s-${s.session}`} flexDirection="column" gap={1}>
                    {si > 0 && rule(`sr-${s.session}`)}
                    <Box flexDirection="row" justifyContent="space-between" gap={1}>
                      <Text {...small} {...strong} color="suggestion">{s.label}</Text>
                      {s.warn
                        ? <Text {...small} color="warning">{s.badge}</Text>
                        : <Text {...small} dimColor>{s.badge}</Text>}
                    </Box>
                    <Box flexDirection="row" gap={1}>
                      <Box width={1} backgroundColor="suggestion" />
                      <Box flexDirection="column">
                        {s.chain.map(c =>
                          gfx && c.current
                            ? (
                                <Button key={`c-${s.session}-${c.id}`} plain label={c.text} onPress={() => showTicket($, c.id)}>
                                  <Text weight="semibold">{c.text}</Text>
                                </Button>
                              )
                            : <Button key={`c-${s.session}-${c.id}`} plain dimColor={c.muted} label={c.text} onPress={() => showTicket($, c.id)} />,
                        )}
                      </Box>
                    </Box>
                  </Box>
                ))}
              </Box>
            )
          }
          return (
            <Box key="next" flexDirection="column" gap={1}>
              {heading('next-h', sec.heading)}
              {sec.items.map((t, i) => (
                <Box key={`n-${t.id}`} flexDirection="column" gap={1}>
                  {i > 0 && rule(`nr-${t.id}`)}
                  <Button key={`nb-${t.id}`} plain label={t.title} onPress={() => showTicket($, t.id)} />
                </Box>
              ))}
              {sec.more && rule('nr-more')}
              {sec.more && <Text {...note2} dimColor>{sec.more}</Text>}
            </Box>
          )
        })}
        <Box flexDirection="column" gap={1}>
          <Box flexDirection="row">
            <Button key="full" onPress={() => openFull($)}>Full board</Button>
          </Box>
          {fullBoard && <Markdown text={fullBoard} />}
        </Box>
      </Box>
    )
  })
}
