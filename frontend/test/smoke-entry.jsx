/* Renders every page against a live backend and reports any React error. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { store } from '../src/store'
import App from '../src/App'

const PAGES = [
  '/projects', '/dashboard', '/drawings', '/quantities',
  '/review', '/coordination', '/copilot', '/library', '/exports',
]

export async function run() {
  const errors = []
  const orig = console.error
  console.error = (...a) => { errors.push(a.map(String).join(' ')) }
  let failures = 0

  for (const path of PAGES) {
    errors.length = 0
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    root.render(
      <Provider store={store}>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </Provider>
    )
    await new Promise((r) => setTimeout(r, Number(process.env.MEPIQ_WAIT_MS) || 1200))
    const text = host.textContent || ''
    const bad = errors.filter((e) => !/not wrapped in act|Warning:|validateDOMNesting/.test(e))
    if (bad.length) failures += 1
    orig(
      `${bad.length ? 'FAIL' : ' OK '} ${path.padEnd(14)} chars=${String(text.length).padStart(5)}` +
      (process.env.MEPIQ_DUMP ? `\n      ${text.replace(/\s+/g, ' ').slice(0, 340)}` : '') +
      (bad.length ? `\n      ${bad[0].slice(0, 400)}` : '')
    )
    root.unmount()
    host.remove()
  }
  console.error = orig
  return failures
}
