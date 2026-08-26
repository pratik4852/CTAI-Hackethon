import React, { useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import {
  useAnalyseMutation,
  useCreateProjectMutation,
  useDeleteProjectMutation,
  useProjectQuery,
  useProjectsQuery,
  useUploadDocumentsMutation,
} from '../store/api'
import { setDocument, setJob, setProject, toast } from '../store/uiSlice'
import { bytes, num, timeAgo } from '../lib/format'

function UploadCard({ project }) {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [over, setOver] = useState(false)
  const [upload, { isLoading: uploading }] = useUploadDocumentsMutation()
  const [analyse, { isLoading: starting }] = useAnalyseMutation()
  const [maxSheets, setMaxSheets] = useState(8)
  const [onlyPlans, setOnlyPlans] = useState(true)
  const [doClash, setDoClash] = useState(true)

  const handleFiles = async (files) => {
    const list = [...files].filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (!list.length) {
      dispatch(toast({ kind: 'error', message: 'Only PDF drawing sets are supported.' }))
      return
    }
    try {
      const res = await upload({ projectId: project.id, files: list }).unwrap()
      dispatch(setDocument(res.documents[0].id))
      dispatch(toast({ message: `Uploaded ${list.length} file(s).` }))
    } catch (e) {
      dispatch(toast({ kind: 'error', message: e?.data?.detail || 'Upload failed' }))
    }
  }

  const run = async (documentId) => {
    try {
      const res = await analyse({
        projectId: project.id,
        document_id: documentId,
        max_sheets: Number(maxSheets),
        only_plans: onlyPlans,
        clash: doClash,
      }).unwrap()
      dispatch(setDocument(res.document_id))
      dispatch(setJob(res.job.id))
      navigate('/dashboard')
    } catch (e) {
      dispatch(toast({ kind: 'error', message: e?.data?.detail || 'Could not start the analysis' }))
    }
  }

  return (
    <div className="card">
      <h3>Drawing sets</h3>
      <p className="hint">
        Drop a vector PDF — a full bid set is fine. MEPIQ triages the pages, works out which are
        MEP plans, and analyses those.
      </p>

      <div
        className={`dropzone ${over ? 'over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          handleFiles(e.dataTransfer.files)
        }}
        onClick={() => inputRef.current?.click()}
        style={{ cursor: 'pointer' }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => handleFiles(e.target.files)}
        />
        {uploading ? (
          <div className="row" style={{ justifyContent: 'center' }}>
            <div className="spin" /> Uploading…
          </div>
        ) : (
          <>
            <div style={{ fontSize: 22, marginBottom: 6 }}>↥</div>
            <div style={{ color: 'var(--text)', fontWeight: 550 }}>
              Drop drawings here, or click to browse
            </div>
            <div className="small" style={{ marginTop: 4 }}>
              Mechanical, plumbing, fire protection and electrical PDFs
            </div>
          </>
        )}
      </div>

      {project.documents?.length > 0 && (
        <>
          <div className="row wrap" style={{ marginTop: 16, gap: 14 }}>
            <label className="field" style={{ width: 130 }}>
              Sheets to analyse
              <input
                type="number"
                min="1"
                max="60"
                value={maxSheets}
                onChange={(e) => setMaxSheets(e.target.value)}
              />
            </label>
            <label className="row small" style={{ gap: 6, marginTop: 18 }}>
              <input
                type="checkbox"
                checked={onlyPlans}
                onChange={(e) => setOnlyPlans(e.target.checked)}
                style={{ width: 'auto' }}
              />
              Plans only (skip schedules and details)
            </label>
            <label className="row small" style={{ gap: 6, marginTop: 18 }}>
              <input
                type="checkbox"
                checked={doClash}
                onChange={(e) => setDoClash(e.target.checked)}
                style={{ width: 'auto' }}
              />
              Cross-discipline clash screen
            </label>
          </div>

          <div className="table-wrap" style={{ marginTop: 12, maxHeight: 320 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>File</th>
                  <th className="num">Pages</th>
                  <th className="num">Size</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {project.documents.map((d) => (
                  <tr key={d.id}>
                    <td>{d.file_name}</td>
                    <td className="num">{d.page_count}</td>
                    <td className="num">{bytes(d.size_bytes)}</td>
                    <td>
                      {d.has_result ? (
                        <span className="badge ok">Analysed</span>
                      ) : (
                        <span className="badge">Not analysed</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="sm primary" disabled={starting} onClick={() => run(d.id)}>
                        {d.has_result ? 'Re-analyse' : 'Analyse'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

export default function Projects() {
  const dispatch = useDispatch()
  const { projectId } = useSelector((s) => s.ui)
  const { data: projects, isLoading } = useProjectsQuery()
  const { data: project } = useProjectQuery(projectId, { skip: !projectId })
  const [create] = useCreateProjectMutation()
  const [remove] = useDeleteProjectMutation()
  const [name, setName] = useState('')

  const makeProject = async () => {
    const n = name.trim() || `Project ${new Date().toLocaleDateString()}`
    const p = await create({ name: n }).unwrap()
    dispatch(setProject(p.id))
    setName('')
  }

  return (
    <div className="page">
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="card">
          <h3>Projects</h3>
          <p className="hint">A project holds one building's drawing sets across all trades.</p>

          <div className="row" style={{ marginBottom: 14 }}>
            <input
              placeholder="New project name…"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && makeProject()}
            />
            <button className="primary" onClick={makeProject}>
              Create
            </button>
          </div>

          {isLoading && <div className="spin" />}
          {projects?.length === 0 && (
            <div className="small muted">No projects yet — create one to get started.</div>
          )}

          {projects?.map((p) => (
            <div
              key={p.id}
              className={`list-item ${p.id === projectId ? 'active' : ''}`}
              onClick={() => dispatch(setProject(p.id))}
            >
              <div className="row">
                <span className="t">{p.name}</span>
                <span className="spacer" />
                <span className="badge">{p.status}</span>
                <button
                  className="sm ghost danger"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm(`Delete “${p.name}” and its drawings?`)) {
                      remove(p.id)
                      if (p.id === projectId) dispatch(setProject(null))
                    }
                  }}
                  title="Delete project"
                >
                  ✕
                </button>
              </div>
              <div className="s">
                {p.documents?.length || 0} drawing set(s) · updated {timeAgo(p.updated_at)}
              </div>
            </div>
          ))}
        </div>

        {project ? (
          <UploadCard project={project} />
        ) : (
          <div className="card">
            <h3>Getting started</h3>
            <p className="hint">Create or select a project on the left, then upload drawings.</p>
            <ol className="small" style={{ color: 'var(--text-2)', paddingLeft: 18, lineHeight: 1.9 }}>
              <li>Upload a mechanical, plumbing or electrical PDF.</li>
              <li>MEPIQ reads the drawing's own vector geometry — no image guessing.</li>
              <li>
                You get counts, measured duct and pipe lengths, design findings and a bill of
                quantities, each traceable back to the geometry on the sheet.
              </li>
              <li>Ask the copilot anything about the set.</li>
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
