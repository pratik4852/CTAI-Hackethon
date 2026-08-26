import React, { useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { exportUrl, useResultFullQuery } from '../store/api'
import { setPage } from '../store/uiSlice'
import { focusOn, selectRun } from '../store/viewerSlice'
import EmptyState from '../components/EmptyState'
import { num } from '../lib/format'

const TABS = [
  { id: 'components', label: 'Components' },
  { id: 'runs', label: 'Duct & pipe runs' },
  { id: 'boq', label: 'Bill of quantities' },
]

export default function Quantities() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { documentId } = useSelector((s) => s.ui)
  const { data, isFetching } = useResultFullQuery(documentId, { skip: !documentId })
  const [tab, setTab] = useState('components')
  const [q, setQ] = useState('')
  const [sheetFilter, setSheetFilter] = useState('')

  const sheets = data?.sheets || []

  const componentRows = useMemo(() => {
    const rows = []
    for (const s of sheets) {
      if (sheetFilter && s.sheet_label !== sheetFilter) continue
      for (const c of s.counts || []) {
        rows.push({ ...c, sheet: s.sheet_label, discipline: s.discipline_label })
      }
    }
    return rows.filter((r) => !q || r.category.toLowerCase().includes(q.toLowerCase()))
  }, [sheets, q, sheetFilter])

  const runRows = useMemo(() => {
    const rows = []
    for (const s of sheets) {
      if (sheetFilter && s.sheet_label !== sheetFilter) continue
      for (const r of s.linear?.runs || []) {
        rows.push({ ...r, sheet: s.sheet_label, page: s.page_number })
      }
    }
    const filtered = rows.filter(
      (r) =>
        !q ||
        `${r.size_label} ${r.service_name} ${r.kind}`.toLowerCase().includes(q.toLowerCase())
    )
    return filtered.sort((a, b) => b.length_ft - a.length_ft).slice(0, 800)
  }, [sheets, q, sheetFilter])

  const boqRows = useMemo(() => {
    const items = new Map()
    for (const s of sheets) {
      if (sheetFilter && s.sheet_label !== sheetFilter) continue
      for (const c of s.counts || []) {
        const key = `count|${c.category}`
        const row = items.get(key) || {
          section: c.category_group || 'Components',
          description: c.category,
          unit: c.unit || 'EA',
          size: '',
          quantity: 0,
          sheets: new Set(),
        }
        row.quantity += c.count
        row.sheets.add(s.sheet_label)
        items.set(key, row)
      }
      const lin = s.linear
      for (const b of lin?.by_size || []) {
        if (!b.length_ft) continue
        const label = lin.kind === 'duct' ? 'Ductwork' : 'Piping'
        const key = `lin|${label}|${b.size}|${b.service || ''}`
        const row = items.get(key) || {
          section: label,
          description: `${label} — ${b.service || 'unassigned service'}`,
          unit: 'LF',
          size: b.size,
          quantity: 0,
          sheets: new Set(),
        }
        row.quantity += b.length_ft
        row.sheets.add(s.sheet_label)
        items.set(key, row)
      }
    }
    return [...items.values()]
      .map((r) => ({ ...r, sheets: [...r.sheets].join(', ') }))
      .filter((r) => !q || `${r.description} ${r.size}`.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) => (a.section === b.section ? b.quantity - a.quantity : a.section.localeCompare(b.section)))
  }, [sheets, q, sheetFilter])

  if (!documentId) return <EmptyState title="No drawing set selected" hint="Analyse a drawing set first." />
  if (isFetching && !data) {
    return (
      <div className="empty">
        <div className="spin" style={{ margin: '0 auto 10px' }} />
        Loading quantities…
      </div>
    )
  }
  if (!data) return <EmptyState title="Not analysed yet" hint="Run the analysis on this drawing set." />

  const jumpToRun = (r) => {
    dispatch(setPage(r.page))
    dispatch(selectRun(r.id))
    dispatch(focusOn(r.bbox_pt))
    navigate('/drawings')
  }

  return (
    <div className="page wide">
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 4 }}>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? 'primary sm' : 'sm'} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <select value={sheetFilter} onChange={(e) => setSheetFilter(e.target.value)} style={{ width: 190 }}>
          <option value="">All sheets</option>
          {sheets.map((s) => (
            <option key={s.page_number} value={s.sheet_label}>
              {s.sheet_label} · {s.discipline_label}
            </option>
          ))}
        </select>
        <input placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
        <a className="btn sm" href={exportUrl(documentId, tab === 'runs' ? 'runs' : tab === 'boq' ? 'boq' : 'counts')}>
          ↧ CSV
        </a>
      </div>

      {tab === 'components' && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Sheet</th>
                <th>Discipline</th>
                <th>Group</th>
                <th>Component</th>
                <th className="num">Count</th>
                <th className="num">Mean confidence</th>
                <th>Detectors</th>
              </tr>
            </thead>
            <tbody>
              {componentRows.map((r, i) => (
                <tr key={i}>
                  <td><strong>{r.sheet}</strong></td>
                  <td className="small muted">{r.discipline}</td>
                  <td className="small">{r.category_group}</td>
                  <td>{r.category}</td>
                  <td className="num"><strong>{num(r.count)}</strong></td>
                  <td className="num">{Math.round((r.mean_confidence || 0) * 100)}%</td>
                  <td className="small mono muted">
                    {Object.entries(r.detectors || {}).map(([k, v]) => `${k}:${v}`).join(' ')}
                  </td>
                </tr>
              ))}
              {componentRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted small" style={{ textAlign: 'center', padding: 24 }}>
                    No components match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'runs' && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Sheet</th>
                <th className="num">Run</th>
                <th>Type</th>
                <th>Size</th>
                <th>Service</th>
                <th>Status</th>
                <th className="num">Length</th>
                <th className="num">Feet</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runRows.map((r) => (
                <tr key={`${r.sheet}-${r.id}`}>
                  <td><strong>{r.sheet}</strong></td>
                  <td className="num mono">#{r.id}</td>
                  <td className="small">{r.kind}</td>
                  <td>{r.size_label || <span className="muted">untagged</span>}</td>
                  <td className="small">{r.service_name || '—'}</td>
                  <td className="small">{r.status || 'new'}</td>
                  <td className="num mono">{r.length_label}</td>
                  <td className="num">{num(r.length_ft, 1)}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="sm ghost" onClick={() => jumpToRun(r)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'boq' && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Section</th>
                <th>Description</th>
                <th>Size</th>
                <th className="num">Quantity</th>
                <th>Unit</th>
                <th>Sheets</th>
              </tr>
            </thead>
            <tbody>
              {boqRows.map((r, i) => (
                <tr key={i}>
                  <td className="num muted">{i + 1}</td>
                  <td className="small">{r.section}</td>
                  <td>{r.description}</td>
                  <td className="mono small">{r.size || '—'}</td>
                  <td className="num"><strong>{num(r.quantity, r.unit === 'LF' ? 1 : 0)}</strong></td>
                  <td className="small">{r.unit}</td>
                  <td className="small muted">{r.sheets}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
