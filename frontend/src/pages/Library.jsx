import React from 'react'
import { useDispatch } from 'react-redux'
import { useCatalogueQuery, useForgetGlyphMutation, useLibraryQuery } from '../store/api'
import { toast } from '../store/uiSlice'
import { categoryColor } from '../lib/format'

export default function Library() {
  const dispatch = useDispatch()
  const { data: catalogue } = useCatalogueQuery()
  const { data: library } = useLibraryQuery()
  const [forget] = useForgetGlyphMutation()

  return (
    <div className="page">
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="card">
          <h3>Component catalogue</h3>
          <p className="hint">
            Each of these is detected from its geometric definition rather than from training
            images — which is why a detection can explain itself, and why it works at any scale or
            rotation.
          </p>
          {(catalogue?.symbols || []).map((s) => (
            <div key={s.key} style={{ padding: '10px 0', borderBottom: '1px solid var(--line-soft)' }}>
              <div className="row">
                <span
                  style={{ width: 9, height: 9, borderRadius: 2, background: categoryColor(s.key) }}
                />
                <strong style={{ fontSize: 13 }}>{s.name}</strong>
                <span className="spacer" />
                <span className="badge">{s.category}</span>
                <span className="badge brand">{s.unit}</span>
              </div>
              <div className="small muted" style={{ marginTop: 4 }}>
                {s.description}
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Learned symbols</h3>
          <p className="hint">
            Symbols a reviewer has named. Because the match is on exact geometry, one naming makes
            every occurrence countable on every drawing from the same office — the tool adapts to
            your drawing conventions instead of the other way round.
          </p>

          {(library?.glyphs || []).length === 0 ? (
            <div className="small muted" style={{ padding: '14px 0' }}>
              Nothing learned yet. On the Drawings page, use <strong>Find similar symbols</strong> to
              select a symbol and name it — or name one from the Review page's suggestions.
            </div>
          ) : (
            <div className="table-wrap" style={{ maxHeight: '58vh' }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Trade</th>
                    <th className="num">Size (pt)</th>
                    <th className="num">Confirmations</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {library.glyphs.map((g) => (
                    <tr key={g.glyph_id}>
                      <td>
                        <strong>{g.label}</strong>
                        <div className="mono small muted">{g.glyph_id}</div>
                      </td>
                      <td className="small">{g.trade || '—'}</td>
                      <td className="num mono small">
                        {g.size_pt ? `${g.size_pt[0]} × ${g.size_pt[1]}` : '—'}
                      </td>
                      <td className="num">{g.confirmations}</td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="sm ghost danger"
                          onClick={() => {
                            forget(g.glyph_id)
                            dispatch(toast({ message: `Removed “${g.label}” from the library.` }))
                          }}
                        >
                          Forget
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
