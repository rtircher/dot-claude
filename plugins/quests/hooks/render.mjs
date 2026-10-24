// Pure view model for the glance pane: quest log summary JSON in, sections out.
// No I/O and no platform API, so `node --test` can exercise it.

export const NEXT_SHOWN = 5

const BADGES = { waiting: 'waiting on you' }
// Badges that need the user's attention are drawn in the warning color.
const WARN_STATES = new Set(['idle', 'waiting'])

// The goal bar and row divider are SVG on graphical surfaces. Fixed colors
// with partial opacity read on both light and dark themes.
const ACCENT = '#3b82f6'
const TRACK = '#888888'

export function barSvg(fraction, width = 300, height = 6) {
  const f = Math.min(1, Math.max(0, fraction || 0))
  const fill = Math.round(f * width)
  const r = height / 2
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">` +
    `<rect width="${width}" height="${height}" rx="${r}" fill="${TRACK}" fill-opacity="0.25"/>` +
    (fill > 0 ? `<rect width="${fill}" height="${height}" rx="${r}" fill="${ACCENT}"/>` : '') +
    '</svg>'
  )
}

export function ruleSvg(width = 300) {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="1" viewBox="0 0 ${width} 1" preserveAspectRatio="none">` +
    `<rect width="${width}" height="1" fill="${TRACK}" fill-opacity="0.35"/></svg>`
  )
}

// The repo as people say it: the last path segment of a URL-ish name.
export function repoName(repo) {
  return String(repo || '').replace(/\.git$/, '').split('/').filter(Boolean).pop() || ''
}

function heading(title) {
  return title.toUpperCase()
}

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
      warn: WARN_STATES.has(s.state),
      isCurrent: s.session === current,
      chain: (s.chain || []).map((c, i, all) => ({
        id: c.id,
        title: c.title,
        text: i === 0 ? c.title : `› ${c.title}`,
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
      heading: heading(`Project · ${repoName(summary.repo)}`),
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
      heading: heading(`In progress · ${sessions.length} session${sessions.length === 1 ? '' : 's'}`),
      sessions,
    })
  }
  if (all.length) {
    sections.push({
      kind: 'next',
      title: 'Next up',
      heading: heading('Next up (unclaimed, unblocked)'),
      items: all.slice(0, NEXT_SHOWN),
      more: more > 0 ? `+${more} more` : null,
    })
  }
  const notice =
    summary.fetched === false ? 'The quest log is not fetched yet (remote unreachable). Try again when online.' : null
  return { unsynced: summary.synced === false, notice, sections: notice ? [] : sections }
}

export function ticketDetail(t) {
  const lines = [
    `${t.id}  ${t.title}`,
    `status: ${t.status}`,
    `main quest: ${t.goal || '-'}`,
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

// The one-line band above the prompt. Returns null when there is nothing to
// show. Only the next-up title is cut to fit `width`; when fewer than
// BAND_MIN_TITLE cells are left for it, the next-up part is dropped.
const BAND_MIN_TITLE = 8

export function bandText(summary, opts = {}) {
  if (!summary) return null
  if (summary.fetched === false) return 'Quests: not fetched yet (remote unreachable)'
  const n = (summary.sessions || []).length
  const head = `Quests: ${n ? `${n} in progress` : 'nothing in progress'}`
  const tail = summary.synced === false ? ' · unsynced' : ''
  const first = (summary.next || [])[0]
  if (!first) return `${head} · nothing ready${tail}`
  const lead = ' · next: '
  let title = first.title
  if (opts.width) {
    const room = opts.width - head.length - lead.length - tail.length
    if (room < BAND_MIN_TITLE) return head + tail
    if (title.length > room) title = title.slice(0, room - 1) + '…'
  }
  return head + lead + title + tail
}
