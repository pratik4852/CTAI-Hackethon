import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { pageImageUrl } from '../store/api'
import {
  focusOn,
  selectDetection,
  selectRun,
  setCalibrationPoint,
  setMode,
  setSelection,
  setTransform,
  setViewportCentre,
} from '../store/viewerSlice'
import { categoryColor } from '../lib/format'

const RENDER_DPI = 130
const PT_TO_PX = RENDER_DPI / 72

const SEV_COLOR = {
  critical: '#f43f5e',
  high: '#fb923c',
  medium: '#fbbf24',
  low: '#60a5fa',
  info: '#94a3b8',
}

/**
 * The drawing viewer.
 *
 * The sheet is a rendered raster; everything the analysis found is drawn over it
 * as vector SVG in the drawing's own coordinate space. That keeps overlays crisp
 * at any zoom and — more importantly — means every box on screen is the actual
 * geometry the engine measured, not an approximation of it.
 */
export default function SheetCanvas({ sheet, documentId, clashes = [] }) {
  const dispatch = useDispatch()
  const wrapRef = useRef(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [drag, setDrag] = useState(null)
  const [marquee, setMarquee] = useState(null)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [spaceHeld, setSpaceHeld] = useState(false)

  const {
    layers, mode, transform, selectedDetection, selectedRun, focus,
    categoryFilter, minConfidence, searchResult, calibration: calib,
  } = useSelector((s) => s.viewer)

  const pageW = (sheet?.width_pt || 0) * PT_TO_PX
  const pageH = (sheet?.height_pt || 0) * PT_TO_PX

  // --- fit to view -------------------------------------------------------
  const fit = useCallback(() => {
    const el = wrapRef.current
    if (!el || !pageW || !pageH) return
    const { clientWidth: w, clientHeight: h } = el
    const scale = Math.min(w / pageW, h / pageH) * 0.94
    dispatch(
      setTransform({ scale, x: (w - pageW * scale) / 2, y: (h - pageH * scale) / 2 })
    )
  }, [dispatch, pageW, pageH])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return undefined
    const publish = () => {
      setSize({ w: el.clientWidth, h: el.clientHeight })
      dispatch(setViewportCentre({ x: el.clientWidth / 2, y: el.clientHeight / 2 }))
    }
    const ro = new ResizeObserver(publish)
    ro.observe(el)
    publish()
    return () => ro.disconnect()
  }, [dispatch])

  // Fit as soon as the sheet's dimensions are known, rather than waiting for
  // the rendered image. A big sheet can take seconds to render — and while a
  // full analysis is running it competes for CPU — so gating the view on the
  // image meant a slow or failed render left the stage at scale 1 pinned to the
  // origin, showing nothing. The overlays are real geometry and can be read
  // without the raster behind them.
  useEffect(() => {
    if (pageW && pageH && size.w > 0) fit()
  }, [pageW, pageH, size.w, size.h, fit])

  // A fresh page needs a fresh load state, otherwise the previous sheet's
  // "loaded" carries over and the spinner never appears.
  useEffect(() => {
    setImgLoaded(false)
    setImgError(false)
  }, [documentId, sheet?.page_number])

  // Hold space to pan from any tool; typing in a panel input must not trigger it.
  useEffect(() => {
    const typing = (t) => t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)
    const down = (e) => {
      if (e.code === 'Space' && !typing(e.target)) {
        e.preventDefault()
        setSpaceHeld(true)
      }
    }
    const up = (e) => {
      if (e.code === 'Space') setSpaceHeld(false)
    }
    const blur = () => setSpaceHeld(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  }, [])

  // --- fly to a location -------------------------------------------------
  useEffect(() => {
    if (!focus?.bbox || !wrapRef.current) return
    const el = wrapRef.current
    const [x0, y0, x1, y1] = focus.bbox
    const cx = ((x0 + x1) / 2) * PT_TO_PX
    const cy = ((y0 + y1) / 2) * PT_TO_PX
    const span = Math.max((x1 - x0) * PT_TO_PX, (y1 - y0) * PT_TO_PX, 40)
    const scale = Math.min(4, Math.max(0.4, (Math.min(el.clientWidth, el.clientHeight) * 0.35) / span))
    dispatch(
      setTransform({
        scale,
        x: el.clientWidth / 2 - cx * scale,
        y: el.clientHeight / 2 - cy * scale,
      })
    )
  }, [focus, dispatch])

  // --- pointer -----------------------------------------------------------
  const toPagePt = useCallback(
    (clientX, clientY) => {
      const rect = wrapRef.current.getBoundingClientRect()
      const px = (clientX - rect.left - transform.x) / transform.scale
      const py = (clientY - rect.top - transform.y) / transform.scale
      return [px / PT_TO_PX, py / PT_TO_PX]
    },
    [transform]
  )

  const onWheel = (e) => {
    e.preventDefault()
    const rect = wrapRef.current.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const factor = Math.exp(-e.deltaY * 0.0016)
    const scale = Math.min(14, Math.max(0.05, transform.scale * factor))
    dispatch(
      setTransform({
        scale,
        x: mx - (mx - transform.x) * (scale / transform.scale),
        y: my - (my - transform.y) * (scale / transform.scale),
      })
    )
  }

  const onPointerDown = (e) => {
    // Middle-drag pans from any mode, and so does a left-drag while space is
    // held — the convention every CAD and design tool shares. Without it a user
    // who has armed the select tool has to go back to the panel just to scroll
    // the sheet.
    const wantsPan = e.button === 1 || spaceHeld || mode === 'pan'
    if (e.button !== 0 && e.button !== 1) return
    e.currentTarget.setPointerCapture?.(e.pointerId)

    if (wantsPan) {
      setDrag({ x: e.clientX - transform.x, y: e.clientY - transform.y })
      return
    }
    if (mode === 'select') {
      const [x, y] = toPagePt(e.clientX, e.clientY)
      setMarquee({ x0: x, y0: y, x1: x, y1: y })
    } else if (mode === 'calibrate') {
      const [x, y] = toPagePt(e.clientX, e.clientY)
      dispatch(setCalibrationPoint([x, y]))
    }
  }

  const zoomBy = (factor) => {
    const el = wrapRef.current
    if (!el) return
    const mx = el.clientWidth / 2
    const my = el.clientHeight / 2
    const scale = Math.min(14, Math.max(0.05, transform.scale * factor))
    dispatch(
      setTransform({
        scale,
        x: mx - (mx - transform.x) * (scale / transform.scale),
        y: my - (my - transform.y) * (scale / transform.scale),
      })
    )
  }

  const onPointerMove = (e) => {
    if (drag) {
      dispatch(setTransform({ ...transform, x: e.clientX - drag.x, y: e.clientY - drag.y }))
    } else if (marquee) {
      const [x, y] = toPagePt(e.clientX, e.clientY)
      setMarquee((m) => ({ ...m, x1: x, y1: y }))
    }
  }

  const onPointerUp = () => {
    if (marquee) {
      const box = [
        Math.min(marquee.x0, marquee.x1),
        Math.min(marquee.y0, marquee.y1),
        Math.max(marquee.x0, marquee.x1),
        Math.max(marquee.y0, marquee.y1),
      ]
      if (box[2] - box[0] > 0.6 && box[3] - box[1] > 0.6) {
        dispatch(setSelection({ x0: box[0], y0: box[1], x1: box[2], y1: box[3] }))
      }
      setMarquee(null)
    }
    setDrag(null)
  }

  // --- data --------------------------------------------------------------
  const detections = useMemo(() => {
    const list = sheet?.detections || []
    return list.filter(
      (d) =>
        d.confidence >= minConfidence &&
        (categoryFilter.length === 0 || categoryFilter.includes(d.category_key))
    )
  }, [sheet, categoryFilter, minConfidence])

  const runs = sheet?.linear?.runs || []
  const findings = (sheet?.findings || []).filter((f) => f.location_pt && f.status !== 'dismissed')
  const sheetClashes = clashes.filter(
    (c) => c.location_pt && (c.sheet_a === sheet?.sheet_label || c.sheet_b === sheet?.sheet_label)
  )

  const isolatedIds = useMemo(
    () => new Set(sheet?.connectivity?.isolated_runs || []),
    [sheet]
  )

  if (!sheet) return <div className="empty">No sheet selected.</div>

  const S = PT_TO_PX

  return (
    <div
      ref={wrapRef}
      className={`canvas-wrap mode-${spaceHeld ? 'pan' : mode} ${drag ? 'dragging' : ''}`}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <div
        className="canvas-stage"
        style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
      >
        {/* A white plate under the drawing so the sheet has substance while the
            render is in flight, instead of the overlays floating on the dark
            page background. */}
        <div
          style={{
            width: pageW, height: pageH,
            background: imgLoaded ? 'transparent' : '#ffffff',
            position: 'absolute', inset: 0,
          }}
        />
        <img
          src={pageImageUrl(documentId, sheet.page_number, RENDER_DPI)}
          alt={`Sheet ${sheet.sheet_label}`}
          width={pageW}
          height={pageH}
          onLoad={() => { setImgLoaded(true); setImgError(false) }}
          onError={() => setImgError(true)}
          draggable={false}
          style={{ position: 'relative' }}
        />

        <svg width={pageW} height={pageH} viewBox={`0 0 ${pageW} ${pageH}`}>
          {/* --- traced duct / pipe runs --- */}
          {layers.runs &&
            runs.map((r) => {
              const pts = r.points.map(([x, y]) => `${x * S},${y * S}`).join(' ')
              const orphan = isolatedIds.has(r.id)
              return (
                <polyline
                  key={`r${r.id}`}
                  className={`run-line ${selectedRun === r.id ? 'sel' : ''}`}
                  points={pts}
                  stroke={orphan ? 'var(--sev-high)' : sheet.linear?.kind === 'duct' ? '#38bdf8' : '#34d399'}
                  strokeDasharray={orphan ? '5 3' : undefined}
                  onClick={(e) => {
                    e.stopPropagation()
                    dispatch(selectRun(r.id))
                  }}
                >
                  <title>
                    {`Run #${r.id} · ${r.length_label}${r.size_label ? ` · ${r.size_label}` : ''}${
                      r.service_name ? ` · ${r.service_name}` : ''
                    }`}
                  </title>
                </polyline>
              )
            })}

          {/* --- detected components --- */}
          {layers.detections &&
            detections.map((d) => {
              const [x0, y0, x1, y1] = d.bbox_pt
              const color = categoryColor(d.category_key)
              return (
                <rect
                  key={`d${d.id}`}
                  className={`det-box ${selectedDetection === d.id ? 'sel' : ''}`}
                  x={x0 * S - 1}
                  y={y0 * S - 1}
                  width={(x1 - x0) * S + 2}
                  height={(y1 - y0) * S + 2}
                  rx={2}
                  stroke={color}
                  fill={d.review === 'confirmed' ? `${color}22` : 'transparent'}
                  strokeDasharray={d.detector === 'template' ? '4 2' : undefined}
                  onClick={(e) => {
                    e.stopPropagation()
                    dispatch(selectDetection(d.id))
                  }}
                >
                  <title>{`${d.category} · ${Math.round(d.confidence * 100)}%`}</title>
                </rect>
              )
            })}

          {/* --- visual-search matches --- */}
          {layers.matches &&
            searchResult?.instances?.map((m, i) => {
              const [x0, y0, x1, y1] = m.bbox_pt
              return (
                <rect
                  key={`m${i}`}
                  className="match-box"
                  x={x0 * S - 1.5}
                  y={y0 * S - 1.5}
                  width={(x1 - x0) * S + 3}
                  height={(y1 - y0) * S + 3}
                  rx={2}
                />
              )
            })}

          {/* --- validation findings --- */}
          {layers.findings &&
            findings.map((f, i) => {
              const [x0, y0, x1, y1] = f.location_pt
              const cx = ((x0 + x1) / 2) * S
              const cy = ((y0 + y1) / 2) * S
              return (
                <g
                  key={`f${i}`}
                  className="finding-marker"
                  onClick={(e) => {
                    e.stopPropagation()
                    dispatch(focusOn(f.location_pt))
                  }}
                >
                  <circle cx={cx} cy={cy} r={9} fill={SEV_COLOR[f.severity]} fillOpacity={0.22} />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={4}
                    fill={SEV_COLOR[f.severity]}
                    stroke="#0b1120"
                    strokeWidth={1}
                  />
                  <title>{`${f.rule_id} · ${f.message}`}</title>
                </g>
              )
            })}

          {/* --- cross-discipline clashes --- */}
          {layers.clashes &&
            sheetClashes.map((c) => {
              const [x0, y0, x1, y1] = c.location_pt
              const cx = ((x0 + x1) / 2) * S
              const cy = ((y0 + y1) / 2) * S
              return (
                <g key={`c${c.id}`} className="finding-marker">
                  <path
                    d={`M${cx - 8},${cy - 8}L${cx + 8},${cy + 8}M${cx + 8},${cy - 8}L${cx - 8},${cy + 8}`}
                    stroke={SEV_COLOR[c.severity] || '#f43f5e'}
                    strokeWidth={2.4}
                    vectorEffect="non-scaling-stroke"
                  />
                  <title>{c.message}</title>
                </g>
              )
            })}

          {/* --- marquee & calibration --- */}
          {marquee && (
            <rect
              className="marquee"
              x={Math.min(marquee.x0, marquee.x1) * S}
              y={Math.min(marquee.y0, marquee.y1) * S}
              width={Math.abs(marquee.x1 - marquee.x0) * S}
              height={Math.abs(marquee.y1 - marquee.y0) * S}
            />
          )}
          {calib.p1 && (
            <circle cx={calib.p1[0] * S} cy={calib.p1[1] * S} r={4} fill="var(--warn)" />
          )}
          {calib.p1 && calib.p2 && (
            <>
              <line
                x1={calib.p1[0] * S}
                y1={calib.p1[1] * S}
                x2={calib.p2[0] * S}
                y2={calib.p2[1] * S}
                stroke="var(--warn)"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
              <circle cx={calib.p2[0] * S} cy={calib.p2[1] * S} r={4} fill="var(--warn)" />
            </>
          )}
        </svg>
      </div>

      <div className="viewer-toolbar" onPointerDown={(e) => e.stopPropagation()}>
        <button
          className={`icon sm ${mode === 'pan' ? 'primary' : 'ghost'}`}
          onClick={() => dispatch(setMode('pan'))}
          title="Pan (or hold Space / middle-drag from any tool)"
          aria-label="Pan tool"
        >
          ✋
        </button>
        <button
          className={`icon sm ${mode === 'select' ? 'primary' : 'ghost'}`}
          onClick={() => dispatch(setMode(mode === 'select' ? 'pan' : 'select'))}
          title="Find similar symbols — drag a box around one symbol"
          aria-label="Select tool"
        >
          ⬚
        </button>
        <button
          className={`icon sm ${mode === 'calibrate' ? 'primary' : 'ghost'}`}
          onClick={() => dispatch(setMode(mode === 'calibrate' ? 'pan' : 'calibrate'))}
          title="Set the scale by clicking two points"
          aria-label="Calibrate tool"
        >
          📏
        </button>
        <span style={{ width: 1, height: 20, background: 'var(--line)', margin: '0 2px' }} />
        <button className="icon sm ghost" onClick={() => zoomBy(1 / 1.4)} title="Zoom out" aria-label="Zoom out">
          −
        </button>
        <button className="icon sm ghost" onClick={() => zoomBy(1.4)} title="Zoom in" aria-label="Zoom in">
          +
        </button>
        <button className="sm ghost" onClick={fit} title="Fit the sheet to the window">
          Fit
        </button>
      </div>

      {spaceHeld && (
        <div className="viewer-status" style={{ left: 'auto', right: 12 }}>
          ✋ Pan — release Space to return to the {mode} tool
        </div>
      )}

      {!imgLoaded && !imgError && (
        <div className="viewer-hint" style={{ borderColor: 'var(--line)' }}>
          <div className="row">
            <div className="spin" />
            <strong>Rendering sheet…</strong>
          </div>
          <div style={{ marginTop: 4 }}>
            Large sheets take a few seconds, and longer while an analysis is running.
            The traced geometry below is already live.
          </div>
        </div>
      )}
      {imgError && (
        <div className="viewer-hint" style={{ borderColor: 'var(--danger)' }}>
          <strong>Could not render this sheet</strong>
          <div style={{ marginTop: 4 }}>
            The overlays are still accurate. If this persists the server may be low on memory —
            try again once the analysis has finished.
          </div>
          <button
            className="sm"
            style={{ marginTop: 8 }}
            onClick={() => { setImgError(false); setImgLoaded(false) }}
          >
            Retry
          </button>
        </div>
      )}

      <div className="viewer-status">
        <span>{Math.round(transform.scale * 100)}%</span>
        <span className="muted">·</span>
        <span>{detections.length} components</span>
        {runs.length > 0 && (
          <>
            <span className="muted">·</span>
            <span>{runs.length} runs</span>
          </>
        )}
        <span className="muted">·</span>
        <button className="sm ghost" onClick={fit}>
          Fit
        </button>
      </div>

      {mode === 'select' && (
        <div className="viewer-hint">
          <strong>Find similar</strong>
          <div style={{ marginTop: 4 }}>
            Drag a box around a single symbol. Every identical stamp on the sheet is counted
            exactly — the match is on geometry, not appearance.
          </div>
        </div>
      )}
      {mode === 'calibrate' && (
        <div className="viewer-hint">
          <strong>Set the scale</strong>
          <div style={{ marginTop: 4 }}>
            Click two points a known distance apart — a grid line pair or a dimensioned wall —
            then type the real distance in the panel.
          </div>
        </div>
      )}
    </div>
  )
}
