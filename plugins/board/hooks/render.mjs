// Pure view model for the glance pane: board summary JSON in, sections out.
// No I/O and no platform API, so `node --test` can exercise it.

export const NEXT_SHOWN = 5

const BADGES = { waiting: 'waiting on you' }

export function textBar(fraction, width = 12) {
  const f = Math.min(1, Math.max(0, fraction || 0))
  const filled = Math.round(f * width)
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

export function renderGlance(summary, opts = {}) {
  const current = opts.currentSession
  const goals = summary.goals || []
  const sessions = (summary.sessions || [])
    .map((s, i) => ({ s, i }))
    .sort((a, b) => (b.s.session === current) - (a.s.session === current) || a.i - b.i)
    .map(({ s }) => ({
      session: s.session,
      label: s.label,
      where: s.where,
      badge: BADGES[s.state] || s.state,
      isCurrent: s.session === current,
      chain: (s.chain || []).map((c, i, all) => ({
        id: c.id,
        title: c.title,
        current: i === all.length - 1,
        muted: i < all.length - 1,
      })),
    }))
  const all = summary.next || []
  const more = (summary.next_more || 0) + Math.max(0, all.length - NEXT_SHOWN)

  const sections = [
    {
      kind: 'project',
      title: `Project · ${summary.repo || ''}`,
      bars: goals.map((g) => ({
        id: g.id,
        title: g.title,
        done: g.done,
        total: g.total,
        fraction: g.total > 0 ? g.done / g.total : 0,
        label: `${g.done}/${g.total}`,
      })),
    },
  ]
  if (sessions.length) {
    sections.push({
      kind: 'sessions',
      title: `In progress · ${sessions.length} session${sessions.length === 1 ? '' : 's'}`,
      sessions,
    })
  }
  if (all.length) {
    sections.push({
      kind: 'next',
      title: 'Next up',
      items: all.slice(0, NEXT_SHOWN),
      more: more > 0 ? `+${more} more` : null,
    })
  }
  const notice =
    summary.fetched === false ? 'The board is not fetched yet (remote unreachable). Try again when online.' : null
  return { unsynced: summary.synced === false, notice, sections: notice ? [] : sections }
}

export function ticketDetail(t) {
  const lines = [
    `${t.id}  ${t.title}`,
    `status: ${t.status}`,
    `goal: ${t.goal || '-'}`,
    `parent: ${t.parent || '-'}`,
    'owner: ' + (t.owner ? `${t.owner.label} (${t.owner.where})` : '-'),
  ]
  if (t.links && t.links.length) lines.push('links: ' + t.links.join(', '))
  for (const e of t.log || []) lines.push(`  ${e.at} ${e.text}`)
  return lines
}

export function goalTickets(summary, goalId) {
  return (summary.next || []).filter((t) => t.goal === goalId)
}

export function fileLink(path) {
  return 'file://' + encodeURI(path).replace(/[()]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())
}
