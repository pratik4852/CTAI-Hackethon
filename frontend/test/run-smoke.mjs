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
// Seed the app with a real, analysed project so pages render actual content.
if (process.env.MEPIQ_PID) {
  dom.window.localStorage.setItem('mepiq.projectId', JSON.stringify(process.env.MEPIQ_PID))
  dom.window.localStorage.setItem('mepiq.documentId', JSON.stringify(process.env.MEPIQ_DID))
}

const realFetch = globalThis.fetch
globalThis.fetch = (input, init) => {
  const url = typeof input === 'string' ? input : input.url
  return realFetch(url.startsWith('/') ? API + url : url, init)
}

const { run } = await import('./smoke-bundle.mjs')
const failures = await run()
console.log(failures ? `\n${failures} page(s) failed to render.` : '\nAll pages rendered without errors.')
process.exit(failures ? 1 : 0)
