import React from 'react'
import { useSelector } from 'react-redux'
import { exportUrl, useResultQuery } from '../store/api'
import EmptyState from '../components/EmptyState'

const EXPORTS = [
  {
    kind: 'coco',
    title: 'Detections — COCO JSON',
    desc: 'Instance annotations in the dataset\'s own format, at 150 DPI, so results drop straight into an existing evaluation harness.',
    tag: 'Level 1',
  },
  {
    kind: 'counts',
    title: 'Component counts — CSV',
    desc: 'Per-sheet counts of every detected component with mean confidence.',
    tag: 'Level 1',
  },
  {
    kind: 'detections',
    title: 'Detections — CSV',
    desc: 'Every instance with its location, confidence, detector and the reason it was identified.',
    tag: 'Level 1',
  },
  {
    kind: 'runs',
    title: 'Linear runs — CSV',
    desc: 'Traced duct and pipe runs with measured length, size, service and location.',
    tag: 'Level 2',
  },
  {
    kind: 'boq',
    title: 'Bill of quantities — CSV',
    desc: 'Priceable line items rolled up across the set: components by type, ductwork and piping by size.',
    tag: 'Takeoff',
  },
  {
    kind: 'findings',
    title: 'Design findings — CSV',
    desc: 'Validation and constructability findings with severity, location and recommendation.',
    tag: 'Level 4',
  },
  {
    kind: 'clashes',
    title: 'Clash report — CSV',
    desc: 'Cross-discipline conflicts with the elements involved and the encroachment.',
    tag: 'Level 4',
  },
  {
    kind: 'issues',
    title: 'Issues — BCF-shaped JSON',
    desc: 'Findings and clashes as coordination topics for issue trackers and BIM tools.',
    tag: 'Level 4',
  },
  {
    kind: 'ifc',
    title: 'IFC4 model',
    desc: 'Detected components and traced runs placed in plan as IFC entities — opens in Revit, Navisworks or Solibri as a coordination underlay.',
    tag: 'Level 4',
  },
  {
    kind: 'result',
    title: 'Full analysis — JSON',
    desc: 'Everything the engine produced, including geometry, scale provenance and rationales.',
    tag: 'All',
  },
]

export default function Exports() {
  const { documentId } = useSelector((s) => s.ui)
  const { data } = useResultQuery(documentId, { skip: !documentId })

  if (!documentId) return <EmptyState title="No drawing set selected" hint="Analyse a drawing set first." />
  if (!data) return <EmptyState title="Not analysed yet" hint="Run the analysis on this drawing set." />

  return (
    <div className="page">
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Structured output</h3>
        <p className="hint" style={{ margin: 0 }}>
          A takeoff is only useful if it flows into the next tool. Every artefact below is written
          to be opened directly by the thing that needs it — no reformatting step.
        </p>
      </div>

      <div className="grid cols-2">
        {EXPORTS.map((e) => (
          <div key={e.kind} className="card">
            <div className="row" style={{ marginBottom: 6 }}>
              <strong style={{ fontSize: 13.5 }}>{e.title}</strong>
              <span className="spacer" />
              <span className="badge brand">{e.tag}</span>
            </div>
            <div className="small muted" style={{ minHeight: 42 }}>
              {e.desc}
            </div>
            <a className="btn primary sm" style={{ marginTop: 10 }} href={exportUrl(documentId, e.kind)}>
              ↧ Download
            </a>
          </div>
        ))}
      </div>
    </div>
  )
}
