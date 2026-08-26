/*
 * Renders every page against a live backend and asserts it shows real content.
 *
 * Two scenarios matter, and the second is a regression guard:
 *
 *   restored  — project AND document in localStorage, as after an upload
 *   project-only — only the project, as after a page reload or picking a
 *                  project from the dropdown. `setProject` clears the document,
 *                  so without auto-selection every data page silently falls
 *                  back to an empty state and the user "cannot see drawings".
 */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { store } from '../src/store'
import { setDocument, setProject } from '../src/store/uiSlice'
import App from '../src/App'

const PAGES = [
  '/projects', '/dashboard', '/drawings', '/quantities',
  '/review', '/coordination', '/copilot', '/library', '/exports',
]

//: Pages that must show analysed data, and a string proving they did.
const EXPECT = {
  '/dashboard': ['Components detected'],
  '/drawings': ['Sheets ('],
  '/quantities': ['Component'],
  '/review': ['Validation rules'],
  '/exports': ['Download'],
}

const WAIT = Number(process.env.MEPIQ_WAIT_MS) || 1500

async function renderPage(path, errors) {
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
  await new Promise((r) => setTimeout(r, WAIT))
  const text = host.textContent || ''
  root.unmount()
  host.remove()
  return text
}

export async function run(scenario, { pid, did } = {}) {
  const errors = []
  const orig = console.error
  console.error = (...a) => { errors.push(a.map(String).join(' ')) }
  let failures = 0

  // setProject always clears the document, which is precisely the state a page
  // reload leaves behind. Dispatching rather than seeding localStorage also
  // sidesteps the fact that the store reads storage once, at import.
  store.dispatch(setProject(pid))
  if (did) store.dispatch(setDocument(did))

  orig(`\n--- scenario: ${scenario} ---`)

  for (const path of PAGES) {
    const text = await renderPage(path, errors)
    const bad = errors.filter((e) => !/not wrapped in act|Warning:|validateDOMNesting/.test(e))

    const want = EXPECT[path] || []
    const missing = want.filter((w) => !text.includes(w))

    // An empty state on a data page is the exact symptom of the bug this
    // harness exists to catch, so call it out by name rather than as "short".
    const emptied = want.length > 0 && /No drawing set selected|Not analysed yet|No drawing set open/.test(text)

    const ok = bad.length === 0 && missing.length === 0 && !emptied
    if (!ok) failures += 1

    let note = ''
    if (bad.length) note = `\n      react error: ${bad[0].slice(0, 300)}`
    else if (emptied) note = `\n      showed an EMPTY STATE — no document was selected`
    else if (missing.length) note = `\n      missing expected content: ${missing.join(', ')}`

    orig(`${ok ? ' OK ' : 'FAIL'} ${path.padEnd(14)} chars=${String(text.length).padStart(5)}${note}`)
  }

  console.error = orig
  return failures
}
