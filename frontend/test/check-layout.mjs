/*
 * Layout invariants the jsdom smoke test cannot check.
 *
 * jsdom does no layout at all: it happily reports textContent for an element
 * whose computed height is zero. That is precisely how a collapsed drawing
 * canvas passed nine green checks while showing the user an empty rectangle.
 *
 * These are cheap static assertions over the source. They cannot replace a real
 * browser, but they do pin the specific structural rules that, when broken,
 * make the viewer silently render nothing.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const css = readFileSync(join(root, 'src/styles.css'), 'utf8')
const drawings = readFileSync(join(root, 'src/pages/Drawings.jsx'), 'utf8')
const canvas = readFileSync(join(root, 'src/components/SheetCanvas.jsx'), 'utf8')

const rule = (selector) => {
  const m = css.match(new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`))
  return m ? m[1] : ''
}

const checks = [
  {
    name: '.canvas-wrap has a definite height',
    why: 'all its children are absolutely positioned, so without one it collapses to 0px and overflow:hidden hides the whole viewer',
    pass: () => {
      const body = rule('.canvas-wrap')
      return /height:\s*100%/.test(body) || /flex:\s*1/.test(body)
    },
  },
  {
    name: '.canvas-wrap keeps a minimum height',
    why: 'a floor means a layout mistake degrades to a small canvas rather than an invisible one',
    pass: () => /min-height:\s*\d/.test(rule('.canvas-wrap')),
  },
  {
    name: 'Drawings.jsx wraps the canvas in .canvas-column',
    why: 'the flex column is what gives .canvas-wrap a height to fill',
    pass: () => /className="canvas-column"/.test(drawings),
  },
  {
    name: '.canvas-column is a flex column',
    pass: () => {
      const body = rule('.canvas-column')
      return /display:\s*flex/.test(body) && /flex-direction:\s*column/.test(body)
    },
  },
  {
    name: 'the view fits without waiting for the rendered image',
    why: 'a slow or failed render must not leave the stage at scale 1 pinned to the origin',
    pass: () => /if \(pageW && pageH && size\.w > 0\) fit\(\)/.test(canvas),
  },
  {
    name: 'image load state resets when the sheet changes',
    why: 'otherwise the previous sheet\'s "loaded" carries over and the spinner never shows',
    pass: () => /setImgLoaded\(false\)[\s\S]{0,80}\[documentId, sheet\?\.page_number\]/.test(canvas),
  },
  {
    name: 'a failed render is reported to the user',
    why: 'a blank canvas with no message is indistinguishable from a broken app',
    pass: () => /onError=\{\(\) => setImgError\(true\)\}/.test(canvas) && /Could not render this sheet/.test(canvas),
  },
]

let failed = 0
for (const c of checks) {
  let ok = false
  try { ok = c.pass() } catch { ok = false }
  if (!ok) failed += 1
  console.log(`${ok ? ' OK ' : 'FAIL'} ${c.name}${ok || !c.why ? '' : `\n      ${c.why}`}`)
}

console.log(failed ? `\n${failed} layout invariant(s) broken.` : '\nAll layout invariants hold.')
process.exit(failed ? 1 : 0)
