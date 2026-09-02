/**
 * Generates "MEPIQ — User Manual & Technical Guide" as a .docx.
 *
 *   cd docs && npm install docx && node build_manual.js
 *
 * Everything in the document is drawn from the built system: measured numbers
 * come from backend/evaluate_dataset.py, behaviours from the test suite.
 */

const fs = require('fs')
const {
  AlignmentType, BorderStyle, Document, Footer, Header, HeadingLevel, LevelFormat,
  PageBreak, PageNumber, Packer, Paragraph, ShadingType, Table, TableCell, TableRow,
  TextRun, WidthType, TableOfContents, ExternalHyperlink,
} = require('docx')

// ---------------------------------------------------------------------------
// Page geometry — US Letter, 0.75" margins
// ---------------------------------------------------------------------------
const PAGE_W = 12240
const MARGIN = 1080
const CONTENT_W = PAGE_W - MARGIN * 2   // 10080 DXA

const INK = '1A1A1A'
const MUTED = '5A6472'
const BRAND = '0B6FA4'
const ACCENT = '117A5B'
const WARN = 'A6631B'
const RULE = 'D6DEE8'

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

const h1 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 420, after: 160 },
    children: [new TextRun({ text, bold: true, size: 32, color: BRAND })],
  })

const h2 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 300, after: 110 },
    children: [new TextRun({ text, bold: true, size: 25, color: INK })],
  })

const h3 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 220, after: 80 },
    children: [new TextRun({ text, bold: true, size: 22, color: MUTED })],
  })

/** Body paragraph. `parts` may be a string or an array of {t, b, i, c, mono}. */
const p = (parts, opts = {}) => {
  const arr = typeof parts === 'string' ? [{ t: parts }] : parts
  return new Paragraph({
    spacing: { after: opts.after ?? 120, line: 276 },
    indent: opts.indent ? { left: opts.indent } : undefined,
    alignment: opts.align,
    children: arr.map(
      (r) =>
        new TextRun({
          text: r.t,
          bold: r.b,
          italics: r.i,
          color: r.c || INK,
          size: opts.size ?? 21,
          font: r.mono ? 'Consolas' : undefined,
        })
    ),
  })
}

const bullet = (parts, level = 0) => {
  const arr = typeof parts === 'string' ? [{ t: parts }] : parts
  return new Paragraph({
    numbering: { reference: 'dot-list', level },
    spacing: { after: 70, line: 270 },
    children: arr.map(
      (r) => new TextRun({ text: r.t, bold: r.b, italics: r.i, color: r.c || INK, size: 21, font: r.mono ? 'Consolas' : undefined })
    ),
  })
}

// Each ordered list needs its own numbering instance, otherwise every list in
// the document shares one counter and the second one starts at 9.
let _numInstance = 0
const newList = () => (_numInstance += 1)

const step = (parts, level = 0, instance = _numInstance) => {
  const arr = typeof parts === 'string' ? [{ t: parts }] : parts
  return new Paragraph({
    numbering: { reference: 'num-list', level, instance },
    spacing: { after: 70, line: 270 },
    children: arr.map(
      (r) => new TextRun({ text: r.t, bold: r.b, italics: r.i, color: r.c || INK, size: 21, font: r.mono ? 'Consolas' : undefined })
    ),
  })
}

const code = (lines) =>
  new Paragraph({
    spacing: { before: 90, after: 130 },
    shading: { type: ShadingType.CLEAR, fill: 'F2F5F8' },
    border: {
      left: { style: BorderStyle.SINGLE, size: 12, color: BRAND, space: 8 },
      top: { style: BorderStyle.SINGLE, size: 2, color: RULE, space: 6 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE, space: 6 },
      right: { style: BorderStyle.SINGLE, size: 2, color: RULE, space: 6 },
    },
    children: (Array.isArray(lines) ? lines : [lines]).flatMap((l, i) => [
      ...(i ? [new TextRun({ break: 1 })] : []),
      new TextRun({ text: l, font: 'Consolas', size: 18, color: '17384F' }),
    ]),
  })

/** A highlighted note. `kind` picks the accent colour. */
const callout = (label, text, kind = 'brand') => {
  const colour = kind === 'warn' ? WARN : kind === 'ok' ? ACCENT : BRAND
  const fill = kind === 'warn' ? 'FDF6EC' : kind === 'ok' ? 'EDF7F2' : 'EEF5FA'
  return new Paragraph({
    spacing: { before: 110, after: 150 },
    shading: { type: ShadingType.CLEAR, fill },
    border: {
      left: { style: BorderStyle.SINGLE, size: 18, color: colour, space: 10 },
      top: { style: BorderStyle.SINGLE, size: 2, color: fill, space: 8 },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: fill, space: 8 },
      right: { style: BorderStyle.SINGLE, size: 2, color: fill, space: 8 },
    },
    children: [
      new TextRun({ text: `${label}  `, bold: true, size: 20, color: colour }),
      new TextRun({ text, size: 20, color: INK }),
    ],
  })
}

const cell = (content, { width, bold, fill, align, mono, size } = {}) =>
  new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { type: ShadingType.CLEAR, fill } : undefined,
    margins: { top: 90, bottom: 90, left: 130, right: 130 },
    children: (Array.isArray(content) ? content : [content]).map(
      (line) =>
        new Paragraph({
          alignment: align,
          spacing: { after: 0, line: 250 },
          children: [
            new TextRun({
              text: String(line),
              bold,
              size: size ?? 19,
              color: INK,
              font: mono ? 'Consolas' : undefined,
            }),
          ],
        })
    ),
  })

/**
 * Table with header row. `widths` must sum to CONTENT_W.
 * Both columnWidths and per-cell width are set — percentage widths break in
 * Google Docs, and omitting either makes columns collapse.
 */
const table = (headers, rows, widths, opts = {}) =>
  new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      left: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
      right: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: RULE },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((htxt, i) =>
          cell(htxt, { width: widths[i], bold: true, fill: 'EDF2F7', size: 18 })
        ),
      }),
      ...rows.map(
        (r) =>
          new TableRow({
            children: r.map((c, i) =>
              cell(c, {
                width: widths[i],
                mono: opts.monoCols?.includes(i),
                bold: opts.boldCols?.includes(i),
                align: opts.rightCols?.includes(i) ? AlignmentType.RIGHT : undefined,
              })
            ),
          })
      ),
    ],
  })

const spacer = (h = 120) => new Paragraph({ spacing: { after: h }, children: [] })
const pageBreak = () => new Paragraph({ children: [new PageBreak()] })

const divider = () =>
  new Paragraph({
    spacing: { before: 100, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: RULE, space: 4 } },
    children: [],
  })

// A consistent way to present each screen of the app.
const feature = ({ title, what, why, how, judge }) => {
  const out = [h2(title)]
  out.push(p([{ t: 'What it is. ', b: true }, { t: what }]))
  out.push(p([{ t: 'Why it exists. ', b: true }, { t: why }]))
  if (how && how.length) {
    out.push(p([{ t: 'How to use it', b: true }], { after: 60 }))
    const inst = newList()
    how.forEach((s) => out.push(step(s, 0, inst)))
  }
  if (judge) out.push(callout('Say this to the judges:', judge))
  return out
}

// ---------------------------------------------------------------------------
// Document content
// ---------------------------------------------------------------------------

const children = []

// ---- Cover ---------------------------------------------------------------
children.push(
  new Paragraph({ spacing: { before: 2600, after: 0 }, children: [] }),
  new Paragraph({
    spacing: { after: 60 },
    children: [new TextRun({ text: 'MEPIQ', bold: true, size: 84, color: BRAND })],
  }),
  new Paragraph({
    spacing: { after: 340 },
    children: [
      new TextRun({ text: 'Design Management for MEP Drawings with AI', size: 30, color: INK }),
    ],
  }),
  new Paragraph({
    spacing: { after: 100 },
    children: [
      new TextRun({ text: 'User Manual & Technical Guide', bold: true, size: 26, color: MUTED }),
    ],
  }),
  new Paragraph({
    spacing: { after: 900 },
    children: [
      new TextRun({
        text: 'Everything you need to demonstrate, explain and extend the system',
        italics: true, size: 21, color: MUTED,
      }),
    ],
  }),
  new Paragraph({
    spacing: { after: 50 },
    children: [new TextRun({ text: 'CTD 2026 AI Hackathon', bold: true, size: 22, color: INK })],
  }),
  new Paragraph({
    spacing: { after: 50 },
    children: [new TextRun({ text: 'Problem statement: Design Management for MEP with AI', size: 20, color: MUTED })],
  }),
  new Paragraph({
    children: [new TextRun({ text: 'Version 1.0.0', size: 20, color: MUTED })],
  }),
  pageBreak()
)

// ---- Contents ------------------------------------------------------------
children.push(
  h1('Contents'),
  p('Right-click the table below in Word and choose "Update Field" to populate page numbers.', { size: 19 }),
  new TableOfContents('Contents', { hyperlink: true, headingStyleRange: '1-3' }),
  pageBreak()
)

// =========================================================================
// PART 1 — WHAT IT IS AND WHY
// =========================================================================
children.push(h1('1. What MEPIQ is, and why it exists'))

children.push(h2('1.1 The problem you were asked to solve'))
children.push(
  p(
    'The hackathon brief asks for an AI system that understands Mechanical, Electrical and ' +
    'Plumbing (MEP) 2-D construction drawings — detecting and interpreting the objects on them ' +
    'so that downstream work like quantity takeoff, drawing review and change analysis becomes ' +
    'possible. It is graded across four levels.'
  )
)
children.push(
  table(
    ['Level', 'What is asked for', 'Weight'],
    [
      ['Level 1', 'Detect, classify and count quantifiable components; produce structured output', '35%'],
      ['Level 2', 'Detect linear objects and measure AC vent and pipe lengths using the drawing scale', '40%'],
      ['Level 3', 'An AI assistant that interacts with the engineering data', '15%'],
      ['Level 4', 'Innovation beyond the core problem', '+10%'],
    ],
    [1500, 7080, 1500],
    { boldCols: [0], rightCols: [2] }
  )
)
children.push(spacer(160))
children.push(
  p(
    'MEPIQ addresses all four, and is delivered as a deployed web application rather than a ' +
    'notebook, so a judge can upload a drawing and see the whole workflow end to end.'
  )
)

children.push(h2('1.2 The one insight that shaped everything'))
children.push(
  p([
    { t: 'A construction PDF is not a picture. ', b: true },
    {
      t: 'When an engineer publishes a sheet from Revit, AutoCAD or Navisworks, the result is a ' +
        'vector document. Every duct wall, every diffuser and every pipe is still inside the file ' +
        'as geometry — with its exact coordinates, its stroke colour and its pen weight intact.',
    },
  ])
)
children.push(
  p(
    'Almost every tool in this space throws that away. It converts the sheet to an image and asks ' +
    'a neural network to find a twenty-pixel symbol in it. That is throwing away exact information ' +
    'and replacing it with a guess.'
  )
)
children.push(
  p([
    { t: 'MEPIQ reads the geometry instead.', b: true },
    { t: ' Every consequence that makes this project distinctive follows from that single decision:' },
  ])
)
children.push(bullet([{ t: 'Measurements are exact', b: true }, { t: ' — a duct length is computed from the actual line coordinates, not estimated from pixels.' }]))
children.push(bullet([{ t: 'Detections explain themselves', b: true }, { t: ' — the app can say "18.0 × 18.0 pt square with two corner diagonals and a 3.1 pt central circle", not just "87% confident".' }]))
children.push(bullet([{ t: 'It is deterministic', b: true }, { t: ' — the same PDF always produces the same numbers. That matters when the output goes into a bid.' }]))
children.push(bullet([{ t: 'It is fast and cheap', b: true }, { t: ' — seconds per sheet on a laptop CPU. No GPU, no model download, no training run.' }]))

children.push(h3('The two discoveries that made it work'))
children.push(
  p(
    'Both were found by analysing the supplied dataset, and both are reproducible with the ' +
    'evaluation script included in the repository.'
  )
)
children.push(
  p([
    { t: 'Discovery 1 — publishers screen the background. ', b: true },
    {
      t: 'CAD software plots the architectural reference drawing (walls, grid, room outlines) in a ' +
        'light grey, and keeps the discipline\'s own systems at full black. So a simple brightness ' +
        'test separates "the work I am responsible for" from "context" — with no guessing about content.',
    },
  ])
)
children.push(
  p([
    { t: 'Discovery 2 — pen weight is a hidden layer table. ', b: true },
    {
      t: 'Within that foreground, duct and pipe run linework is drawn at one consistent, heavier ' +
        'pen weight than tags, leaders and hatching. Selecting that weight class recovers 99.5% of ' +
        'the ground-truth duct and pipe geometry in the dataset — 100% on 27 of 28 mechanical sheets.',
    },
  ])
)
children.push(
  callout(
    'This is the headline.',
    'PDFs of construction drawings still contain the original CAD geometry. We read it directly ' +
      'instead of guessing from pixels, which is why our measurements are exact and every number ' +
      'can be traced back to a specific line on the sheet.',
    'ok'
  )
)

children.push(h2('1.3 Objectives — what we set out to achieve'))
children.push(
  p(
    'Three layers of objective sit behind MEPIQ: the outcome we want for the user, the levels the ' +
    'hackathon grades, and the engineering principles we committed to. Being able to state all ' +
    'three is what turns a demo into a product pitch.'
  )
)

children.push(h3('Objective 1 — the user outcome'))
children.push(
  callout(
    'The primary objective:',
    'Take the counting and measuring work off an MEP estimator or plan reviewer entirely, and hand ' +
      'back a takeoff they can trust without re-doing it — so their time goes on judgement rather ' +
      'than on tallying.'
  )
)
children.push(
  p(
    'Today that work is manual. An estimator counts diffusers with a highlighter and measures ' +
    'ductwork with a digital wheel, sheet by sheet, for days per set. It is slow, it is tedious, ' +
    'and because it is tedious it is error-prone — and an error in a takeoff becomes a mispriced ' +
    'bid or a change order on site.'
  )
)
children.push(p('So the concrete objectives are:'))
children.push(bullet([{ t: 'Cut days of takeoff to minutes', b: true }, { t: ' — quantities, lengths and a priceable bill of quantities from an uploaded PDF.' }]))
children.push(bullet([{ t: 'Make the output checkable, not just fast', b: true }, { t: ' — every number traceable to the geometry it came from, in one click.' }]))
children.push(bullet([{ t: 'Catch coordination problems early', b: true }, { t: ' — while they are still a drawing revision rather than a change order.' }]))
children.push(bullet([{ t: 'Fit the way engineers already work', b: true }, { t: ' — their drawing conventions, their terminology, their file formats.' }]))

children.push(h3('Objective 2 — the four graded levels'))
children.push(
  p('Each level in the brief maps to a concrete objective we can point at in the running application.')
)
children.push(
  table(
    ['Level', 'Objective', 'Where you see it'],
    [
      ['1', 'Detect, identify and count quantifiable components, with bounding boxes, confidence scores and structured JSON/CSV output',
        'Drawings and Quantities screens; COCO and CSV exports'],
      ['2', 'Detect linear objects, trace them, and measure AC vent and pipe lengths using the drawing scale',
        'Runs overlay on Drawings; the Runs tab in Quantities'],
      ['3', 'An assistant that answers natural-language questions, explains detected issues and generates engineering summaries',
        'Copilot screen'],
      ['4', 'Innovation: corrective recommendations, risk identification, cross-discipline coordination, BIM integration, feedback learning',
        'Review, Coordination, Library and Exports screens'],
    ],
    [800, 5200, 4080],
    { boldCols: [0] }
  )
)
children.push(spacer(140))
children.push(
  p(
    'Note the weighting: Level 2 is worth 40% and Level 1 is worth 35%. Three quarters of the grade ' +
    'is detection and measurement accuracy, which is why the vector-geometry approach — the thing ' +
    'that makes measurement exact — was the right bet.'
  )
)

children.push(h3('Objective 3 — the engineering principles we committed to'))
children.push(
  p(
    'These were decided before any code was written, and every design choice in the system traces ' +
    'back to one of them. If a judge asks "why did you build it this way?", the answer is here.'
  )
)
children.push(
  table(
    ['Principle', 'Why', 'How it shows up'],
    [
      ['Exact over approximate',
        'A takeoff feeds a bid. An estimate of an estimate is worthless.',
        'Read vector geometry, not pixels. Duct walls collapse to one centreline so nothing is double-counted.'],
      ['Explainable over confident',
        'No engineer signs off on "87% confident". They need to see the reasoning.',
        'Every detection carries a sentence of geometric evidence. The scale shows its method and provenance.'],
      ['Deterministic',
        'The same drawing must produce the same numbers every time, or the output cannot go into a commercial document.',
        'No sampling, no model weights, no randomness anywhere in the engine.'],
      ['Correctable, and it should learn',
        'No system will be right on every drawing. What matters is how cheaply a human can fix it, and whether the fix sticks.',
        'One-click confirm/reject; name an unknown symbol once and it is recognised on every future drawing.'],
      ['Honest about limits',
        'A tool that hides its uncertainty will be abandoned the first time it is quietly wrong.',
        'Confidence and evidence on screen; a validation rule that fires when the scale is unconfirmed; 2-D clash results labelled as a screening pass.'],
      ['Deployable, not a notebook',
        'The brief asks for a working solution; a notebook is a demo, not a product.',
        'One Docker image, no GPU, no model download, CI that smoke-tests the running container.'],
    ],
    [2000, 3800, 4280]
  )
)
children.push(spacer(140))

children.push(h3('How we defined success'))
children.push(bullet([{ t: 'Accuracy: ', b: true }, { t: 'recover the ground-truth duct and pipe geometry near-perfectly, since Level 2 carries the most weight. ' }, { t: 'Achieved: 99.5%.', b: true, c: ACCENT }]))
children.push(bullet([{ t: 'Speed: ', b: true }, { t: 'a sheet analysed in seconds, not minutes, on ordinary hardware. ' }, { t: 'Achieved: 2–7 s per sheet, no GPU.', b: true, c: ACCENT }]))
children.push(bullet([{ t: 'Trust: ', b: true }, { t: 'every number on screen traceable to the drawing in one click. ' }, { t: 'Achieved throughout the reviewer.', b: true, c: ACCENT }]))
children.push(bullet([{ t: 'Generality: ', b: true }, { t: 'work on a drawing convention we have never seen. ' }, { t: 'Achieved via Find Similar and the learning library.', b: true, c: ACCENT }]))
children.push(bullet([{ t: 'Deployability: ', b: true }, { t: 'a judge can open it in a browser. ' }, { t: 'Achieved — Docker, LAN and cloud blueprints.', b: true, c: ACCENT }]))

children.push(h2('1.4 What the system does, in plain language'))
children.push(
  table(
    ['Level', 'Capability', 'How MEPIQ does it'],
    [
      ['1', 'Detect, classify and count components',
        'The dataset ships a symbol catalogue that defines each component geometrically. We draw those ideal symbols from their definitions and match candidates against them, then propagate confirmed matches across the sheet by exact geometry.'],
      ['2', 'Trace and measure duct and pipe runs',
        'Recover the system linework, pair the two walls of each duct into one centreline, chain segments into continuous runs, and convert to feet using a scale we detect five different ways.'],
      ['3', 'Answer questions in plain English',
        'A copilot with nine tools that read the analysis. It never invents a number, and it works with or without an OpenAI key.'],
      ['4', 'Validate the design and coordinate trades',
        'Twelve engineering rules, a cross-discipline clash screen, IFC and BCF export, and a symbol library that learns from the reviewer.'],
    ],
    [800, 2900, 6380],
    { boldCols: [0] }
  )
)

children.push(h2('1.5 Your 60-second opening for the judges'))
children.push(
  callout(
    'Read this almost word for word.',
    'Taking quantities off MEP drawings is done by hand today — an estimator counts diffusers with ' +
      'a highlighter and measures ductwork with a digital wheel. It takes days per set and it is ' +
      'error-prone. Every AI attempt we found rasterises the sheet and runs object detection on the ' +
      'image. We noticed something they all miss: a construction PDF is a vector file. The original ' +
      'CAD geometry is still in there. So MEPIQ reads the geometry directly. That means our duct ' +
      'lengths are exact rather than estimated, every detection can explain itself in engineering ' +
      'terms, and a full sheet analyses in seconds on a CPU with no model training at all. On the ' +
      'supplied dataset we recover 99.5% of the ground-truth duct and pipe geometry. Let me show you.'
  )
)

children.push(pageBreak())

// =========================================================================
// PART 2 — FEATURE GUIDE
// =========================================================================
children.push(h1('2. Feature guide — every screen, what it does and why'))
children.push(
  p(
    'The application has nine screens, listed down the left sidebar. This section walks through ' +
    'each one. For each screen you get what it is, why it exists, how to drive it, and a line you ' +
    'can say out loud to a judge.'
  )
)

children.push(
  ...feature({
    title: '2.1 Projects — upload and analyse',
    what:
      'The starting point. A project holds one building\'s drawing sets across all trades. You ' +
      'create a project, drop in one or more PDFs, and start the analysis.',
    why:
      'Real drawing sets arrive as large multi-page bid sets containing hundreds of pages, most of ' +
      'which are irrelevant — schedules, details, cover sheets. MEPIQ triages every page first and ' +
      'analyses only the MEP plans, so you are not waiting on pages nobody needs.',
    how: [
      'Type a project name and press Create.',
      'Drag a PDF onto the drop zone, or click to browse. A whole bid set is fine.',
      'Choose how many sheets to analyse. Start with 2–4 for a live demo; a full set takes minutes.',
      'Leave "Plans only" ticked so schedules and detail sheets are skipped.',
      'Press Analyse. A progress bar appears in the top bar showing the actual stage of work.',
    ],
    judge:
      'Notice the progress bar is not a spinner — it names the real work: "tracing ductwork on ' +
      'M-3.1". The analysis runs as a background job and streams its progress to the browser.',
  })
)

children.push(
  ...feature({
    title: '2.2 Dashboard — the project at a glance',
    what:
      'Four headline numbers (components detected, ductwork measured, piping measured, review ' +
      'findings), two charts, and a table of every analysed sheet.',
    why:
      'A project manager wants the totals, not the geometry. This is the page you would screenshot ' +
      'into a status report.',
    how: [
      'Read the four cards across the top.',
      'The left chart breaks components down by type; the right shows findings by severity.',
      'Click any row in the sheet table to jump straight into that sheet in the reviewer.',
    ],
    judge:
      'Every one of these numbers is traceable. Click through to any sheet and you can see the ' +
      'specific geometry each figure came from.',
  })
)

children.push(
  ...feature({
    title: '2.3 Drawings — the reviewer (the centrepiece)',
    what:
      'A drawing viewer with the sheet rendered underneath and everything the analysis found drawn ' +
      'on top as live vector overlays: component boxes, traced duct and pipe runs, finding markers ' +
      'and clash crosses.',
    why:
      'Numbers in a table are not trustworthy until you can see where they came from. This screen ' +
      'is the proof: every box on screen is the actual geometry the engine measured, not a picture of it.',
    how: [
      'Use the toolbar at the top-left of the canvas: hand (pan), box (find similar), ruler (calibrate scale), minus and plus (zoom), and Fit.',
      'Hold the Space bar, or drag with the middle mouse button, to pan from any tool.',
      'Scroll the mouse wheel to zoom towards the cursor.',
      'Click a component box or a traced run to open the Inspector on the right.',
      'Toggle the Layers chips on the left to show or hide each overlay.',
      'Use the Component filter chips to isolate one component type, and the confidence slider to hide low-confidence detections.',
    ],
    judge:
      'The overlays are SVG drawn in the drawing\'s own coordinate space, so they stay razor sharp ' +
      'at any zoom. That is only possible because we work in real geometry rather than pixels.',
  })
)

children.push(h3('2.3.1 The Inspector — why a detection is a detection'))
children.push(
  p(
    'Click any component box. The right panel shows a zoomed crop of that exact spot on the ' +
    'drawing, the component name, its confidence, and — most importantly — a plain-English ' +
    'explanation of the evidence, for example:'
  )
)
children.push(code('18.0 x 18.0 pt square with an internal \'X\'; heavy 1.32 pt side indicates the rated barrier'))
children.push(
  p(
    'Two buttons let you Confirm or Reject the detection. A rejection removes it from every count ' +
    'and every export immediately.'
  )
)
children.push(
  callout(
    'This is a strong demo moment.',
    'Most AI tools give you a bounding box and a confidence score you have to take on faith. Ask a ' +
      'judge: "would you sign a bid off on 87% confident?" Then show them that our detection ' +
      'explains itself in the language a mechanical engineer already uses.'
  )
)

children.push(h3('2.3.2 Drawing scale — with provenance, and one-click override'))
children.push(
  p(
    'Every measured length depends on the sheet scale, so getting it wrong makes everything wrong. ' +
    'The panel shows the scale, a confidence percentage, and the evidence — for example ' +
    '"26/78 dimension annotations agree" or "Scale text found on sheet".'
  )
)
children.push(
  p(
    'If the scale is wrong or uncertain, press "Calibrate from the drawing", click two points a ' +
    'known distance apart, type the real distance, and every length on the sheet is rescaled ' +
    'instantly.'
  )
)
children.push(
  callout(
    'Say this:',
    'We do not just guess the scale — we tell you how we worked it out and how confident we are, ' +
      'and we let you override it in two clicks. A takeoff tool that hides its assumptions is not ' +
      'one an engineer will trust.'
  )
)

children.push(h3('2.3.3 Find similar symbols — the feature to demo last'))
children.push(
  p(
    'Select the box tool, drag a rectangle around a single symbol, and MEPIQ finds every identical ' +
    'stamp on the sheet and reports the count. On a dense mechanical sheet this returns 116 matches ' +
    'in 0.07 seconds.'
  )
)
children.push(
  p(
    'This is exact, not approximate. CAD symbols are stamped from blocks, so every instance is the ' +
    'same geometry under a rigid transform. The match is a geometric one — it either is the symbol ' +
    'or it is not.'
  )
)
children.push(
  p(
    'After the search you can type a name and press Save. That teaches the component library, and ' +
    'from then on the symbol is recognised automatically on this sheet, the rest of the set, and ' +
    'every drawing analysed afterwards.'
  )
)
children.push(
  callout(
    'Important for the demo:',
    'You must zoom in before selecting. At a fit-to-page view of a 1/32" sheet, a 24-inch diffuser ' +
      'is about one screen pixel wide — no mouse drag can isolate it. The app detects this and ' +
      'disables the tool with a "Zoom in for me" button. Zoom to roughly 90% first.',
    'warn'
  )
)

children.push(
  ...feature({
    title: '2.4 Quantities — the takeoff',
    what:
      'Three tabs: component counts per sheet, every measured duct and pipe run, and a rolled-up ' +
      'bill of quantities. Each is filterable and exports to CSV.',
    why:
      'This is the deliverable an estimator actually wants. The bill of quantities is priceable ' +
      'line items: components by type in each, ductwork and piping by size in linear feet.',
    how: [
      'Switch tabs with the buttons at the top.',
      'Filter by sheet with the dropdown, or type in the filter box.',
      'On the Runs tab, click View on any row to fly to that run on the drawing.',
      'Press the CSV button to download the current tab.',
    ],
    judge:
      'The runs table is the Level 2 answer. Every row is one traced object with its measured ' +
      'length, its size, its service — supply air, sanitary sewer — and whether it is new or existing.',
  })
)

children.push(
  ...feature({
    title: '2.5 Review — design validation',
    what:
      'The findings list from a twelve-rule engineering checker, sorted by severity, each with an ' +
      'explanation, a recommendation and a jump-to-location button. Also the "teach the library" queue.',
    why:
      'Counting things is table stakes. What actually saves an engineer time is being told which of ' +
      'the 400 objects on a sheet deserves a second look.',
    how: [
      'Filter by severity or by rule.',
      'Press "Show on drawing" to fly to the exact location of a finding.',
      'Press Dismiss on a finding you disagree with — it is removed from the counts but kept on record.',
      'In the right-hand card, name any unidentified repeated symbol to teach the library.',
    ],
    judge:
      'These are not generic warnings. MEP-006 flags a duct crossing a fire-rated barrier without a ' +
      'damper — that is a life-safety and code compliance failure, and it is exactly what a plan ' +
      'reviewer is paid to catch.',
  })
)

children.push(h3('2.5.1 The twelve rules'))
children.push(
  table(
    ['Rule', 'What it checks', 'Severity'],
    [
      ['MEP-001', 'A duct or pipe run that connects to nothing', 'High'],
      ['MEP-002', 'An air terminal with no ductwork reaching it', 'High'],
      ['MEP-003', 'Runs with no size or service tag — cannot be priced', 'Medium'],
      ['MEP-004', 'Duct size reduces then increases along a run', 'Medium'],
      ['MEP-005', 'A fire damper not sitting on any traced duct', 'Medium'],
      ['MEP-006', 'A duct penetrating a rated wall with no damper', 'Critical'],
      ['MEP-007', 'An unusually long run with no branch — a possible mis-trace', 'Low'],
      ['MEP-008', 'The drawing scale could not be confirmed', 'High'],
      ['MEP-009', 'A repeated symbol that is not in the component library', 'Low'],
      ['MEP-010', 'Existing services shown as modified', 'Info'],
      ['MEP-011', 'Air terminal spacing outside the usual 8–20 ft', 'Low'],
      ['MEP-012', 'A branch too small for the terminal it feeds', 'Medium'],
    ],
    [1300, 7280, 1500],
    { monoCols: [0], boldCols: [0] }
  )
)

children.push(spacer(140))
children.push(
  ...feature({
    title: '2.6 Coordination — cross-discipline clash screening',
    what:
      'Overlays same-level sheets from different trades on their shared drawing frame and reports ' +
      'where their systems occupy the same plan space.',
    why:
      'Clash detection normally needs a federated 3-D model — which does not exist at the stage ' +
      'these drawings are produced. But most coordination failures are visible in 2-D long before ' +
      'anyone builds a model.',
    how: [
      'Upload at least two sheets from different trades at the same building level and scale.',
      'Filter by severity.',
      'Press View to fly to the conflict on the drawing.',
    ],
    judge:
      'Be honest that this is a screening pass, not a 3-D clash. Plan geometry cannot know ' +
      'elevations — and the app says so on the screen rather than implying certainty. Judges ' +
      'respect a system that knows its own limits.',
  })
)

children.push(
  ...feature({
    title: '2.7 Copilot — ask the drawings anything',
    what:
      'A chat panel that answers questions about the analysed set: quantities, findings, ' +
      'comparisons, explanations.',
    why:
      'This is the Level 3 requirement. But the design decision worth defending is that it never ' +
      'invents a number. Every quantity comes from a tool call against the analysis, and the answer ' +
      'shows you which lookups it made.',
    how: [
      'Click a suggested question, or type your own.',
      'Expand the "data lookups" line under any answer to see exactly which tools were called.',
      'Untick the LLM checkbox to see the deterministic engine answer the same question.',
    ],
    judge:
      'Ask it something, then expand the tool trace. That transparency is the point: the language ' +
      'model chooses tools and explains results, it does not recall figures. And it works with no ' +
      'API key at all — which means it cannot fail during a demo.',
  })
)

children.push(h3('2.7.1 Good questions to ask on stage'))
children.push(bullet('"Give me a summary of this drawing set"'))
children.push(bullet('"How much supply air ductwork is there, by size?"'))
children.push(bullet('"What are the highest-severity issues I should look at first?"'))
children.push(bullet('"Which runs are not connected to anything?"'))
children.push(bullet('"Show me the bill of quantities"'))
children.push(bullet('"How was the drawing scale determined?"'))

children.push(spacer(140))
children.push(
  ...feature({
    title: '2.8 Library — the system that learns',
    what:
      'Two panels: the built-in component catalogue with each symbol\'s geometric definition, and ' +
      'the symbols a reviewer has taught the system.',
    why:
      'No fixed catalogue covers every firm\'s drawing conventions. Because our matching is on exact ' +
      'geometry, naming a symbol once makes every occurrence countable — on that sheet, the rest of ' +
      'the set, and every future drawing from the same office.',
    how: [
      'Read the catalogue to see how each component is defined geometrically.',
      'Learned symbols appear in the right panel with a confirmation count.',
      'Press Forget to remove one.',
    ],
    judge:
      'This is the human-in-the-loop feedback loop. The product gets better with use, and it adapts ' +
      'to the customer instead of forcing the customer to adapt to it.',
  })
)

children.push(
  ...feature({
    title: '2.9 Exports — structured output',
    what:
      'Ten downloadable artefacts: COCO JSON, four CSVs, a bill of quantities, a BCF-shaped issue ' +
      'list, an IFC4 model, and the full analysis JSON.',
    why:
      'A takeoff is only useful if it flows into the next tool. Each format is written to be opened ' +
      'directly by the thing that needs it — no reformatting step.',
    how: ['Press Download on any card.'],
    judge:
      'The COCO export uses the dataset\'s own 150-DPI pixel coordinates, so our results drop ' +
      'straight into your existing evaluation harness. And the IFC file opens in Revit or ' +
      'Navisworks as a coordination underlay with real quantities attached.',
  })
)

children.push(pageBreak())

// =========================================================================
// PART 3 — HOW THE ENGINE WORKS
// =========================================================================
children.push(h1('3. How it works — the engine'))
children.push(
  p(
    'This section explains the analysis itself. If a judge asks a technical question, the answer is ' +
    'almost certainly here.'
  )
)

children.push(h2('3.1 The pipeline, end to end'))
children.push(
  code([
    'PDF',
    ' |',
    ' +-> extract vector primitives      (pdfdoc.py)',
    ' +-> split foreground / screened    (brightness test)',
    ' +-> triage every page              (discipline.py)',
    ' |',
    ' +-> for each MEP plan sheet:',
    '      +-> detect components          (shapes.py + matching.py + symbols.py)   Level 1',
    '      +-> establish drawing scale    (scale.py, five estimators)',
    '      +-> trace and measure runs     (linear.py)                              Level 2',
    '      +-> run validation rules       (validate.py)                            Level 4',
    ' |',
    ' +-> cross-discipline clash screen   (clash.py)                               Level 4',
    ' +-> results -> API -> UI -> copilot (copilot.py)                             Level 3',
    '             -> COCO / CSV / BOQ / IFC / BCF (exporters.py)',
  ])
)

children.push(h2('3.2 Reading the PDF'))
children.push(
  p(
    'PyMuPDF gives us one record per drawn path. Each is flattened into straight segments carrying ' +
    'colour, pen width, dash state and fill. Curves become their control chords — enough for length ' +
    'and topology, and far cheaper than full tessellation on a sheet with 100,000 primitives.'
  )
)
children.push(p([{ t: 'The single most important line of code in the project:', b: true }]))
children.push(code('is_foreground = luminance <= 0.35 or saturation >= 0.12'))
children.push(
  p(
    'That separates the discipline\'s own linework from the screened architectural underlay. It held ' +
    'on every publisher in the supplied dataset.'
  )
)
children.push(
  callout(
    'Performance note worth mentioning:',
    'A submitted bid set can be several hundred pages, and fully parsing one sheet costs about a ' +
      'second. So triage uses a text-only view with drawing density estimated from the content-stream ' +
      'size. Triaging a 25-page set takes 1.5 seconds instead of 30.'
  )
)

children.push(h2('3.3 Drawing scale — five independent estimators'))
children.push(
  p(
    'Get the scale wrong and every length is wrong, so we do not rely on one trick. Five estimators ' +
    'run, each returning a candidate with its own confidence and a human-readable justification.'
  )
)
children.push(
  table(
    ['Estimator', 'What it uses', 'Confidence'],
    [
      ['title_block', 'The scale printed on the sheet, e.g. 1/8" = 1\'-0"', '0.86 – 0.98'],
      ['dimension_string', 'A dimension annotation sitting on a line of known drawn length', '0.55 – 0.92'],
      ['duct_tag', 'A duct tagged 42/20 must be 42 inches across, so its drawn gap fixes the scale', '0.45 – 0.90'],
      ['known_component', 'Square ceiling diffusers sit in a 24-inch ceiling module', '0.35 – 0.80'],
      ['sheet_size', 'Last-resort prior from the paper size', '0.20'],
    ],
    [2200, 6280, 1600],
    { monoCols: [0] }
  )
)
children.push(spacer(140))
children.push(
  p(
    'When two independent estimators agree, confidence rises by 0.10 — a genuinely stronger signal ' +
    'than either alone. Losing candidates are kept and shown in the UI, so a reviewer sees the ' +
    'alternatives rather than a single opaque answer.'
  )
)
children.push(
  p([
    { t: 'A subtle trap we handle: ', b: true },
    {
      t: 'metric ratios sit numerically between the imperial ones, so a slightly noisy imperial ' +
        'estimate will happily land on "1:75" and silently rescale the entire takeoff. Metric is ' +
        'therefore only considered when the sheet actually reads metric.',
    },
  ])
)

children.push(h2('3.4 Level 1 — detecting and counting components'))
children.push(
  p('Three mechanisms work together. Understanding the first one is enough for most questions.')
)

children.push(h3('Mechanism 1 — legend-driven shape classification'))
children.push(
  p(
    'The dataset ships a symbol catalogue that defines each component in words: "a square with an ' +
    'X and a central circle", "a square with a single diagonal", "concentric circles". So rather ' +
    'than learn what those look like from pixels, we draw them from the definition and compare.'
  )
)
const mech1 = newList()
children.push(step('Cluster short foreground segments that touch into blobs. Only short segments take part — run linework is long, symbol strokes are not — which stops symbols fusing into the duct network they sit on.', 0, mech1))
children.push(step('Merge blobs whose bounding boxes overlap. A fire damper is a square, two diagonals and a heavy barrier line, which can land in separate blobs depending on how the exporter ordered the file.', 0, mech1))
children.push(step('Absorb any geometry wholly inside the candidate. An 18 pt square\'s own diagonal is 25 pt, so the short-segment cut-off would otherwise discard the very "X" that distinguishes a fire damper from a plain register.', 0, mech1))
children.push(step('Normalise to a 40 × 40 binary raster and score against the ideal symbols over four rotations and their mirrors.', 0, mech1))
children.push(
  p([
    { t: 'The score is the harmonic mean of two quantities that both matter: ', },
    { t: 'coverage', b: true },
    { t: ' (how much of the symbol is present) and ' },
    { t: 'cleanliness', b: true },
    { t: ' (how much of the candidate the symbol explains). Coverage alone misses a symbol with a stroke absent; cleanliness alone accepts a blob containing the symbol plus a lot else.' },
  ])
)

children.push(h3('Mechanism 2 — exact template propagation'))
children.push(
  p(
    'Classification only sees a symbol when clustering managed to isolate it. Wherever a diffuser is ' +
    'fused to the flexible duct feeding it, the blob is too big to recognise — and on a busy sheet ' +
    'those are the majority.'
  )
)
children.push(
  p(
    'So each confidently classified instance is lifted as a template, and the whole sheet is searched ' +
    'for rigid copies of it. Because CAD symbols are stamped from blocks, every instance is the same ' +
    'geometry under a rigid transform, and the search is an exact match rather than a similarity score.'
  )
)

children.push(h3('Mechanism 3 — glyph mining and the learning library'))
children.push(
  p(
    'Separately, MEPIQ mines geometry that repeats verbatim across the sheet. That finds every ' +
    'repeated component — including ones nobody has ever labelled — with exact counts. Unnamed ' +
    'repeated glyphs surface in the Review queue, and naming one writes it to the library.'
  )
)
children.push(
  callout(
    'Why this matters commercially:',
    'A fixed catalogue can never cover every firm\'s drawing conventions. This turns that from a ' +
      'blocker into a one-click setup step, and the system improves with every project.',
    'ok'
  )
)

children.push(h2('3.5 Level 2 — tracing and measuring runs'))

children.push(h3('Step 1 — recover the system linework'))
children.push(p('Stroke classes are ranked by a score that balances three signals:'))
children.push(code('score = inked_length x sqrt(weight / max_weight) x (1 + 2.5 x tag_affinity)'))
children.push(
  p([
    { t: 'The first two terms balance "MEP systems are plotted heavier" against "a class only matters if there is a lot of it". ' },
    { t: 'Tag affinity', b: true },
    {
      t: ' is the drawing telling us the answer directly: engineers tag runs by writing the size ' +
        'beside the line, so whichever stroke class those tags sit on is the one carrying the ' +
        'system. That settles cases line weight alone cannot — on many plumbing sheets the pipes ' +
        'are dashed, so the system class has more, shorter strokes than the architectural linework.',
    },
  ])
)

children.push(h3('Step 2 — collapse duct walls into centrelines'))
children.push(
  p(
    'Rectangular duct is drawn as two parallel lines. Pairing them and walking the centreline turns ' +
    '2 × L of linework into 1 × L of duct with a known width — which is both the correct quantity ' +
    'and a free size takeoff.'
  )
)
children.push(
  callout(
    'This is a great judge answer.',
    'Measuring the linework instead would double-count every rectangular duct. That is the classic ' +
      'error when taking ductwork off a PDF by hand or by pixel. We have a test that asserts two ' +
      'walls 12 pt apart over 100 pt measure 100 pt of duct, not 200 pt of lines.'
  )
)

children.push(h3('Step 3 — chain into runs and attribute them'))
children.push(
  p(
    'Centrelines and single-line branches are snapped into an endpoint graph and walked outward ' +
    'while the path is unambiguous, so an elbow becomes one run rather than two. Size and service ' +
    'come from the annotations printed beside the run — 42/20 SA, (N)2"LW — parsed into structured ' +
    'dimensions, service names and new/existing status.'
  )
)
children.push(
  table(
    ['Tag on the drawing', 'What MEPIQ reads from it'],
    [
      ['42/20 SA', 'Rectangular duct, 42 × 20 inches, Supply Air'],
      ['12ø EA', 'Round duct, 12 inch diameter, Exhaust Air'],
      ['(N)2"LW', 'New 2-inch pipe, Laboratory Waste'],
      ['(E)4"SS', 'Existing 4-inch pipe, Sanitary Sewer'],
    ],
    [3400, 6680],
    { monoCols: [0] }
  )
)

children.push(pageBreak())

// =========================================================================
// PART 4 — BACKEND
// =========================================================================
children.push(h1('4. How it works — the backend'))
children.push(
  p([
    { t: 'Stack: ', b: true },
    { t: 'Python 3.12, FastAPI, PyMuPDF for PDF geometry, NumPy for the raster scoring, SQLite for metadata, JSON files on disk for analysis payloads. No ORM, no message broker, no GPU.' },
  ])
)

children.push(h2('4.1 Layout'))
children.push(
  table(
    ['Module', 'Responsibility'],
    [
      ['mepiq_core/pdfdoc.py', 'Vector primitive extraction; the foreground / screened split'],
      ['mepiq_core/geometry.py', 'Polygons, circles, hatch runs, parallel pairs, spatial indexes'],
      ['mepiq_core/shapes.py', 'Legend-driven shape classification (Level 1)'],
      ['mepiq_core/matching.py', 'Exact rigid-transform geometric hashing'],
      ['mepiq_core/symbols.py', 'Component catalogue, detection pipeline, glyph mining, library'],
      ['mepiq_core/linear.py', 'Layer recovery, duct centrelines, run chaining, measurement (Level 2)'],
      ['mepiq_core/scale.py', 'Five scale estimators with provenance and confidence'],
      ['mepiq_core/discipline.py', 'Sheet triage — which trade, and is it a plan?'],
      ['mepiq_core/validate.py', 'The twelve design-validation rules (Level 4)'],
      ['mepiq_core/clash.py', 'Cross-discipline 2-D coordination screen (Level 4)'],
      ['mepiq_core/exporters.py', 'COCO, CSV, BOQ, IFC4, BCF'],
      ['mepiq_core/pipeline.py', 'End-to-end orchestration with progress reporting'],
      ['app/main.py', 'The FastAPI application and all HTTP endpoints'],
      ['app/store.py', 'SQLite schema and file storage'],
      ['app/copilot.py', 'The nine copilot tools, the LLM loop and the deterministic router'],
    ],
    [3300, 6780],
    { monoCols: [0] }
  )
)
children.push(spacer(140))
children.push(
  callout(
    'A deliberate design choice:',
    'mepiq_core has no web framework and no I/O assumptions. It is a library that could be used from ' +
      'a notebook, a CLI or a different web stack. Only app/ knows about HTTP. That separation is why ' +
      'the evaluation script can reuse the exact code path the API uses.'
  )
)

children.push(h2('4.2 The API surface'))
children.push(
  table(
    ['Endpoint', 'Purpose'],
    [
      ['GET  /api/health', 'Version, and whether the LLM copilot is enabled'],
      ['GET  /api/catalogue', 'Symbol catalogue, validation rules, standard scales'],
      ['POST /api/projects', 'Create a project'],
      ['POST /api/projects/{id}/documents', 'Upload PDFs'],
      ['POST /api/projects/{id}/analyse', 'Start a background analysis job'],
      ['GET  /api/jobs/{id}/stream', 'Server-sent progress events'],
      ['GET  /api/documents/{id}/result', 'Analysis summary (light)'],
      ['GET  /api/documents/{id}/result/full', 'Everything, including geometry'],
      ['GET  /api/documents/{id}/page/{n}/image', 'Rendered sheet, cached on disk'],
      ['POST /api/visual-search', 'Find every instance of a selected symbol'],
      ['POST /api/projects/{id}/calibrate', 'Set the scale from two clicked points'],
      ['POST /api/projects/{id}/review', 'Confirm, reject or dismiss'],
      ['POST /api/library', 'Teach the library a symbol'],
      ['POST /api/projects/{id}/chat', 'Ask the copilot'],
      ['GET  /api/documents/{id}/export/{kind}', 'Any of the ten export formats'],
    ],
    [4200, 5880],
    { monoCols: [0] }
  )
)
children.push(spacer(140))
children.push(p('Interactive documentation is generated automatically at /docs — a good thing to open for judges.'))

children.push(h2('4.3 Three backend decisions worth explaining'))

children.push(h3('Background jobs with streamed progress'))
children.push(
  p(
    'Analysis runs in a thread pool. Progress is reported as stage, percentage and message, and ' +
    'streamed to the browser over server-sent events. That is why the UI can say "tracing ductwork ' +
    'on M-3.1" rather than showing an indeterminate spinner on a job that takes a minute.'
  )
)

children.push(h3('Reviewer decisions are an overlay, never a mutation'))
children.push(
  p(
    'Confirmations, rejections and dismissals are stored in an append-only reviews table and applied ' +
    'when a result is read. The analysis file itself is never modified. Two consequences: re-running ' +
    'the analysis does not lose corrections, and every decision remains auditable — which matters ' +
    'when the output feeds a commercial bid.'
  )
)

children.push(h3('Rendered sheets are cached on disk'))
children.push(
  p(
    'A large sheet renders to a multi-megabyte image and takes a second or two, and while an ' +
    'analysis is running it competes for CPU. Sheets never change once uploaded, so the render is ' +
    'cached and never needs invalidating. Measured: 0.39 s on the first request, 0.01 s thereafter.'
  )
)

children.push(pageBreak())

// =========================================================================
// PART 5 — FRONTEND
// =========================================================================
children.push(h1('5. How it works — the frontend'))
children.push(
  p([
    { t: 'Stack: ', b: true },
    { t: 'React 18, Vite, Redux Toolkit with RTK Query, React Router. Hand-written CSS with design tokens — no UI framework, so the bundle is 314 kB (100 kB gzipped) and there is nothing to fight when styling.' },
  ])
)

children.push(h2('5.1 State — three stores, each with one job'))
children.push(
  table(
    ['Store', 'Holds', 'Examples'],
    [
      ['RTK Query cache', 'Everything the server owns', 'projects, analysis results, chat history, library'],
      ['uiSlice', 'Which project, document and page you are looking at', 'projectId, documentId, page, theme, job progress'],
      ['viewerSlice', 'Everything about the drawing canvas', 'zoom and pan, active tool, layer toggles, selection, filters'],
    ],
    [2400, 3200, 4480],
    { monoCols: [0] }
  )
)
children.push(spacer(140))
children.push(
  p(
    'RTK Query handles caching, request de-duplication and invalidation. When a reviewer rejects a ' +
    'detection, the mutation invalidates the Result tag and every screen showing that number ' +
    'refreshes itself — the dashboard, the quantities table and the exports all stay consistent ' +
    'with no manual wiring.'
  )
)

children.push(h2('5.2 The viewer, and its coordinate system'))
children.push(
  p(
    'This is the part worth understanding, because it is the heart of the demo. Three coordinate ' +
    'spaces are in play at once:'
  )
)
children.push(
  table(
    ['Space', 'Unit', 'Used for'],
    [
      ['PDF points', '1/72 inch', 'Everything the engine computes and stores'],
      ['Render pixels', '130 DPI', 'The rendered sheet image'],
      ['Screen pixels', 'CSS px', 'What the user sees, after pan and zoom'],
    ],
    [2600, 2400, 5080]
  )
)
children.push(spacer(140))
children.push(
  p(
    'The sheet is an <img>, and every overlay is SVG drawn in the same space, both inside one ' +
    'container that carries a single CSS transform for pan and zoom. Because the browser applies ' +
    'that transform, panning and zooming stay smooth even with hundreds of runs on screen, and the ' +
    'overlays remain vector-sharp at any magnification.'
  )
)
children.push(
  callout(
    'If a judge asks why the overlays are so crisp:',
    'They are not drawn onto the image. They are live SVG in the drawing\'s own coordinate space, ' +
      'rendered from the exact geometry the engine measured. Zoom in as far as you like — a ' +
      'detection box lands on the actual strokes every time.'
  )
)

children.push(h2('5.3 Interaction model'))
children.push(
  table(
    ['Action', 'Result'],
    [
      ['Drag with the hand tool', 'Pan'],
      ['Hold Space and drag', 'Pan from any tool'],
      ['Middle-mouse drag', 'Pan from any tool'],
      ['Mouse wheel', 'Zoom towards the cursor'],
      ['Click a box or run', 'Open it in the Inspector'],
      ['Box tool, then drag', 'Find every identical symbol'],
      ['Ruler tool, then two clicks', 'Set the scale from a known distance'],
    ],
    [3600, 6480]
  )
)

children.push(pageBreak())

// =========================================================================
// PART 6 — RESULTS
// =========================================================================
children.push(h1('6. Results, and the limits we are honest about'))
children.push(
  p(
    'All figures below are reproducible with backend/evaluate_dataset.py against the supplied ' +
    'annotations. Judges respect measured numbers with stated caveats far more than round claims.'
  )
)

children.push(h2('6.1 Level 2 — linear measurement (worth 40%)'))
children.push(
  p(
    'This is the level with unambiguous ground truth: the supplied annotated PDFs contain the exact ' +
    'vector geometry marked as duct or pipe, so we compare segment for segment.'
  )
)
children.push(
  table(
    ['Metric', 'Result'],
    [
      ['Ground-truth geometry recovered', '99.5%'],
      ['Mechanical sheets at 100% recall', '27 of 28'],
      ['Plumbing and fire protection', '94.4%'],
      ['Selection precision', '86.5%'],
      ['Sheets at 100% recall overall', '40 of 44'],
      ['Time per sheet', '0.3 – 3 seconds'],
    ],
    [6480, 3600],
    { rightCols: [1], boldCols: [1] }
  )
)
children.push(spacer(140))
children.push(
  callout(
    'Lead with this number.',
    'Level 2 carries the most weight in the grading, and it is where we are strongest: 99.5% of the ' +
      'ground-truth duct and pipe geometry recovered, and exactly 100% on 27 of the 28 mechanical ' +
      'sheets.',
    'ok'
  )
)

children.push(h2('6.2 Level 1 — detection and counting (worth 35%)'))
children.push(
  table(
    ['Metric', 'All 29 sheets', 'Catalogue-dense sheets'],
    [
      ['Precision at IoU 0.3', '0.45', '0.58 – 0.82'],
      ['Recall at IoU 0.3', '0.47', '0.67 – 0.83'],
      ['F1', '0.46', '0.68 – 0.77'],
      ['Count accuracy', '0.40', '0.62 – 0.73'],
      ['Time per sheet', '2 – 7 s', ''],
    ],
    [4080, 3000, 3000],
    { rightCols: [1, 2] }
  )
)
children.push(spacer(140))
children.push(h3('The caveat to state before a judge finds it'))
children.push(
  p(
    'The Level 1 annotations are not hand-drawn ground truth. Every record carries a "score" field ' +
    '(values as low as 0.61) and an "orig_detection_id" — they are another detector\'s output. ' +
    'Concretely, within a single sheet:'
  )
)
children.push(bullet('Boxes for one component type vary from 26.5 × 18.8 px to 53.0 × 37.5 px — a 2× spread.'))
children.push(bullet('Several sheets label only one class while the drawing plainly contains several others.'))
children.push(bullet('One ductwork construction plan carries 3 annotations for a sheet with hundreds of components.'))
children.push(
  p(
    'Errors run in both directions: precision is penalised for finding real components that were ' +
    'never labelled, and recall is penalised for instances whose reference boxes disagree with the ' +
    'drawn extents. On the densest sheet we find 144 of 168 fire dampers — 86% of the count — at ' +
    '0.86 class-agnostic localisation recall.'
  )
)
children.push(
  callout(
    'How to handle this honestly:',
    '"Count accuracy on catalogue-dense sheets — 62 to 73% — is the number we would stand behind. ' +
      'And our answer to the remaining gap is not a better threshold, it is the review loop: ' +
      'confirm, reject or name in one click, and the library carries that correction forward to ' +
      'every future drawing."',
    'warn'
  )
)

children.push(h2('6.3 Speed'))
children.push(
  table(
    ['Operation', 'Time'],
    [
      ['Parse a 100,000-primitive sheet', '1.3 s'],
      ['Detect components on a dense mechanical sheet', '2 – 5 s'],
      ['Trace and measure ductwork', '0.3 – 3 s'],
      ['Find-similar visual search (116 matches)', '0.07 s'],
      ['Triage a 25-page bid set', '1.5 s'],
      ['Full analysis, 4 sheets', '20 – 45 s'],
    ],
    [7080, 3000],
    { rightCols: [1], boldCols: [1] }
  )
)
children.push(spacer(140))
children.push(p('No GPU, no model download, no training step.'))

children.push(h2('6.4 Testing'))
children.push(bullet([{ t: '39 backend tests', b: true }, { t: ' — synthetic drawings generated with PyMuPDF, so no dataset is required and CI is fast.' }]))
children.push(bullet([{ t: '7 layout invariants', b: true }, { t: ' — static checks on the CSS and viewer that catch a class of bug jsdom provably cannot see.' }]))
children.push(bullet([{ t: 'Page smoke tests', b: true }, { t: ' — every screen rendered against a live API in two states, asserting real data appears.' }]))
children.push(bullet([{ t: 'CI', b: true }, { t: ' — GitHub Actions runs all of the above, builds the Docker image and smoke-tests the running container.' }]))

children.push(h2('6.5 Limits we state openly'))
children.push(bullet([{ t: '2-D is 2-D. ', b: true }, { t: 'Clash screening overlays plan geometry; it cannot know elevations. Findings are candidates for a human to check, and the app says so.' }]))
children.push(bullet([{ t: 'Scanned drawings are out of scope. ', b: true }, { t: 'MEPIQ needs a vector PDF. A raster scan produces no geometry, and the app reports that rather than guessing.' }]))
children.push(bullet([{ t: 'Not a certified takeoff. ', b: true }, { t: 'It is a review aid that shows its working, so an engineer can check any number in one click.' }]))
children.push(bullet([{ t: 'Flexible duct detection is tuned for precision. ', b: true }, { t: '0.84 precision at 0.26 recall — curved flexible duct changes its hash-mark length as it bends, which breaks run chaining. This is the biggest single improvement still available.' }]))
children.push(bullet([{ t: 'No authentication. ', b: true }, { t: 'Fine on a trusted network for a demo; it would need auth before any real deployment.' }]))

children.push(pageBreak())

// =========================================================================
// PART 7 — RUNNING IT
// =========================================================================
children.push(h1('7. Running and deploying'))

children.push(h2('7.1 The three ways to run it'))
children.push(h3('Docker Compose — the whole stack'))
children.push(code(['copy .env.example .env', 'docker compose up --build']))
children.push(p('App on http://localhost:8080, API docs on http://localhost:8000/docs.'))

children.push(h3('Single container — one image, one port'))
children.push(code(['docker build -t mepiq .', 'docker run -p 8000:8000 -v mepiq-data:/data mepiq']))
children.push(p('Serves both the API and the UI from http://localhost:8000. This is what the cloud deploy configs use.'))

children.push(h3('On your network, so judges can open it on their own laptops'))
children.push(code(['.\\run-lan.ps1', '.\\run-lan.ps1 -OpenFirewall -NoBuild    # once, from an admin prompt']))
children.push(
  p(
    'The script finds your LAN address, waits for the API to report healthy, and prints the URL to ' +
    'share. No rebuild is needed for a different address: the frontend calls the API on whatever ' +
    'host the browser used.'
  )
)
children.push(
  callout(
    'If someone cannot connect:',
    'It is almost always Windows Firewall, or the network profile being set to Public rather than ' +
      'Private. Guest and corporate Wi-Fi often block device-to-device traffic entirely — use a ' +
      'phone hotspot as a fallback.',
    'warn'
  )
)

children.push(h2('7.2 Configuration'))
children.push(
  table(
    ['Setting', 'Default', 'Notes'],
    [
      ['MEPIQ_DATA_DIR', './data', 'Uploads, results, SQLite, library. The only state — back this up.'],
      ['MEPIQ_WORKERS', '2', 'Concurrent analyses. Bounded by RAM, not CPU.'],
      ['MEPIQ_MAX_SHEETS', '40', 'Ceiling on sheets analysed per run.'],
      ['MEPIQ_MAX_UPLOAD_MB', '200', 'Per-file upload cap.'],
      ['MEPIQ_BIND', '0.0.0.0', 'Set to 127.0.0.1 to keep it to one machine.'],
      ['OPENAI_API_KEY', 'unset', 'Optional. Without it the copilot uses its deterministic engine.'],
    ],
    [2900, 1600, 5580],
    { monoCols: [0, 1] }
  )
)
children.push(spacer(140))

children.push(h2('7.3 Sizing a cloud instance'))
children.push(
  p(
    'The engine is CPU-bound on geometry and holds one sheet at a time in memory. A t3.micro ' +
    '(1 GB) is too small — the Docker build alone will likely run out of memory. Use t3.small ' +
    '(2 GB) as a minimum, t3.medium (4 GB) to be comfortable. Around 20 GB of disk is plenty.'
  )
)

children.push(pageBreak())

// =========================================================================
// PART 8 — DEMO SCRIPT
// =========================================================================
children.push(h1('8. Your demo script'))
children.push(
  p(
    'A tested seven-minute run-through. Do the setup before you are called up — never analyse a ' +
    'drawing live from cold.'
  )
)

children.push(h2('8.1 Before you present'))
const demoPrep = newList()
children.push(step('Start the stack and confirm /api/health returns "llm_enabled": true.', 0, demoPrep))
children.push(step('Create a project and upload testing/mechanical/mechanical.pdf.', 0, demoPrep))
children.push(step('Analyse 3–4 sheets and let it finish completely.', 0, demoPrep))
children.push(step('Open the Drawings page, pick a sheet with visible ductwork, and zoom to about 90% so Find Similar is ready.', 0, demoPrep))
children.push(step('Have a second browser tab on the Dashboard.', 0, demoPrep))

children.push(h2('8.2 The seven minutes'))
children.push(
  table(
    ['Time', 'Screen', 'What you do and say'],
    [
      ['0:00', '—',
        'Give the 60-second opening from section 1.4. Do not touch the computer yet — let the idea land first.'],
      ['1:00', 'Dashboard',
        '"This is a real mechanical set. We analysed four sheets in 30 seconds on a laptop CPU." Point at the totals: components detected, ductwork measured in feet, findings raised.'],
      ['2:00', 'Drawings',
        'Toggle the runs layer off and on. "Every blue line is a duct we traced and measured. Not a guess from pixels — the actual geometry from inside the PDF."'],
      ['2:45', 'Drawings',
        'Click a fire damper. Read its explanation aloud. "It does not just say 87% confident. It says: 18 by 18 point square with an internal X and a heavy side marking the rated barrier."'],
      ['3:30', 'Drawings',
        'Point at the scale panel. "Five independent methods, with the evidence shown. And if it is wrong, click two points and everything rescales."'],
      ['4:15', 'Drawings',
        'Find Similar: drag a box around one symbol. "116 matches in seven hundredths of a second. Exact geometric matching — CAD symbols are stamped from blocks." Then name it. "Now it is counted on every future drawing."'],
      ['5:15', 'Review',
        '"Counting is table stakes. This tells you which of 400 objects to look at." Open a critical or high finding and press Show on drawing.'],
      ['6:00', 'Copilot',
        'Ask "how much supply air ductwork is there, by size?" Then expand the tool trace. "It never invents a number — it queries the analysis and shows you the lookups."'],
      ['6:45', 'Exports',
        '"COCO in the dataset\'s own coordinates, a bill of quantities, and an IFC file that opens in Revit. The takeoff flows into the next tool." Close on the 99.5% figure.'],
    ],
    [900, 1700, 7480],
    { monoCols: [0], boldCols: [0] }
  )
)

children.push(h2('8.3 Things to avoid on stage'))
children.push(bullet('Do not analyse a large set live — start one before you present if you want to show progress streaming.'))
children.push(bullet('Do not try Find Similar while zoomed out; the tool disables itself and it will look like a failure.'))
children.push(bullet('Do not claim it replaces an estimator. Say it does the counting and measuring so the estimator can do the judging.'))
children.push(bullet('Do not hide the Level 1 numbers. Volunteer the caveat — it reads as rigour, not weakness.'))

children.push(pageBreak())

// =========================================================================
// PART 9 — Q&A
// =========================================================================
children.push(h1('9. Questions the judges will ask'))

const qa = [
  ['"Why not just use YOLO or a CNN?"',
    'Because the information is already exact and a CNN would throw it away. A CNN needs thousands of labelled examples per symbol, a GPU, and it still gives you a probability rather than a measurement. We get exact coordinates, sub-point measurement, explanations, and it runs in seconds on a CPU. Where learning genuinely helps — recognising a symbol nobody has catalogued — we do learn, but from geometry, and from one example rather than a thousand.'],
  ['"What if the PDF is a scan?"',
    'Then there is no vector geometry and we say so rather than guessing. That is a real limitation. The honest answer is that a scan needs a different first stage — vectorisation or OCR — feeding the same engine. Most modern issued-for-construction sets are vector, which is the market we would target first.'],
  ['"How do you know your measurements are right?"',
    'Three ways. The supplied annotated PDFs contain the exact geometry marked as duct and pipe, and we recover 99.5% of it segment for segment. We have unit tests asserting the arithmetic — including that two duct walls measure one duct length, not two. And every measured run is clickable on the drawing, so any number can be checked in one click.'],
  ['"Your Level 1 numbers look low."',
    'They do, and we report them honestly. Two things: the supplied Level 1 annotations carry confidence scores and detection ids, so they are another detector\'s output rather than hand-drawn truth, with a 2x spread in box sizes for the same component within one sheet. And on the catalogue-dense sheets our count accuracy is 62 to 73%, with 144 of 168 fire dampers found on the densest one. Our answer to the gap is the review loop rather than a better threshold.'],
  ['"What happens with a drawing convention you have never seen?"',
    'That is the Find Similar feature. Drag a box around the unfamiliar symbol, we find every instance by exact geometry, you name it once, and it is recognised on every future drawing. The system adapts to the customer rather than the other way round.'],
  ['"Is this actually deployable?"',
    'It is running now. One Docker image, one port, no GPU, no model download. There are ready blueprints for Render, Railway, Fly and Cloud Run, and CI builds the image and smoke-tests the running container on every push. A 2 GB instance handles a real set.'],
  ['"Who would pay for this and how much time does it save?"',
    'Mechanical and plumbing subcontractors bidding work, and the estimating departments of general contractors. Manual takeoff on a set like this is days of work. We produce the counts, the measured lengths and a priceable bill of quantities in under a minute, plus a review list that catches coordination problems before they become change orders.'],
  ['"What would you build next with more time?"',
    'Three things in order: flexible duct recall, which is our weakest detector; multi-sheet system tracing so a duct followed across match lines becomes one object; and pulling in the specification and equipment schedules so the copilot can reason across drawings and documents together.'],
  ['"How does the copilot avoid hallucinating numbers?"',
    'It has no numbers to hallucinate from. Nine tools read the analysis result, the model chooses which to call, and the answer shows you the calls it made. The system prompt forbids stating any figure that did not come from a tool result. And it works with no API key at all, using a deterministic router over the same tools — so it cannot fail during a demo.'],
  ['"Is the drawing scale reliable?"',
    'Five independent estimators, each with its own confidence and evidence, and agreement between two of them raises confidence further. When it is unsure it says so and raises a validation finding rather than quietly producing wrong lengths. And a reviewer can recalibrate from two clicked points in seconds.'],
]

qa.forEach(([q, a]) => {
  children.push(
    new Paragraph({
      spacing: { before: 200, after: 60 },
      children: [new TextRun({ text: q, bold: true, size: 21, color: BRAND })],
    })
  )
  children.push(p(a))
})

children.push(pageBreak())

// =========================================================================
// PART 10 — FUTURE WORK
// =========================================================================
children.push(h1('10. Extending the system'))
children.push(
  p(
    'If a judge asks "what would you change next?", or if you carry this on after the hackathon, ' +
    'this section is the map.'
  )
)

children.push(h2('10.1 Where to change what'))
children.push(
  table(
    ['If you want to...', 'Edit this'],
    [
      ['Add a new component symbol', 'CATALOGUE in symbols.py, then ideal_symbols() in shapes.py'],
      ['Change how strict detection is', 'ACCEPT thresholds in shapes.py'],
      ['Add a validation rule', 'RULES and run_validation() in validate.py'],
      ['Support a new size-tag format', 'The regexes at the top of linear.py'],
      ['Add a scale estimator', 'A new scale_from_*() in scale.py, then register it in detect_scale()'],
      ['Add an export format', 'exporters.py and the _EXPORTS map in app/main.py'],
      ['Give the copilot a new skill', 'A tool function in copilot.py plus its OPENAI_TOOLS entry'],
      ['Change the trade clearances', 'TRADE_CLEARANCE_IN in clash.py'],
      ['Add a screen to the UI', 'A page in frontend/src/pages, then the NAV array in App.jsx'],
    ],
    [4200, 5880],
    { monoCols: [1] }
  )
)

children.push(h2('10.2 The roadmap, in priority order'))

children.push(h3('1. Flexible duct recall — the biggest single win'))
children.push(
  p(
    'Currently 0.84 precision at 0.26 recall, deliberately tuned to avoid reporting junk. The cause ' +
    'is that curved flexible duct changes its hash-mark length as it bends, so bucketing ticks by ' +
    'length breaks the run at every curve — but bucketing by angle alone floods each group with ' +
    'unrelated segments. The fix is a chaining algorithm that tolerates gradual length drift while ' +
    'still rejecting the curve-flattening chords. This alone would lift the Level 1 aggregate ' +
    'noticeably, since flexible duct is the only annotated class on roughly a third of the sheets.'
  )
)

children.push(h3('2. Multi-sheet system tracing'))
children.push(
  p(
    'Today each sheet is analysed independently. Real systems continue across match lines onto other ' +
    'sheets. Following the match-line callouts, which are already parsed as text, would let a duct ' +
    'main become one object across a whole floor — and would make the connectivity analysis and ' +
    'orphan detection far more meaningful.'
  )
)

children.push(h3('3. True 3-D clash detection'))
children.push(
  p(
    'Elevations are often written on the drawing as annotations — "BOD +10\'-6"". Parsing those would ' +
    'turn the 2-D screening pass into genuine clearance checking, and would let the IFC export place ' +
    'elements at their real height rather than at the storey datum.'
  )
)

children.push(h3('4. Multi-modal reasoning across documents'))
children.push(
  p(
    'The copilot currently reasons over drawings alone. Adding the specification, the equipment ' +
    'schedules and the applicable code sections would let it answer questions like "does this ' +
    'diffuser meet the airflow in the schedule?" — which is the Level 4 ambition of the brief.'
  )
)

children.push(h3('5. Production hardening'))
children.push(bullet('Authentication and per-project access control — there is none today.'))
children.push(bullet('Move the job queue out of process so analyses survive a restart.'))
children.push(bullet('Object storage for uploads and renders instead of a local disk.'))
children.push(bullet('A Playwright test suite — the layout bug we hit was invisible to jsdom because jsdom performs no layout.'))

children.push(pageBreak())

// =========================================================================
// APPENDIX
// =========================================================================
children.push(h1('Appendix A — Glossary'))
children.push(
  p('Terms a judge from an engineering background will use, and what they mean in this system.')
)
children.push(
  table(
    ['Term', 'Meaning'],
    [
      ['MEP', 'Mechanical, Electrical and Plumbing — the building services trades'],
      ['Takeoff', 'Counting and measuring everything on a drawing in order to price it'],
      ['BOQ', 'Bill of quantities — the priceable line-item list a takeoff produces'],
      ['Diffuser', 'A ceiling outlet that distributes supply air into a room'],
      ['Register / grille', 'A ceiling or wall opening that returns or exhausts air'],
      ['Fire damper', 'A device in ductwork that closes where the duct crosses a fire-rated wall'],
      ['Flexible duct', 'Flexible ducting connecting a rigid branch to an air terminal'],
      ['Run', 'A continuous length of duct or pipe traced as one object'],
      ['Service', 'What a run carries — supply air, sanitary sewer, natural gas, and so on'],
      ['Sheet', 'One page of a drawing set, with its own number, title and scale'],
      ['Title block', 'The bordered panel carrying the sheet number, title and scale'],
      ['Screened linework', 'Background drawing plotted in light grey for reference'],
      ['Pen weight', 'The plotted thickness of a line — carries meaning in CAD drawings'],
      ['IFC', 'Industry Foundation Classes — the open BIM interchange format'],
      ['BCF', 'BIM Collaboration Format — how coordination issues are exchanged'],
      ['COCO', 'A standard JSON format for object-detection annotations'],
    ],
    [2900, 7180]
  )
)

children.push(h2('Appendix B — Repository map'))
children.push(
  code([
    'backend/',
    '  mepiq_core/          the engine (no web framework, no I/O assumptions)',
    '  app/                 FastAPI: uploads, jobs, results, review, exports, copilot',
    '  tests/               39 tests, no dataset required',
    '  evaluate_dataset.py  reproducible evaluation against the supplied annotations',
    'frontend/',
    '  src/pages/           one file per screen',
    '  src/components/      SheetCanvas is the drawing viewer',
    '  src/store/           RTK Query api + uiSlice + viewerSlice',
    '  test/                layout invariants and page smoke tests',
    'deploy/                Render, Railway, Fly.io, Vercel blueprints',
    'docs/                  architecture, deployment, problem statement, this manual',
    'evaluation/            RESULTS.md and the measured evaluation output',
    'docker-compose.yml     two-tier stack',
    'Dockerfile             single-container build (API serves the UI)',
    'run-lan.ps1            serve on your network for a demo',
  ])
)

children.push(h2('Appendix C — One-page cheat sheet'))
children.push(
  callout(
    'The five things to remember:',
    '(1) Construction PDFs are vector files — we read the CAD geometry instead of guessing from ' +
      'pixels. (2) That makes measurements exact, detections explainable, and the whole thing run ' +
      'in seconds on a CPU. (3) We recover 99.5% of the ground-truth duct and pipe geometry, which ' +
      'is the 40%-weighted level. (4) Every detection explains itself in engineering language and ' +
      'can be confirmed or rejected in one click. (5) Name an unknown symbol once and it is counted ' +
      'on every drawing from then on.',
    'ok'
  )
)

// ---------------------------------------------------------------------------
// Assemble
// ---------------------------------------------------------------------------

const doc = new Document({
  creator: 'MEPIQ',
  title: 'MEPIQ — User Manual & Technical Guide',
  description: 'User manual and technical guide for the MEPIQ MEP drawing intelligence platform',
  styles: {
    default: {
      document: { run: { font: 'Calibri', size: 21, color: INK } },
    },
  },
  numbering: {
    config: [
      {
        reference: 'dot-list',
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 460, hanging: 240 } } } },
          { level: 1, format: LevelFormat.BULLET, text: '◦', alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 900, hanging: 240 } } } },
        ],
      },
      {
        reference: 'num-list',
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
            start: 1,
            style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: PAGE_W, height: 15840 },
          margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              alignment: AlignmentType.RIGHT,
              spacing: { after: 80 },
              border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: RULE, space: 6 } },
              children: [
                new TextRun({ text: 'MEPIQ — User Manual & Technical Guide', size: 17, color: MUTED }),
              ],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.RIGHT,
              children: [
                new TextRun({ text: 'CTD 2026 AI Hackathon    ', size: 17, color: MUTED }),
                new TextRun({ children: [PageNumber.CURRENT], size: 17, color: MUTED, bold: true }),
              ],
            }),
          ],
        }),
      },
      children,
    },
  ],
})

Packer.toBuffer(doc).then((buf) => {
  const out = process.argv[2] || 'MEPIQ_User_Manual.docx'
  fs.writeFileSync(out, buf)
  console.log(`Wrote ${out} (${(buf.length / 1024).toFixed(0)} KB, ${children.length} blocks)`)
})
