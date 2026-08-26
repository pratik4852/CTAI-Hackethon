export const TRADE_COLORS = {
  mechanical: 'var(--mech)',
  plumbing: 'var(--plumb)',
  electrical: 'var(--elec)',
  fire_protection: 'var(--fire)',
  architectural: 'var(--text-3)',
  unknown: 'var(--text-3)',
}

export const CATEGORY_COLORS = {
  square_supply_diffuser_4way: '#38bdf8',
  square_return_exhaust_register: '#34d399',
  round_supply_diffuser: '#22d3ee',
  linear_bar_grille: '#a78bfa',
  fire_damper: '#f87171',
  water_source_heat_pump: '#fbbf24',
  flexible_duct: '#f472b6',
  elevation_benchmark: '#94a3b8',
}

export const categoryColor = (key) => CATEGORY_COLORS[key] || '#818cf8'

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export const num = (v, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v)
    ? '—'
    : Number(v).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })

export const feet = (v) => (v ? `${num(v, 0)} ft` : '—')

export const pct = (v) => `${Math.round((v || 0) * 100)}%`

export const bytes = (n) => {
  if (!n) return '—'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`
}

export const timeAgo = (ts) => {
  if (!ts) return '—'
  const s = Math.max(1, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Minimal markdown: bold, inline code, bullet lists, paragraphs. */
export const renderMarkdown = (text) => {
  const esc = (s) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+?)`/g, '<code>$1</code>')
      .replace(/_(.+?)_/g, '<em>$1</em>')

  const lines = String(text || '').split('\n')
  const out = []
  let list = null
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    const m = line.match(/^\s*[-*]\s+(.*)$/)
    if (m) {
      if (!list) list = []
      list.push(`<li>${inline(m[1])}</li>`)
      continue
    }
    if (list) {
      out.push(`<ul>${list.join('')}</ul>`)
      list = null
    }
    if (line.trim()) out.push(`<p>${inline(line)}</p>`)
  }
  if (list) out.push(`<ul>${list.join('')}</ul>`)
  return out.join('')
}
