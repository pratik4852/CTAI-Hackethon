import React from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { useResultQuery } from '../store/api'
import { setPage } from '../store/uiSlice'
import { BarList, Stat } from '../components/Stat'
import EmptyState from '../components/EmptyState'
import { SEVERITY_ORDER, categoryColor, num } from '../lib/format'

const SEV_VAR = {
  critical: 'var(--sev-critical)',
  high: 'var(--sev-high)',
  medium: 'var(--sev-medium)',
  low: 'var(--sev-low)',
  info: 'var(--sev-info)',
}

const DISC_VAR = {
  mechanical: 'var(--mech)',
  plumbing: 'var(--plumb)',
  electrical: 'var(--elec)',
  fire_protection: 'var(--fire)',
}

export default function Dashboard() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { documentId } = useSelector((s) => s.ui)
  const { data, isFetching } = useResultQuery(documentId, { skip: !documentId })

  if (!documentId) {
    return <EmptyState title="No drawing set selected" hint="Upload a drawing set and run the analysis." />
  }
  if (isFetching && !data) {
    return (
      <div className="empty">
        <div className="spin" style={{ margin: '0 auto 10px' }} />
        Loading results…
      </div>
    )
  }
  if (!data) {
    return <EmptyState title="Not analysed yet" hint="Run the analysis on this drawing set to see results." />
  }

  const t = data.totals || {}
  const sev = t.findings_by_severity || {}
  const openSheet = (page) => {
    dispatch(setPage(page))
    navigate('/drawings')
  }

  return (
    <div className="page wide">
      <div className="row" style={{ marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 650 }}>{data.file_name}</div>
          <div className="small muted">
            {data.analysed_sheets} of {data.page_count} pages analysed in {data.elapsed_s}s ·
            geometry read directly from the PDF
          </div>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat label="Components detected" value={num(t.component_total)} sub={`${(t.components || []).length} types`} />
        <Stat
          label="Ductwork measured"
          value={num(t.duct_length_ft)}
          unit="ft"
          sub="centreline length"
          tone="var(--mech)"
        />
        <Stat
          label="Piping measured"
          value={num(t.pipe_length_ft)}
          unit="ft"
          sub={`${num(t.run_count)} runs traced`}
          tone="var(--plumb)"
        />
        <Stat
          label="Review findings"
          value={num(t.finding_count)}
          sub={`${sev.critical || 0} critical · ${sev.high || 0} high`}
          tone={sev.critical ? 'var(--sev-critical)' : sev.high ? 'var(--sev-high)' : undefined}
        />
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Components by type</h3>
          <p className="hint">Every count is traceable to specific geometry on a sheet.</p>
          {(t.components || []).length === 0 ? (
            <div className="small muted">No components detected.</div>
          ) : (
            <BarList
              rows={(t.components || []).slice(0, 10)}
              colorFor={(r) => categoryColor(r.category_key)}
              labelFor={(r) => r.category}
              valueFor={(r) => r.count}
            />
          )}
        </div>

        <div className="card">
          <h3>Findings by severity</h3>
          <p className="hint">Design validation and constructability checks across the set.</p>
          <BarList
            rows={SEVERITY_ORDER.map((s) => ({ s, n: sev[s] || 0 })).filter((r) => r.n > 0)}
            colorFor={(r) => SEV_VAR[r.s]}
            labelFor={(r) => r.s.charAt(0).toUpperCase() + r.s.slice(1)}
            valueFor={(r) => r.n}
          />
          {data.clash_summary?.total > 0 && (
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line-soft)' }}>
              <div className="row">
                <strong style={{ fontSize: 13 }}>Cross-discipline conflicts</strong>
                <span className="spacer" />
                <span className="badge danger">{data.clash_summary.total}</span>
              </div>
              <div className="small muted" style={{ marginTop: 4 }}>
                {(data.clash_summary.by_trade_pair || [])
                  .map((p) => `${p.pair} (${p.count})`)
                  .join(' · ')}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Sheets</h3>
        <p className="hint">Click a sheet to open it in the reviewer.</p>
        <div className="table-wrap" style={{ maxHeight: '46vh' }}>
          <table className="data">
            <thead>
              <tr>
                <th>Sheet</th>
                <th>Discipline</th>
                <th>Title</th>
                <th>Scale</th>
                <th className="num">Components</th>
                <th className="num">Runs</th>
                <th className="num">Length</th>
                <th className="num">Findings</th>
              </tr>
            </thead>
            <tbody>
              {(data.sheet_index || []).map((s) => (
                <tr key={s.page_number} style={{ cursor: 'pointer' }} onClick={() => openSheet(s.page_number)}>
                  <td>
                    <span className="row" style={{ gap: 7 }}>
                      <span
                        style={{
                          width: 7,
                          height: 7,
                          borderRadius: '50%',
                          background: DISC_VAR[s.discipline] || 'var(--text-3)',
                        }}
                      />
                      <strong>{s.sheet_label}</strong>
                    </span>
                  </td>
                  <td className="small">{s.discipline_label}</td>
                  <td className="small muted">{s.sheet_title || '—'}</td>
                  <td className="small mono">{s.scale}</td>
                  <td className="num">{num(s.detections)}</td>
                  <td className="num">{num(s.runs)}</td>
                  <td className="num">{s.length_ft ? `${num(s.length_ft)} ft` : '—'}</td>
                  <td className="num">
                    {s.findings ? <span className="badge warn">{s.findings}</span> : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
