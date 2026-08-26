import React, { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { API_BASE, api } from '../store/api'
import { setJob, setJobProgress, toast } from '../store/uiSlice'

/**
 * Live analysis progress.
 *
 * The backend streams stage updates over SSE, so the user sees the actual work
 * — "tracing ductwork on M-3.1" — instead of an indeterminate spinner. A drawing
 * set can take a minute; knowing what it is doing is the difference between
 * waiting and wondering.
 */
export default function JobProgress() {
  const dispatch = useDispatch()
  const { jobId, jobProgress } = useSelector((s) => s.ui)

  useEffect(() => {
    if (!jobId) return undefined
    const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/stream`)
    source.onmessage = (e) => {
      let job
      try {
        job = JSON.parse(e.data)
      } catch {
        return
      }
      dispatch(setJobProgress(job))
      if (job.status === 'succeeded') {
        source.close()
        dispatch(api.util.invalidateTags(['Result', 'Project']))
        dispatch(toast({ message: job.message || 'Analysis complete' }))
        setTimeout(() => dispatch(setJob(null)), 2500)
      } else if (job.status === 'failed') {
        source.close()
        dispatch(toast({ kind: 'error', message: `Analysis failed: ${job.message}`, ms: 9000 }))
        setTimeout(() => dispatch(setJob(null)), 400)
      }
    }
    source.onerror = () => source.close()
    return () => source.close()
  }, [jobId, dispatch])

  if (!jobId || !jobProgress) return null
  const pct = Math.round((jobProgress.progress || 0) * 100)

  return (
    <div className="row" style={{ minWidth: 320, gap: 10 }}>
      <div className="spin" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="small" style={{ display: 'flex', gap: 8 }}>
          <span
            style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              color: 'var(--text-2)',
            }}
          >
            {jobProgress.message}
          </span>
          <span className="muted tnum" style={{ marginLeft: 'auto' }}>
            {pct}%
          </span>
        </div>
        <div className="progress" style={{ marginTop: 4 }}>
          <div style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  )
}
