# MEPIQ — Design Management for MEP Drawings with AI

**CTD 2026 AI Hackathon submission.** A deployed web application that reads Mechanical,
Electrical and Plumbing construction drawings, detects and counts the components on them,
traces and measures every duct and pipe run, validates the design against engineering rules,
screens for cross-discipline conflicts, and answers questions about all of it in plain English.

> The original problem statement is preserved verbatim at
> [`docs/PROBLEM_STATEMENT.md`](docs/PROBLEM_STATEMENT.md).

---

## The idea in one paragraph

Construction PDFs are not pictures. They are vector CAD exports: every duct wall, every
diffuser and every pipe is still in the file as geometry, with its stroke colour and pen
weight intact. Almost every tool in this space throws that away — it rasterises the sheet and
asks a CNN to find a twenty-pixel symbol. **MEPIQ reads the geometry instead.** That single
decision is why a duct length here is exact rather than approximate, why a detection can
explain itself in engineering language, and why the whole thing runs in seconds on a laptop
with no GPU and no training run.

Two findings from the supplied dataset drove the design, and both are reproducible with the
evaluation script in this repository:

1. **Publishers screen the background.** The architectural underlay is plotted grey; the
   discipline's own systems stay full black. Splitting on luminance separates *my scope* from
   *context* with no heuristics about content.
2. **Pen weight is a layer table.** Within the foreground, run linework is drawn at one
   consistent, heavier weight. Selecting that class **reproduces 99.5 % of the ground-truth
   duct and pipe geometry, segment for segment** — 100 % on 27 of 28 mechanical sheets.

---

## What it does

| Level | Capability | How |
|---|---|---|
| **1** | Detect, classify and count quantifiable components; JSON/CSV/COCO output | Legend-driven shape grammar + exact geometric template propagation |
| **2** | Trace and measure AC vent and pipe runs, with scale and connectivity | Foreground/weight layer recovery, duct-wall pairing, run chaining, five-way scale detection |
| **3** | Natural-language querying, explanations, engineering summaries | Tool-calling copilot over the extracted data — works with **or without** an LLM key |
| **4** | Design validation, risk rules, 2-D clash screening, IFC/BCF export, feedback learning | 12-rule engine, cross-sheet overlay, IFC4 writer, learn-once symbol library |

### The parts worth looking at

- **Explainable detections.** Every component carries a sentence: *"18.0 × 18.0 pt square with
  two corner diagonals and a 3.1 pt central circle"*. Not a confidence score you have to trust.
- **Ductwork is not double-counted.** Rectangular duct is drawn as two parallel lines. MEPIQ
  pairs the walls and measures the centreline — the *correct* quantity — and gets the duct
  width for free, which becomes a size takeoff. (`test_measured_duct_is_not_double_counted`)
- **Scale detection with provenance.** Five independent estimators (title block, dimension
  strings, duct tags, known component sizes, sheet size), each reporting its own confidence and
  reasoning. Agreement between two of them raises confidence. The UI shows *why* it believes a
  sheet is 1/4" = 1'-0", and a reviewer can recalibrate by clicking two points.
- **Find-similar visual search.** Drag a box around any symbol; every identical stamp on the
  sheet is found by rigid-transform geometry matching. On a dense mechanical sheet: **116
  matches in 0.07 s**. This is the workflow estimators already use in Bluebeam — made exact.
- **The library learns.** Name a symbol once and every occurrence is counted automatically,
  on that sheet, on the rest of the set, and on every drawing analysed afterwards. The product
  adapts to a firm's drawing conventions instead of the other way round.

---

## Running it

### Docker Compose — the whole stack

```bash
cp .env.example .env          # optional: add OPENAI_API_KEY
docker compose up --build
```

- App: <http://localhost:8080>
- API docs: <http://localhost:8000/docs>

### Sharing it on your network

Other machines on the same Wi-Fi or LAN can use it with no rebuild — the frontend calls the API
on whatever host the browser used, so a LAN IP just works.

```powershell
.\run-lan.ps1                          # prints the URL to share
.\run-lan.ps1 -OpenFirewall -NoBuild   # once, from an admin prompt
```

```bash
./run-lan.sh                           # macOS / Linux
```

The script finds your LAN address, waits for the API to report healthy, and prints
`http://192.168.x.x:8080` for you to hand out. Windows Firewall is the usual reason a colleague
cannot connect; `-OpenFirewall` adds the inbound rules for private networks.

To keep it to your machine only, set `MEPIQ_BIND=127.0.0.1` in `.env`.

### Single container — one image, one port

```bash
docker build -t mepiq .
docker run -p 8000:8000 -v mepiq-data:/data mepiq
```

Open <http://localhost:8000>. The API serves the built React bundle from the same origin, so
there is no CORS setup and nothing to keep in sync. This is the image the deploy configs use.

### Local development — no Docker

One command, either platform. It installs dependencies on the first run, loads `.env`, starts
both processes and opens the browser.

```powershell
.\run-local.ps1          # Windows PowerShell
```

```bash
./run-local.sh           # macOS / Linux
```

Or by hand:

```bash
# Terminal 1 — API
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2 — web
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

### Deploying

Ready-to-use configs are in [`deploy/`](deploy/) — Render, Railway, Fly.io and Vercel. The
step-by-step guide is [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The short version for Render:
push to GitHub → New → Blueprint → pick the repo. One service, one URL, persistent disk.

---

## Using it

1. **Projects** — create a project, drop in a PDF. A whole bid set is fine: MEPIQ triages every
   page, works out which are MEP plans, and analyses those.
2. **Dashboard** — totals, counts by type, findings by severity, a sheet index.
3. **Drawings** — the reviewer. Pan and zoom the sheet with detections, traced runs, findings
   and clashes overlaid as live vector geometry. Click anything to see how it was identified,
   confirm or reject it. Drag-select a symbol to count every copy of it.
4. **Quantities** — component counts, every measured run, and a bill of quantities.
5. **Review** — findings with severity and a jump-to-location, plus the unnamed symbols the
   engine found repeating, ready to be named in one click.
6. **Coordination** — cross-discipline conflicts.
7. **Copilot** — ask anything; every number is fetched from the analysis and cited.
8. **Exports** — COCO, CSV, BOQ, IFC4, BCF-shaped issues, full JSON.

---

## Results

Measured with [`backend/evaluate_dataset.py`](backend/evaluate_dataset.py) against the supplied
annotations. Full detail and honest caveats: [`evaluation/RESULTS.md`](evaluation/RESULTS.md).

```bash
cd backend
python evaluate_dataset.py --dataset "../CTD Dataset/CTD Dataset" --out ../evaluation
```

**Level 2 — linear measurement (44 sheets)**

| Metric | Result |
|---|---|
| Ground-truth geometry recovered | **99.5 %** |
| Mechanical sheets | **100 %** on 27 of 28 |
| Plumbing / fire protection | 94.4 % |
| Selection precision | 86.5 % |
| Time per sheet | 0.3 – 3 s |

**Level 1 — detection and counting (29 mechanical sheets)**

| Metric | All sheets | Catalogue-dense sheets |
|---|---|---|
| Precision @ IoU 0.3 | 0.45 | 0.58 – 0.82 |
| Recall @ IoU 0.3 | 0.47 | 0.67 – 0.83 |
| F1 | 0.46 | 0.68 – 0.77 |
| Count accuracy | 0.40 | 0.62 – 0.73 |
| Time per sheet | 2 – 7 s | |

The supplied Level 1 annotations carry `score` and `orig_detection_id` fields — they are
another detector's output rather than hand-drawn truth, and box extents for one component type
vary by more than 2× within a single sheet. We report against them anyway, and say plainly
where that flatters or penalises us. See the caveats section in `evaluation/RESULTS.md`.

---

## Layout

```
backend/
  mepiq_core/          the engine — no web framework, no I/O assumptions
    pdfdoc.py          vector primitive extraction, screened/foreground split
    geometry.py        polygons, circles, hatch runs, parallel pairs, spatial indexes
    shapes.py          legend-driven shape classification (Level 1)
    matching.py        exact rigid-transform geometric hashing
    symbols.py         component catalogue, detection pipeline, glyph mining, library
    linear.py          layer recovery, duct centrelines, run chaining, measurement (Level 2)
    scale.py           five scale estimators with provenance and confidence
    discipline.py      sheet triage: which trade, and is it a plan?
    validate.py        12 design-validation and constructability rules (Level 4)
    clash.py           cross-discipline 2-D coordination screen (Level 4)
    exporters.py       COCO, CSV, BOQ, IFC4, BCF
    pipeline.py        end-to-end orchestration with progress reporting
  app/                 FastAPI: uploads, jobs, results, review, exports, copilot
  tests/               39 tests, no dataset required
  evaluate_dataset.py  reproducible evaluation against the supplied annotations
frontend/              React 18 + Vite + Redux Toolkit (RTK Query)
deploy/                Render, Railway, Fly.io, Vercel
docs/                  architecture, deployment, problem statement
```

## Testing

```bash
cd backend && pytest -q              # 39 tests
cd frontend && npm run build         # production bundle
```

CI (`.github/workflows/ci.yml`) runs both, then builds the Docker image and smoke-tests the
running container.

---

## Honest limits

- **2-D is 2-D.** Clash screening overlays plan geometry; it cannot know elevations. Findings
  are candidates for a human to check, and the app says so.
- **Scanned drawings are out of scope.** MEPIQ needs a vector PDF. A raster scan will produce
  no geometry, and the app reports that rather than guessing.
- **Not a certified takeoff.** It is a review aid that shows its working, so an engineer can
  check any number in one click.
- **Electrical detection is library-driven.** The supplied catalogue defines mechanical
  symbols geometrically; electrical symbols are counted by glyph mining and named by the
  reviewer, which is exact for counting but needs one naming pass per drawing convention.
