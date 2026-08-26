import React, { useEffect } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { useHealthQuery } from './store/api'
import { toast, toggleTheme } from './store/uiSlice'
import ProjectBar from './components/ProjectBar'
import Projects from './pages/Projects'
import Dashboard from './pages/Dashboard'
import Drawings from './pages/Drawings'
import Quantities from './pages/Quantities'
import Review from './pages/Review'
import Coordination from './pages/Coordination'
import Copilot from './pages/Copilot'
import Exports from './pages/Exports'
import Library from './pages/Library'

const NAV = [
  { to: '/projects', label: 'Projects', icon: '◧' },
  { to: '/dashboard', label: 'Dashboard', icon: '▤' },
  { to: '/drawings', label: 'Drawings', icon: '◈' },
  { to: '/quantities', label: 'Quantities', icon: '∑' },
  { to: '/review', label: 'Review', icon: '⚑' },
  { to: '/coordination', label: 'Coordination', icon: '⧉' },
  { to: '/copilot', label: 'Copilot', icon: '✦' },
  { to: '/library', label: 'Library', icon: '⌘' },
  { to: '/exports', label: 'Exports', icon: '↧' },
]

function Toast() {
  const t = useSelector((s) => s.ui.toast)
  const dispatch = useDispatch()
  useEffect(() => {
    if (!t) return undefined
    const id = setTimeout(() => dispatch(toast(null)), t.ms || 4200)
    return () => clearTimeout(id)
  }, [t, dispatch])
  if (!t) return null
  return <div className={`toast ${t.kind === 'error' ? 'error' : ''}`}>{t.message}</div>
}

export default function App() {
  const theme = useSelector((s) => s.ui.theme)
  const dispatch = useDispatch()
  const { data: health } = useHealthQuery(undefined, { pollingInterval: 60000 })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">MQ</div>
          <div>
            <div className="brand-name">MEPIQ</div>
            <div className="brand-sub">Drawing intelligence</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? 'active' : '')}>
              <span aria-hidden style={{ width: 16, textAlign: 'center', opacity: 0.75 }}>
                {n.icon}
              </span>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span>v{health?.version || '1.0.0'}</span>
            <button className="sm ghost" onClick={() => dispatch(toggleTheme())} title="Toggle theme">
              {theme === 'dark' ? '☾' : '☀'}
            </button>
          </div>
          <div style={{ marginTop: 6 }}>
            {health ? (
              <span className={`badge ${health.llm_enabled ? 'ok' : ''}`}>
                {health.llm_enabled ? `LLM · ${health.llm_model}` : 'Rule-based copilot'}
              </span>
            ) : (
              <span className="badge">connecting…</span>
            )}
          </div>
        </div>
      </aside>

      <div className="main">
        <ProjectBar />
        <div className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/projects" replace />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/drawings" element={<Drawings />} />
            <Route path="/quantities" element={<Quantities />} />
            <Route path="/review" element={<Review />} />
            <Route path="/coordination" element={<Coordination />} />
            <Route path="/copilot" element={<Copilot />} />
            <Route path="/library" element={<Library />} />
            <Route path="/exports" element={<Exports />} />
            <Route path="*" element={<Navigate to="/projects" replace />} />
          </Routes>
        </div>
      </div>

      <Toast />
    </div>
  )
}
