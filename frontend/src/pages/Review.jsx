import React, { useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import {
  exportUrl,
  useCatalogueQuery,
  useLearnGlyphMutation,
  useResultFullQuery,
  useReviewMutation,
} from '../store/api'
import { setPage, toast } from '../store/uiSlice'
import { focusOn } from '../store/viewerSlice'
import EmptyState from '../components/EmptyState'
import { SEVERITY_ORDER, num } from '../lib/format'

function GlyphRow({ glyph, sheet, documentId }) {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const [learn, { isLoading }] = useLearnGlyphMutation()
  const [label, setLabel] = useState('')

  const save = async () => {
    if (!label.trim()) return
    await learn({
      glyph_id: glyph.glyph_id,
      label: label.trim(),
      trade: sheet.discipline,
      size_pt: [glyph.width_pt, glyph.height_pt],
    }).unwrap()
    dispatch(
      toast({
        message: `“${label.trim()}” learned — ${glyph.count} instances on this sheet are now counted, and it will be recognised on future drawings.`,
        ms: 7000,
      })
    )
    setLabel('')
  }

  return (
    <div className="list-item" style={{ cursor: 'default' }}>
      <div className="row">
        <div style={{ fontSize: 18, fontWeight: 700, minWidth: 46 }}>{glyph.count}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="t">Unidentified repeated symbol</div>
          <div className="s">
            {glyph.width_pt} × {glyph.height_pt} pt · {glyph.n_segments} strokes · sheet{' '}
            {sheet.sheet_label}
          </div>
        </div>
        <button
          className="sm ghost"
          onClick={() => {
            dispatch(setPage(sheet.page_number))
            dispatch(focusOn(glyph.instances?.[0]))
            navigate('/drawings')
          }}
        >
          Show
        </button>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input
          placeholder="What is this component?"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && save()}
        />
        <button className="sm primary" disabled={!label.trim() || isLoading} onClick={save}>
          Learn
        </button>
      </div>
    </div>
  )
}

export default function Review() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { documentId, projectId } = useSelector((s) => s.ui)
  const { data } = useResultFullQuery(documentId, { skip: !documentId })
  const { data: catalogue } = useCatalogueQuery()
  const [review] = useReviewMutation()
  const [sev, setSev] = useState('')
  const [rule, setRule] = useState('')
  const [showDismissed, setShowDismissed] = useState(false)

  const findings = useMemo(() => {
    const rows = []
    for (const s of data?.sheets || []) {
      for (const f of s.findings || []) {
        rows.push({ ...f, page: s.page_number, sheet_label: s.sheet_label })
      }
    }
    return rows
      .filter((f) => (showDismissed ? true : f.status !== 'dismissed'))
      .filter((f) => !sev || f.severity === sev)
      .filter((f) => !rule || f.rule_id === rule)
      .sort(
        (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
      )
  }, [data, sev, rule, showDismissed])

  const glyphs = useMemo(() => {
    const rows = []
    for (const s of data?.sheets || []) {
      for (const g of s.glyphs || []) {
        if (g.source === 'mined' && g.count >= 5 && !g.label) rows.push({ g, s })
      }
    }
    return rows.sort((a, b) => b.g.count - a.g.count).slice(0, 12)
  }, [data])

  if (!documentId) return <EmptyState title="No drawing set selected" hint="Analyse a drawing set first." />
  if (!data) return <EmptyState title="Not analysed yet" hint="Run the analysis on this drawing set." />

  const jump = (f) => {
    dispatch(setPage(f.page))
    if (f.location_pt) dispatch(focusOn(f.location_pt))
    navigate('/drawings')
  }

  const dismiss = async (f) => {
    await review({
      projectId,
      document_id: documentId,
      page_number: f.page,
      target_type: 'finding',
      target_id: `${f.rule_id}@${JSON.stringify(f.location_pt)}`,
      action: 'dismissed',
    }).unwrap()
    dispatch(toast({ message: `${f.rule_id} dismissed.` }))
  }

  const ruleIds = [...new Set((data.sheets || []).flatMap((s) => (s.findings || []).map((f) => f.rule_id)))].sort()

  return (
    <div className="page wide">
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <select value={sev} onChange={(e) => setSev(e.target.value)} style={{ width: 160 }}>
          <option value="">All severities</option>
          {SEVERITY_ORDER.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select value={rule} onChange={(e) => setRule(e.target.value)} style={{ width: 190 }}>
          <option value="">All rules</option>
          {ruleIds.map((r) => (
            <option key={r} value={r}>
              {r} — {catalogue?.rules?.find((x) => x.id === r)?.title || ''}
            </option>
          ))}
        </select>
        <label className="row small" style={{ gap: 6 }}>
          <input
            type="checkbox"
            checked={showDismissed}
            onChange={(e) => setShowDismissed(e.target.checked)}
            style={{ width: 'auto' }}
          />
          Show dismissed
        </label>
        <span className="spacer" />
        <span className="badge">{findings.length} findings</span>
        <a className="btn sm" href={exportUrl(documentId, 'findings')}>
          ↧ CSV
        </a>
        <a className="btn sm" href={exportUrl(documentId, 'issues')}>
          ↧ BCF issues
        </a>
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="card tight">
          <div style={{ maxHeight: '68vh', overflow: 'auto' }}>
            {findings.map((f, i) => (
              <div key={i} className="list-item" style={{ cursor: 'default' }}>
                <div className="row">
                  <span className={`sev ${f.severity}`}>{f.severity}</span>
                  <span className="mono small muted">{f.rule_id}</span>
                  <span className="spacer" />
                  <span className="badge">{f.sheet_label}</span>
                  {f.status === 'dismissed' && <span className="badge">dismissed</span>}
                </div>
                <div className="t" style={{ marginTop: 6 }}>
                  {f.title}
                </div>
                <div className="s" style={{ marginTop: 3, lineHeight: 1.5 }}>
                  {f.message}
                </div>
                {f.recommendation && (
                  <div className="s" style={{ marginTop: 5, color: 'var(--brand)' }}>
                    → {f.recommendation}
                  </div>
                )}
                <div className="row" style={{ marginTop: 8 }}>
                  {f.location_pt && (
                    <button className="sm" onClick={() => jump(f)}>
                      Show on drawing
                    </button>
                  )}
                  {f.status !== 'dismissed' && (
                    <button className="sm ghost" onClick={() => dismiss(f)}>
                      Dismiss
                    </button>
                  )}
                </div>
              </div>
            ))}
            {findings.length === 0 && (
              <div className="small muted" style={{ padding: 20, textAlign: 'center' }}>
                Nothing flagged with this filter.
              </div>
            )}
          </div>
        </div>

        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <h3>Teach the library</h3>
            <p className="hint">
              These symbols repeat on the drawings but are not in the component catalogue. Name one
              and every instance — here and on every future set — is counted automatically.
            </p>
            {glyphs.length === 0 ? (
              <div className="small muted">Nothing unidentified worth naming on these sheets.</div>
            ) : (
              glyphs.map(({ g, s }) => (
                <GlyphRow key={g.glyph_id} glyph={g} sheet={s} documentId={documentId} />
              ))
            )}
          </div>

          <div className="card">
            <h3>Validation rules</h3>
            <p className="hint">Every check MEPIQ runs, and why it matters.</p>
            <div style={{ maxHeight: 320, overflow: 'auto' }}>
              {(catalogue?.rules || []).map((r) => (
                <div key={r.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--line-soft)' }}>
                  <div className="row">
                    <span className={`sev ${r.severity}`}>{r.severity}</span>
                    <span className="mono small muted">{r.id}</span>
                    <span style={{ fontSize: 13, fontWeight: 550 }}>{r.title}</span>
                  </div>
                  <div className="small muted" style={{ marginTop: 3 }}>
                    {r.rationale}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
