import React, { useEffect, useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  cropUrl,
  useCalibrateMutation,
  useLearnGlyphMutation,
  useResultQuery,
  useReviewMutation,
  useSheetQuery,
  useVisualSearchMutation,
} from '../store/api'
import { setDocument, setPage, toast } from '../store/uiSlice'
import {
  focusOn,
  resetCalibration,
  selectDetection,
  setCategoryFilter,
  setMinConfidence,
  setMode,
  setSearchResult,
  setSelection,
  toggleLayer,
} from '../store/viewerSlice'
import SheetCanvas from '../components/SheetCanvas'
import { categoryColor, num, pct } from '../lib/format'
import EmptyState from '../components/EmptyState'

const LAYER_LABELS = {
  detections: 'Components',
  runs: 'Duct / pipe runs',
  findings: 'Findings',
  clashes: 'Clashes',
  matches: 'Search matches',
}

function ScalePanel({ sheet, projectId, documentId }) {
  const dispatch = useDispatch()
  const calib = useSelector((s) => s.viewer.calibration)
  const mode = useSelector((s) => s.viewer.mode)
  const [feet, setFeet] = useState('')
  const [inches, setInches] = useState('')
  const [calibrate, { isLoading }] = useCalibrateMutation()
  const scale = sheet.scale || {}

  const apply = async () => {
    if (!calib.p1 || !calib.p2) return
    try {
      await calibrate({
        projectId,
        document_id: documentId,
        page_number: sheet.page_number,
        p1: calib.p1,
        p2: calib.p2,
        real_feet: parseFloat(feet) || 0,
        real_inches: parseFloat(inches) || 0,
      }).unwrap()
      dispatch(resetCalibration())
      dispatch(setMode('pan'))
      dispatch(toast({ message: 'Scale updated — all lengths on this sheet were rescaled.' }))
    } catch (e) {
      dispatch(toast({ kind: 'error', message: e?.data?.detail || 'Calibration failed' }))
    }
  }

  const conf = scale.confidence || 0
  return (
    <div className="pane-section">
      <h4>Drawing scale</h4>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong style={{ fontSize: 14 }}>{scale.label}</strong>
        <span className={`badge ${conf >= 0.8 ? 'ok' : conf >= 0.55 ? 'warn' : 'danger'}`}>
          {pct(conf)} confident
        </span>
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>
        {scale.evidence}
      </div>
      <div className="small muted" style={{ marginTop: 2 }}>
        Method: <span className="mono">{scale.method}</span>
      </div>

      <button
        className="sm"
        style={{ marginTop: 10, width: '100%' }}
        onClick={() => dispatch(setMode(mode === 'calibrate' ? 'pan' : 'calibrate'))}
      >
        {mode === 'calibrate' ? 'Cancel calibration' : 'Calibrate from the drawing'}
      </button>

      {mode === 'calibrate' && (
        <div className="col" style={{ marginTop: 10 }}>
          <div className="small muted">
            {!calib.p1
              ? 'Click the first point on the drawing.'
              : !calib.p2
                ? 'Click the second point.'
                : 'Now enter the real distance between them.'}
          </div>
          <div className="row">
            <label className="field" style={{ flex: 1 }}>
              Feet
              <input value={feet} onChange={(e) => setFeet(e.target.value)} placeholder="20" inputMode="decimal" />
            </label>
            <label className="field" style={{ flex: 1 }}>
              Inches
              <input value={inches} onChange={(e) => setInches(e.target.value)} placeholder="0" inputMode="decimal" />
            </label>
          </div>
          <button
            className="primary sm"
            disabled={!calib.p1 || !calib.p2 || isLoading || (!feet && !inches)}
            onClick={apply}
          >
            Apply scale
          </button>
        </div>
      )}
    </div>
  )
}

function VisualSearchPanel({ sheet, documentId, projectId }) {
  const dispatch = useDispatch()
  const { mode, selection, searchResult } = useSelector((s) => s.viewer)
  const [search, { isLoading }] = useVisualSearchMutation()
  const [learn] = useLearnGlyphMutation()
  const [label, setLabel] = useState('')

  useEffect(() => {
    const run = async () => {
      if (!selection) return
      try {
        const res = await search({
          document_id: documentId,
          page_number: sheet.page_number,
          bbox_pt: [selection.x0, selection.y0, selection.x1, selection.y1],
        }).unwrap()
        dispatch(setSearchResult(res))
        setLabel(res.known_label || '')
      } catch (e) {
        dispatch(toast({ kind: 'error', message: e?.data?.detail || 'Search failed' }))
      } finally {
        dispatch(setSelection(null))
      }
    }
    run()
  }, [selection, documentId, sheet.page_number, search, dispatch])

  const saveLabel = async () => {
    if (!searchResult || !label.trim()) return
    await learn({
      glyph_id: searchResult.glyph_id,
      label: label.trim(),
      trade: sheet.discipline,
      size_pt: [searchResult.template.width_pt, searchResult.template.height_pt],
    }).unwrap()
    dispatch(
      toast({
        message: `Saved “${label.trim()}”. Every matching stamp is now counted automatically, here and on future drawings.`,
        ms: 6000,
      })
    )
  }

  return (
    <div className="pane-section">
      <h4>Find similar symbols</h4>
      <button
        className={mode === 'select' ? 'primary sm' : 'sm'}
        style={{ width: '100%' }}
        onClick={() => dispatch(setMode(mode === 'select' ? 'pan' : 'select'))}
      >
        {mode === 'select' ? 'Selecting — drag on the sheet' : 'Select a symbol to count'}
      </button>

      {isLoading && (
        <div className="row small muted" style={{ marginTop: 10 }}>
          <div className="spin" /> Matching geometry…
        </div>
      )}

      {searchResult && (
        <div style={{ marginTop: 12 }}>
          <div className="row">
            <svg
              className="glyph-preview"
              width={40}
              height={40}
              viewBox={`-1 -1 ${searchResult.template.width_pt + 2} ${searchResult.template.height_pt + 2}`}
            >
              <path d={searchResult.template.svg_path} />
            </svg>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{num(searchResult.count)}</div>
              <div className="small muted">
                occurrences · {searchResult.elapsed_s}s · {searchResult.template.n_segments} strokes
              </div>
            </div>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Name this component…"
            />
            <button className="sm" disabled={!label.trim()} onClick={saveLabel}>
              Save
            </button>
          </div>
          <div className="small muted" style={{ marginTop: 6 }}>
            Naming it adds it to the library, so it is recognised on every drawing from now on.
          </div>
          <button
            className="sm ghost"
            style={{ marginTop: 8, width: '100%' }}
            onClick={() => dispatch(setSearchResult(null))}
          >
            Clear matches
          </button>
        </div>
      )}
    </div>
  )
}

function Inspector({ sheet, documentId, projectId }) {
  const dispatch = useDispatch()
  const { selectedDetection, selectedRun } = useSelector((s) => s.viewer)
  const [review] = useReviewMutation()

  const det = (sheet.detections || []).find((d) => d.id === selectedDetection)
  const run = (sheet.linear?.runs || []).find((r) => r.id === selectedRun)

  const act = async (action) => {
    if (!det) return
    await review({
      projectId,
      document_id: documentId,
      page_number: sheet.page_number,
      target_type: 'detection',
      target_id: String(det.id),
      action,
    }).unwrap()
    dispatch(
      toast({
        message:
          action === 'rejected'
            ? 'Removed from the count.'
            : 'Confirmed — counted with full confidence.',
      })
    )
    if (action === 'rejected') dispatch(selectDetection(null))
  }

  if (det) {
    return (
      <div className="pane-section">
        <h4>Component</h4>
        <img
          src={cropUrl(documentId, sheet.page_number, det.bbox_pt, 320)}
          alt=""
          style={{
            width: '100%',
            borderRadius: 8,
            border: '1px solid var(--line)',
            background: '#fff',
            marginBottom: 10,
          }}
        />
        <div className="row" style={{ marginBottom: 6 }}>
          <span className="dot" style={{ width: 10, height: 10, borderRadius: 3, background: categoryColor(det.category_key) }} />
          <strong style={{ fontSize: 13.5 }}>{det.category}</strong>
        </div>
        <dl className="kv">
          <dt>Confidence</dt>
          <dd>{pct(det.confidence)}</dd>
          <dt>Detector</dt>
          <dd className="mono">{det.detector}</dd>
          <dt>Trade</dt>
          <dd>{det.trade || '—'}</dd>
          <dt>Position</dt>
          <dd className="mono">
            {det.bbox_pt[0].toFixed(0)}, {det.bbox_pt[1].toFixed(0)} pt
          </dd>
          {det.review !== 'unreviewed' && (
            <>
              <dt>Review</dt>
              <dd>{det.review}</dd>
            </>
          )}
        </dl>
        <div className="small" style={{ marginTop: 10, color: 'var(--text-2)' }}>
          <strong style={{ color: 'var(--text)' }}>Why: </strong>
          {det.rationale}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="sm" onClick={() => act('confirmed')}>
            ✓ Confirm
          </button>
          <button className="sm danger" onClick={() => act('rejected')}>
            ✕ Not a component
          </button>
        </div>
      </div>
    )
  }

  if (run) {
    return (
      <div className="pane-section">
        <h4>Traced run</h4>
        <div style={{ fontSize: 20, fontWeight: 700 }}>{run.length_label}</div>
        <div className="small muted">{num(run.length_ft, 1)} ft measured along the centreline</div>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>Run</dt>
          <dd className="mono">#{run.id}</dd>
          <dt>Size</dt>
          <dd>{run.size_label || '—'}</dd>
          <dt>Service</dt>
          <dd>{run.service_name || '—'}</dd>
          <dt>Status</dt>
          <dd>{run.status || 'new'}</dd>
          <dt>Segments</dt>
          <dd>{run.n_segments}</dd>
          {run.width_in ? (
            <>
              <dt>Width</dt>
              <dd>{run.width_in}&quot;</dd>
            </>
          ) : null}
        </dl>
        <button
          className="sm"
          style={{ marginTop: 10, width: '100%' }}
          onClick={() => dispatch(focusOn(run.bbox_pt))}
        >
          Zoom to run
        </button>
      </div>
    )
  }

  return (
    <div className="pane-section">
      <h4>Inspector</h4>
      <div className="small muted">
        Click a component box or a traced run on the drawing to see how it was identified and
        measured — and to confirm or reject it.
      </div>
    </div>
  )
}

export default function Drawings() {
  const dispatch = useDispatch()
  const { projectId, documentId: docFromState, page } = useSelector((s) => s.ui)
  const viewer = useSelector((s) => s.viewer)
  const { data: overview } = useResultQuery(docFromState, { skip: !docFromState })
  const documentId = docFromState

  const pages = overview?.sheets || []
  const current = pages.find((s) => s.page_number === page) || pages[0]
  const { data: sheet, isFetching } = useSheetQuery(
    { documentId, page: current?.page_number },
    { skip: !documentId || !current }
  )

  useEffect(() => {
    if (current && current.page_number !== page) dispatch(setPage(current.page_number))
  }, [current, page, dispatch])

  const categories = useMemo(() => {
    const m = new Map()
    for (const c of sheet?.counts || []) m.set(c.category_key, c)
    return [...m.values()]
  }, [sheet])

  if (!documentId) {
    return <EmptyState title="No drawing set open" hint="Upload and analyse a drawing set to start reviewing." />
  }
  if (!overview) {
    return <EmptyState title="Nothing analysed yet" hint="Run the analysis from the Projects page." />
  }

  return (
    <div className="viewer-shell" style={{ height: 'calc(100vh - 56px)' }}>
      <aside className="viewer-pane">
        <div className="pane-section">
          <h4>Sheets ({pages.length})</h4>
          {pages.map((s) => (
            <div
              key={s.page_number}
              className={`list-item ${s.page_number === current?.page_number ? 'active' : ''}`}
              onClick={() => dispatch(setPage(s.page_number))}
            >
              <div className="row">
                <span
                  className="dot"
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: `var(--${s.discipline === 'mechanical' ? 'mech' : s.discipline === 'plumbing' ? 'plumb' : s.discipline === 'electrical' ? 'elec' : 'fire'})`,
                  }}
                />
                <span className="t">{s.sheet_label}</span>
                <span className="spacer" />
                <span className="badge">{s.scale?.label}</span>
              </div>
              <div className="s">
                {s.discipline_label}
                {s.sheet_title ? ` · ${s.sheet_title.slice(0, 32)}` : ''}
              </div>
            </div>
          ))}
        </div>

        <div className="pane-section">
          <h4>Layers</h4>
          <div className="row wrap">
            {Object.keys(LAYER_LABELS).map((k) => (
              <span
                key={k}
                className={`chip ${viewer.layers[k] ? 'on' : ''}`}
                onClick={() => dispatch(toggleLayer(k))}
              >
                {LAYER_LABELS[k]}
              </span>
            ))}
          </div>
        </div>

        {categories.length > 0 && (
          <div className="pane-section">
            <h4>Component filter</h4>
            <div className="row wrap">
              {categories.map((c) => {
                const on = viewer.categoryFilter.includes(c.category_key)
                return (
                  <span
                    key={c.category_key}
                    className={`chip ${on ? 'on' : ''}`}
                    onClick={() =>
                      dispatch(
                        setCategoryFilter(
                          on
                            ? viewer.categoryFilter.filter((k) => k !== c.category_key)
                            : [...viewer.categoryFilter, c.category_key]
                        )
                      )
                    }
                  >
                    <span className="dot" style={{ background: categoryColor(c.category_key) }} />
                    {c.category.split('(')[0].trim()} · {c.count}
                  </span>
                )
              })}
            </div>
            {viewer.categoryFilter.length > 0 && (
              <button className="sm ghost" style={{ marginTop: 8 }} onClick={() => dispatch(setCategoryFilter([]))}>
                Show all
              </button>
            )}
            <label className="field" style={{ marginTop: 12 }}>
              Minimum confidence · {pct(viewer.minConfidence)}
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={viewer.minConfidence}
                onChange={(e) => dispatch(setMinConfidence(parseFloat(e.target.value)))}
              />
            </label>
          </div>
        )}
      </aside>

      <div style={{ position: 'relative', minWidth: 0 }}>
        {isFetching && !sheet ? (
          <div className="empty">
            <div className="spin" style={{ margin: '0 auto 10px' }} />
            Loading sheet…
          </div>
        ) : (
          <SheetCanvas sheet={sheet} documentId={documentId} clashes={overview.clashes || []} />
        )}
      </div>

      <aside className="viewer-pane right">
        {sheet && (
          <>
            <ScalePanel sheet={sheet} projectId={projectId} documentId={documentId} />
            <VisualSearchPanel sheet={sheet} documentId={documentId} projectId={projectId} />
            <Inspector sheet={sheet} documentId={documentId} projectId={projectId} />
            {sheet.linear && (
              <div className="pane-section">
                <h4>Measured on this sheet</h4>
                <dl className="kv">
                  <dt>{sheet.linear.kind === 'duct' ? 'Ductwork' : 'Piping'}</dt>
                  <dd>{num(sheet.linear.total_length_ft)} ft</dd>
                  <dt>Runs traced</dt>
                  <dd>{num(sheet.linear.run_count)}</dd>
                  <dt>Networks</dt>
                  <dd>{num(sheet.connectivity?.networks?.length)}</dd>
                  <dt>Unconnected</dt>
                  <dd>{num(sheet.connectivity?.isolated_runs?.length)}</dd>
                </dl>
                <div className="small muted" style={{ marginTop: 8 }}>
                  {sheet.linear.layer?.evidence}
                </div>
              </div>
            )}
          </>
        )}
      </aside>
    </div>
  )
}
