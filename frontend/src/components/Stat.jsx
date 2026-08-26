import React from 'react'

export function Stat({ label, value, unit, sub, tone }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value" style={tone ? { color: tone } : undefined}>
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export function BarList({ rows, max, colorFor, valueFor, labelFor }) {
  const top = max || Math.max(1, ...rows.map(valueFor))
  return (
    <div>
      {rows.map((r, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <div className="bar-row">
            <div className="bar-label">
              <span className="dot" style={{ width: 8, height: 8, borderRadius: 2, background: colorFor(r), flex: 'none' }} />
              <span>{labelFor(r)}</span>
            </div>
            <div className="tnum small" style={{ textAlign: 'right' }}>
              {valueFor(r).toLocaleString()}
            </div>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{ width: `${(valueFor(r) / top) * 100}%`, background: colorFor(r) }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
