import React, { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useLocation } from 'react-router-dom'
import { useProjectQuery, useProjectsQuery } from '../store/api'
import { setDocument, setProject } from '../store/uiSlice'
import JobProgress from './JobProgress'

const TITLES = {
  '/projects': 'Projects',
  '/dashboard': 'Project dashboard',
  '/drawings': 'Drawing review',
  '/quantities': 'Quantity takeoff',
  '/review': 'Design validation',
  '/coordination': 'Cross-discipline coordination',
  '/copilot': 'Engineering copilot',
  '/library': 'Component library',
  '/exports': 'Structured exports',
}

export default function ProjectBar() {
  const dispatch = useDispatch()
  const { pathname } = useLocation()
  const { projectId, documentId } = useSelector((s) => s.ui)
  const { data: projects } = useProjectsQuery()
  const { data: project } = useProjectQuery(projectId, { skip: !projectId })

  const docs = project?.documents || []
  const activeDoc = documentId || docs.find((d) => d.has_result)?.id || docs[0]?.id || ''

  // Selecting a project — or simply reloading the page — clears the chosen
  // document. Without this the app would sit on an empty state with no visible
  // way out, because the picker below only appears once a project holds more
  // than one drawing set. Preferring an analysed document means the user lands
  // on something worth looking at.
  useEffect(() => {
    if (projectId && !documentId && activeDoc) {
      dispatch(setDocument(activeDoc))
    }
  }, [projectId, documentId, activeDoc, dispatch])

  return (
    <header className="topbar">
      <h1>{TITLES[pathname] || 'MEPIQ'}</h1>

      <div className="spacer" />

      <JobProgress />

      {projects?.length > 0 && (
        <select
          value={projectId || ''}
          onChange={(e) => dispatch(setProject(e.target.value || null))}
          style={{ width: 210 }}
          aria-label="Project"
        >
          <option value="">Select a project…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}

      {docs.length > 0 && (
        <select
          value={activeDoc}
          onChange={(e) => dispatch(setDocument(e.target.value))}
          style={{ width: 240 }}
          aria-label="Drawing set"
          title="Drawing set"
        >
          {docs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.file_name}
              {d.has_result ? '' : ' — not analysed'}
            </option>
          ))}
        </select>
      )}
    </header>
  )
}
