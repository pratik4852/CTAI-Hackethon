import React from 'react'
import { Link } from 'react-router-dom'

export default function EmptyState({ title, hint, action, to = '/projects' }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{hint}</p>
      {action !== false && (
        <Link className="btn primary" to={to}>
          Go to Projects
        </Link>
      )}
    </div>
  )
}
