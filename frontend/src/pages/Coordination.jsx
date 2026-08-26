import React, { useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { exportUrl, useResultQuery } from '../store/api'
import { setPage } from '../store/uiSlice'
import { focusOn } from '../store/viewerSlice'
import EmptyState from '../components/EmptyState'
import { Stat } from '../components/Stat'
import { num } from '../lib/format'

export default function Coordination() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { documentId } = useSelector((s) => s.ui)
  const { data } = useResultQuery(documentId, { skip: !documentId })
  const [sev, setSev] = useState('')

  const clashes = useMemo(
    () => (data?.clashes || []).filter((c) => !sev || c.severity === sev),
    [data, sev]
  )

  if (!documentId) return <EmptyState title="No drawing set selected" hint="Analyse a drawing set first." />
  if (!data) return <EmptyState title="Not analysed yet" hint="Run the analysis on this drawing set." />

  const summary = data.clash_summary || {}
  const sheetPage = (label) =>
    (data.sheet_index || []).find((s) => s.sheet_label === label)?.page_number

  return (
    <div className="page wide">
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat label="Conflicts flagged" value={num(summary.total || 0)} sub="2-D plan overlap screen" />
        <Stat
          label="Hard overlaps"
          value={num(summary.by_severity?.critical || 0)}
          tone="var(--sev-critical)"
          sub="systems in the same plan space"
        />
        <Stat
          label="Tight clearances"
          value={num((summary.by_severity?.high || 0) + (summary.by_severity?.medium || 0))}
          tone="var(--sev-high)"
          sub="below the trade clearance"
        />
        <Stat
          label="Trade pairs"
          value={num((summary.by_trade_pair || []).length)}
          sub={(summary.by_trade_pair || []).map((p) => p.pair).join(', ') || '—'}
        />
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <div>
            <h3 style={{ margin: 0 }}>Cross-discipline conflicts</h3>
            <p className="hint" style={{ margin: '4px 0 0' }}>
              Same-level sheets from different trades, overlaid on their shared drawing frame. This
              is a screening pass for a human to check — elevations are not known from a plan.
            </p>
          </div>
          <span className="spacer" />
          <select value={sev} onChange={(e) => setSev(e.target.value)} style={{ width: 150 }}>
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
          <a className="btn sm" href={exportUrl(documentId, 'clashes')}>
            ↧ CSV
          </a>
        </div>

        {clashes.length === 0 ? (
          <div className="small muted" style={{ padding: 24, textAlign: 'center' }}>
            No conflicts found. Clash screening needs at least two sheets from different trades at
            the same level, published at the same scale and frame.
          </div>
        ) : (
          <div className="table-wrap" style={{ maxHeight: '58vh' }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Trades</th>
                  <th>Level</th>
                  <th>Sheets</th>
                  <th>Elements</th>
                  <th className="num">Encroachment</th>
                  <th>Detail</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {clashes.slice(0, 400).map((c) => (
                  <tr key={c.id}>
                    <td>
                      <span className={`sev ${c.severity}`}>{c.severity}</span>
                    </td>
                    <td className="small">
                      {c.trade_a} / {c.trade_b}
                    </td>
                    <td className="small">{c.level || '—'}</td>
                    <td className="small mono">
                      {c.sheet_a} ↔ {c.sheet_b}
                    </td>
                    <td className="small muted">
                      {c.ref_a} ↔ {c.ref_b}
                    </td>
                    <td className="num">{c.overlap_in}&quot;</td>
                    <td className="small">{c.message}</td>
                    <td style={{ textAlign: 'right' }}>
                      {c.location_pt && (
                        <button
                          className="sm ghost"
                          onClick={() => {
                            const p = sheetPage(c.sheet_a)
                            if (p) dispatch(setPage(p))
                            dispatch(focusOn(c.location_pt))
                            navigate('/drawings')
                          }}
                        >
                          View
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
