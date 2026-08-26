import React from 'react'
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

      {docs.length > 1 && (
        <select
          value={activeDoc}
          onChange={(e) => dispatch(setDocument(e.target.value))}
          style={{ width: 220 }}
          aria-label="Drawing set"
        >
          {docs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.file_name} {d.has_result ? '' : '(not analysed)'}
            </option>
          ))}
        </select>
      )}
    </header>
  )
}
