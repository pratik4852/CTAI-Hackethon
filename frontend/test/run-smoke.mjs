/*
 * jsdom harness for the smoke test.
 *
 *   MEPIQ_PID=prj_x MEPIQ_DID=doc_y node test/run-smoke.mjs
 *
 * Runs two scenarios: with a document already selected, and with only a project
 * selected (the state after a page reload). Both must render real data.
 */
import { JSDOM } from 'jsdom'

const API = process.env.MEPIQ_API || 'http://127.0.0.1:8000'
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true,
})
for (const k of ['window','document','HTMLElement','Element','Node','SVGElement','getComputedStyle','localStorage','Image','MouseEvent','Event','CustomEvent','DOMParser']) {
  try { globalThis[k] = dom.window[k] } catch { /* read-only in this runtime */ }
}
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true })
globalThis.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0)
globalThis.cancelAnimationFrame = clearTimeout
globalThis.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} }
globalThis.EventSource = class { constructor(){ this.readyState = 0 } close(){} }
globalThis.matchMedia = () => ({ matches: false, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){} })
globalThis.IS_REACT_ACT_ENVIRONMENT = false

const realFetch = globalThis.fetch
globalThis.fetch = (input, init) => {
  const url = typeof input === 'string' ? input : input.url
  return realFetch(url.startsWith('/') ? API + url : url, init)
}

const PID = process.env.MEPIQ_PID
const DID = process.env.MEPIQ_DID
if (!PID) {
  console.error('Set MEPIQ_PID (and ideally MEPIQ_DID) to an analysed project.')
  process.exit(2)
}

const { run } = await import('./smoke-bundle.mjs')

let failures = 0

// 1. Both ids set — the state right after an upload and analysis.
failures += await run('restored (project + document)', { pid: PID, did: DID })

// 2. Project only — the state after a reload, or after picking a project from
//    the dropdown, since setProject clears the document. This is the case that
//    made the drawings disappear.
failures += await run('project only (page reload)', { pid: PID })

console.log(failures ? `\n${failures} page render(s) failed.` : '\nAll pages rendered real data in both scenarios.')
process.exit(failures ? 1 : 0)
