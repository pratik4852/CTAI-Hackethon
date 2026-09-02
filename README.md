# MEPIQ — Design Management for MEP Drawings with AI

**CTD 2026 AI Hackathon submission.** A deployed web application that reads Mechanical,
Electrical and Plumbing (MEP) construction drawings, detects and counts the components on them,
traces and measures every duct and pipe run, validates the design against engineering rules,
screens for cross-discipline conflicts, and answers questions about all of it in plain English.

### 🔗 Live application — **http://13.207.8.179/#/projects**

| | |
|---|---|
| **Live app** | http://13.207.8.179/#/projects |
| **Live API health** | http://13.207.8.179/api/health |
| **Live API docs (interactive)** | http://13.207.8.179/docs |
| **Problem statement** | [`docs/PROBLEM_STATEMENT.md`](docs/PROBLEM_STATEMENT.md) |
| **Full user manual (28 pp)** | [`docs/MEPIQ_User_Manual.docx`](docs/MEPIQ_User_Manual.docx) |
| **Measured results** | [`evaluation/RESULTS.md`](evaluation/RESULTS.md) |
| **Architecture deep-dive** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |

---

# For the verifier — start here

This section is written for someone who has five to fifteen minutes and needs to confirm the
system does what it claims. Everything below is checkable, and where a claim has a limit we
state it rather than waiting for you to find it.

## 1. The claim in one paragraph

A construction PDF is **not a picture**. When an engineer publishes a sheet from Revit or
AutoCAD, the result is a vector document: every duct wall, diffuser and pipe is still inside
the file as geometry, with exact coordinates, stroke colour and pen weight intact. Nearly every
AI approach in this space rasterises the sheet and runs object detection on the image, throwing
that exact information away. **MEPIQ reads the geometry directly.** That is why its measurements
are exact rather than estimated, why every detection can explain itself in engineering language,
and why a sheet analyses in seconds on a CPU with no model training at all.

## 2. Five-minute verification path

> **Open a *mechanical* project.** MEPIQ's component catalogue is HVAC, so mechanical and
> plumbing sheets exercise the full pipeline. Electrical sheets deliberately show no components
> until a symbol is taught (see §6) — running HVAC rules on switchgear would invent air
> terminals that are not there.

| # | Do this | What you should see | Which claim it proves |
|---|---|---|---|
| 1 | Open the live URL, pick a mechanical project, go to **Dashboard** | Component totals, ductwork measured in feet, findings by severity, a sheet index | End-to-end pipeline works |
| 2 | Go to **Drawings**, select a mechanical sheet | The sheet renders with coloured overlays: boxes on components, lines along traced ducts | Level 1 + Level 2 output, on the drawing |
| 3 | Toggle the **Duct / pipe runs** layer off and on | Every traced run highlights. Zoom in — the lines sit exactly on the drawn ductwork | Measurement is on real geometry, not approximate |
| 4 | Click any component box | Right panel shows a zoomed crop plus a sentence of geometric evidence, e.g. *"18.0 x 18.0 pt square with an internal 'X'; heavy 1.32 pt side indicates the rated barrier"* | Detections are explainable, not opaque scores |
| 5 | Read the **Drawing scale** panel | The scale, a confidence %, the method used, and the evidence — e.g. *"26/78 dimension annotations agree"* | Scale detection has provenance |
| 6 | Zoom to ~90%, click the **⬚** tool, drag a box round one symbol | Every identical stamp on the sheet is found and counted, typically in under 0.1 s | Exact geometric matching |
| 7 | Go to **Quantities → Duct & pipe runs** | Every traced run with measured length, size, service (Supply Air, Sanitary Sewer…) and new/existing status | Level 2 deliverable |
| 8 | Go to **Review** | Findings sorted by severity with recommendations and jump-to-location | Level 4 design validation |
| 9 | Go to **Copilot**, ask *"how much ductwork is there by size?"*, then expand the tool-call trace | An answer with figures, and the list of data lookups that produced them | Level 3, and that it does not invent numbers |
| 10 | Go to **Exports**, download the COCO JSON and the IFC | Valid COCO at the dataset's own 150-DPI coordinates; a loadable IFC4 file | Structured output |

## 3. Verify the claims yourself, without trusting the UI

**The live API is open — paste these into a browser or terminal:**

```bash
# Is it up, and is the LLM copilot enabled?
curl http://13.207.8.179/api/health

# The component catalogue and all 12 validation rules
curl http://13.207.8.179/api/catalogue

# Every project and document on the instance
curl http://13.207.8.179/api/projects
```

Interactive API documentation, generated from the code, is at **http://13.207.8.179/docs**.

**Reproduce the accuracy numbers on your own machine:**

```bash
cd backend
pip install -r requirements.txt
python evaluate_dataset.py --dataset "../CTD Dataset/CTD Dataset" --out ../evaluation
```

This scores against the annotations shipped with the dataset and writes `evaluation.json`.
It is the same code path the application uses — not a separate offline script.

**Run the test suite:**

```bash
cd backend  && pytest -q                    # 39 tests, no dataset required
cd frontend && node test/check-layout.mjs   # 7 UI layout invariants
```

## 4. Measured results

Full detail and per-sheet tables: [`evaluation/RESULTS.md`](evaluation/RESULTS.md).

### Level 2 — linear measurement (40% of the grade)

This is the level with unambiguous ground truth. The dataset's `_detected_hvac.pdf` and
`_detected_pipelines.pdf` files contain the exact vector geometry marked as duct or pipe, so we
compare **segment for segment**, not by bounding box.

| Metric | Result |
|---|---:|
| Ground-truth geometry recovered | **99.5%** |
| Mechanical sheets at exactly 100% recall | **27 of 28** |
| Plumbing / fire protection | 94.4% |
| Selection precision | 86.5% |
| Sheets at 100% recall, all disciplines | 40 of 44 |
| Time per sheet | 0.3 – 3 s |

### Level 1 — detection and counting (35% of the grade)

| Metric | All 29 sheets | Catalogue-dense sheets |
|---|---:|---:|
| Precision @ IoU 0.3 | 0.45 | 0.58 – 0.82 |
| Recall @ IoU 0.3 | 0.47 | 0.67 – 0.83 |
| F1 | 0.46 | 0.68 – 0.77 |
| Count accuracy | 0.40 | 0.62 – 0.73 |

**The caveat, stated up front.** The Level 1 annotations in the dataset are not hand-drawn
ground truth — every record carries a `score` field (values as low as 0.61) and an
`orig_detection_id`, so they are another detector's output. Within a single sheet, boxes for one
component type vary from 26.5 × 18.8 px to 53.0 × 37.5 px, a 2× spread; several sheets label
only one class while the drawing plainly contains others; one ductwork plan carries 3
annotations for a sheet with hundreds of components. Errors therefore run both ways — precision
is penalised for finding real components nobody labelled, recall for instances whose reference
boxes disagree with the drawn extents. On the densest sheet MEPIQ finds **144 of 168 fire
dampers (86% of the count)** at 0.86 class-agnostic localisation recall.

### Speed

| Operation | Time |
|---|---:|
| Parse a 100,000-primitive sheet | 1.3 s |
| Detect components, dense mechanical sheet | 2 – 5 s |
| Trace and measure ductwork | 0.3 – 3 s |
| Find-similar search (116 matches) | **0.07 s** |
| Triage a 25-page bid set | 1.5 s |

No GPU, no model download, no training step. The engine is fully deterministic — the same PDF
produces the same numbers every time, which matters when output goes into a bid.

## 5. How the four levels are addressed

| Level | Requirement | Where you see it | How it works |
|---|---|---|---|
| **1** (35%) | Detect, classify, count; bounding boxes, confidence, structured JSON/CSV | Drawings, Quantities; COCO + CSV exports | Legend-driven shape grammar, exact template propagation, unsupervised glyph mining |
| **2** (40%) | Detect linear objects; measure AC vent and pipe lengths using the drawing scale | Runs overlay; Quantities → Runs tab | Pen-weight layer recovery, duct-wall pairing into centrelines, endpoint-graph run chaining, five-way scale detection |
| **3** (15%) | Natural-language querying, explain issues, engineering summaries | Copilot | Nine tools over the analysis; LLM chooses and explains, never recalls figures; deterministic fallback with no API key |
| **4** (+10%) | Corrective recommendations, risk ID, cross-discipline coordination, BIM integration, feedback learning | Review, Coordination, Library, Exports | 12-rule engine, 2-D clash screen, IFC4 + BCF export, learn-once symbol library |

## 6. Known limits — stated, not hidden

- **Electrical sheets show no components until a symbol is taught.** The supplied catalogue
  defines HVAC symbols geometrically; there is no equivalent for electrical. Running the HVAC
  grammar on an electrical sheet would invent air terminals from switchgear, so it is disabled
  by discipline. On an electrical sheet, use **Find similar** to name a receptacle once — from
  then on it is counted automatically, on that sheet and every future drawing. This is the
  feedback-learning design working as intended, but it does mean electrical needs one setup step.
- **2-D is 2-D.** Clash screening overlays plan geometry and cannot know elevations. Findings
  are candidates for a human to check, and the app says so on screen.
- **Scanned drawings are out of scope.** MEPIQ needs a vector PDF. A raster scan yields no
  geometry, and the app reports that rather than guessing.
- **Flexible duct detection is tuned for precision over recall** (0.84 / 0.26). Curved flexible
  duct changes its hash-mark length as it bends, which breaks run chaining. This is the single
  biggest improvement still available and is documented in the roadmap.
- **Not a certified takeoff.** It is a review aid that shows its working, so an engineer can
  check any number in one click.
- **No authentication.** Fine for a demo on a trusted network; it would need auth before any
  real deployment.

---

# How it works

## The two discoveries behind the engine

Both were found by analysing the supplied dataset, and both are reproducible with
`backend/evaluate_dataset.py`.

**1. Publishers screen the background.** CAD software plots the architectural reference drawing
(walls, grid, room outlines) in light grey and keeps the discipline's own systems at full black.
So one brightness test separates "the work I am responsible for" from "context":

```python
is_foreground = luminance <= 0.35 or saturation >= 0.12
```

**2. Pen weight is a hidden layer table.** Within that foreground, duct and pipe run linework is
drawn at one consistent, heavier pen weight than tags, leaders and hatching. Selecting that
class recovers **99.5%** of the ground-truth duct and pipe geometry — 100% on 27 of 28
mechanical sheets.

## Level 1 — three mechanisms working together

**Legend-driven shape classification.** The dataset ships a symbol catalogue that defines each
component *in words*: "a square with an X and a central circle", "a square with a single
diagonal", "concentric circles". So instead of learning what those look like from pixels, MEPIQ
**draws them from the definition** and compares. Candidates are normalised to a 40 × 40 binary
raster and scored over four rotations and their mirrors. The score is the harmonic mean of
*coverage* (how much of the symbol is present) and *cleanliness* (how much of the candidate the
symbol explains) — coverage alone misses a symbol with a stroke absent, cleanliness alone accepts
a blob containing the symbol plus a lot else.

**Exact template propagation.** Classification only sees a symbol when clustering isolated it;
wherever a diffuser is fused to the flex duct feeding it, the blob is too big to recognise. So
each confident instance is lifted as a template and the sheet is searched for rigid copies by
geometric hashing. Because CAD symbols are stamped from blocks, this is an *exact* match rather
than a similarity score.

**Glyph mining.** Separately, geometry that repeats verbatim is mined with exact counts — finding
every repeated component, including ones nobody has ever labelled. These surface in the Review
queue for one-click naming.

## Level 2 — tracing and measuring

1. **Recover the system linework.** Stroke classes are ranked by
   `length × √(weight / max_weight) × (1 + 2.5 × tag_affinity)`. Tag affinity is the drawing
   telling us the answer directly — engineers write the size beside the line, so whichever
   stroke class the tags sit on is the system. That settles cases pen weight alone cannot: on
   many plumbing sheets the pipes are dashed, so the system class has *more, shorter* strokes
   than the architecture.
2. **Collapse duct walls into centrelines.** Rectangular duct is drawn as two parallel lines.
   Pairing them turns 2 × L of linework into 1 × L of duct **with a known width** — the correct
   quantity plus a free size takeoff. Measuring the linework instead double-counts every duct,
   which is the classic error when taking ductwork off a PDF.
   Asserted by `test_measured_duct_is_not_double_counted`.
3. **Chain into runs.** Segments are snapped into an endpoint graph and walked while the path is
   unambiguous, so an elbow becomes one run rather than two.
4. **Attribute and convert.** Size and service come from the printed annotations, parsed into
   structured values:

| Tag on the drawing | What MEPIQ reads |
|---|---|
| `42/20 SA` | Rectangular duct, 42 × 20 in, Supply Air |
| `12ø EA` | Round duct, 12 in diameter, Exhaust Air |
| `(N)2"LW` | New 2 in pipe, Laboratory Waste |
| `(E)4"SS` | Existing 4 in pipe, Sanitary Sewer |

## Drawing scale — five independent estimators

| Estimator | Signal | Confidence |
|---|---|---|
| `title_block` | The scale printed on the sheet | 0.86 – 0.98 |
| `dimension_string` | A dimension annotation on a line of known drawn length | 0.55 – 0.92 |
| `duct_tag` | A duct tagged 42/20 must be 42 in across, so its drawn gap fixes the scale | 0.45 – 0.90 |
| `known_component` | Square ceiling diffusers sit in a 24 in ceiling module | 0.35 – 0.80 |
| `sheet_size` | Last-resort prior from the paper size | 0.20 |

Agreement between two independent estimators raises confidence by 0.10. Losing candidates are
kept and shown in the UI. A reviewer can recalibrate by clicking two points and typing the real
distance. When confidence is low, rule **MEP-008** fires rather than quietly producing wrong
lengths.

## Level 4 — the twelve validation rules

| Rule | Checks | Severity |
|---|---|---|
| MEP-001 | A run that connects to nothing | High |
| MEP-002 | An air terminal with no ductwork reaching it | High |
| MEP-003 | Runs with no size/service tag — cannot be priced | Medium |
| MEP-004 | Duct size reduces then increases along a run | Medium |
| MEP-005 | A fire damper not on any traced duct | Medium |
| MEP-006 | A duct penetrating a rated wall with no damper | **Critical** |
| MEP-007 | An unusually long run with no branch | Low |
| MEP-008 | The drawing scale could not be confirmed | High |
| MEP-009 | A repeated symbol not in the library | Low |
| MEP-010 | Existing services shown as modified | Info |
| MEP-011 | Air terminal spacing outside the usual 8–20 ft | Low |
| MEP-012 | A branch too small for the terminal it feeds | Medium |

---

# Technology choices — what we used, and why

Every dependency here was chosen for a reason we can defend. The list is deliberately short:
each addition is a thing that can break during judging, so anything that did not earn its place
was left out.

## The whole stack

| Layer | Choice | Why this, and not the obvious alternative |
|---|---|---|
| **PDF geometry** | **PyMuPDF (fitz)** | The decision the whole project rests on. It exposes the raw vector drawing operators — coordinates, stroke colour, pen width, dash pattern — not just rendered pixels. `pdfplumber` and `PyPDF2` cannot give per-path pen weight, and pen weight turned out to be the hidden layer table that makes Level 2 work. It also renders to raster for the viewer, so one library covers both needs. |
| **Numerics** | **NumPy** | Shape matching compares a candidate against ~50 rotated and mirrored templates. Vectorising that as three array reductions instead of 50 Python loops took a sheet from 35 s to 3.6 s. That is the only place we need array maths, so nothing heavier was justified. |
| **Web framework** | **FastAPI** | Async support for the SSE progress stream, automatic OpenAPI docs at `/docs` (which doubles as a verification surface), and Pydantic request validation for free. Flask would have needed all three bolted on; Django is a large framework for a 15-endpoint API with no admin, no ORM and no templates. |
| **Server** | **Uvicorn** | The standard ASGI server for FastAPI, and it streams server-sent events cleanly. |
| **Database** | **SQLite** | The data is projects, documents, jobs, reviews and chat — a few thousand rows. SQLite means the whole deployment is one file with no separate service to run, no connection pool and no migration story. Postgres would add an entire container for no benefit at this scale. |
| **Analysis storage** | **JSON files on disk** | An analysis result is 1–15 MB of geometry that is always read whole and never queried by field. Putting that in a database column would be storing a blob and calling it a schema. |
| **Frontend framework** | **React 18** | The drawing viewer is heavily stateful — zoom, pan, tool mode, layer toggles, selection, filters — which is exactly what a component model handles well. Also the largest hiring pool, which matters for a project meant to be continued. |
| **Build tool** | **Vite** | Sub-second hot reload during development and a 1.5 s production build. Webpack would have cost minutes per iteration across a build this size. |
| **State management** | **Redux Toolkit + RTK Query** | Not for the ceremony — for **cache invalidation**. When a reviewer rejects a detection, one mutation invalidates the `Result` tag and the dashboard, quantities table and exports all refresh themselves. Hand-rolling that consistency across nine screens is where bugs live. RTK Query also removed the need for a separate data-fetching library. |
| **Routing** | **React Router (hash mode)** | Hash routing means the SPA works on any static host with no server rewrite rules — which is why `http://13.207.8.179/#/projects` works from a plain nginx container with zero configuration. |
| **Styling** | **Hand-written CSS with custom properties** | A dark, CAD-like palette with three-state theming was faster to write directly than to fight a framework's defaults. It also keeps the bundle at 100 kB gzipped with no build-time CSS pipeline. Tailwind would have added a toolchain step for styling we only do once. |
| **Charts** | **None — hand-drawn SVG/CSS** | The dashboard needs horizontal bars and severity counts. A charting library would have added ~200 kB for shapes that are twenty lines of CSS. |
| **LLM** | **OpenAI `gpt-4o-mini` via tool calling** | Cheap, fast, and reliable at *choosing tools* — which is all we ask of it. It never produces figures; nine tools read the analysis and the model explains what comes back. A deterministic router answers the same questions with no key at all, so the demo cannot fail on a quota. |
| **Containers** | **Docker + Compose, plus a single-container build** | Compose for local two-tier development; one combined image for deployment, because most hosts want one image on one port with no reverse proxy and no CORS. |
| **Web server (prod)** | **nginx** | Serves the static bundle and proxies `/api`, with buffering disabled so the SSE progress stream is not held back. |
| **Testing** | **pytest + jsdom + static layout checks** | pytest for the engine using synthetic PDFs generated with PyMuPDF, so CI needs no dataset. jsdom renders every page against a live API. The static layout checks exist because jsdom performs no layout — it once reported 9/9 green on a page whose viewer had collapsed to zero height. |
| **CI** | **GitHub Actions** | Runs the tests, builds the image, and smoke-tests the running container on every push. |
| **Hosting** | **AWS EC2 (Mumbai), single container** | One `docker run` on a small instance. No managed services, so the whole deployment is reproducible from the repo. |

## What we deliberately did **not** use

This is usually the more revealing list.

| Not used | Why not |
|---|---|
| **YOLO / Detectron / any CNN** | The information we need is already exact in the file. A CNN would need thousands of labelled examples per symbol and a GPU, and would still return a probability where we can return a measurement. Where learning genuinely helps — recognising a symbol nobody catalogued — we learn from **geometry**, from one example rather than a thousand. |
| **OpenCV** | It was used during exploration to test raster template matching, which was measured at **0.05 precision** against 0.96 for the geometric approach. Once that comparison was made, the dependency had nothing left to do and was removed. |
| **Tesseract / OCR** | The PDFs carry real embedded text. Extracting it is exact and instant; OCR would introduce errors into the size tags that drive both scale detection and the takeoff. |
| **A vector database / RAG** | The copilot answers from a structured analysis result, not from a document corpus. Nine typed tools over real data beat semantic search over text chunks when the questions are "how many" and "how long". |
| **Celery / Redis / RabbitMQ** | Analysis is CPU-bound and finishes in seconds. An in-process thread pool with SSE progress gives the same user experience without two more services to deploy and monitor. (This is the first thing to change for multi-user production — see the roadmap.) |
| **An ORM** | Six tables, hand-written SQL, no migrations. An ORM would be more code and more indirection than the queries it replaces. |
| **A component library (MUI, Chakra…)** | The UI is a specialist drawing tool, not a CRUD dashboard. Almost every screen needed custom layout anyway, so a library would have been overridden more than used. |
| **Cloud AI document APIs** (Azure Document Intelligence, AWS Textract, Google Document AI) | They are built for forms and tables, not CAD geometry, and none returns pen weight or exact stroke coordinates. They would also add per-page cost, network latency, and a dependency on someone else's uptime during judging. |

## Why the architecture is shaped this way

Three structural decisions, each with a reason a reviewer can check in the code:

**`mepiq_core` has no web framework and no I/O assumptions.** It is a pure library. `app/` is
the only thing that knows about HTTP. That is why `evaluate_dataset.py` can score the *exact*
code path the API runs — the accuracy numbers are not from a separate offline script that might
have drifted.

**Reviewer decisions are an overlay, never a mutation.** Confirmations and rejections are stored
append-only and applied when a result is read. Re-running an analysis therefore cannot lose
corrections, and every decision stays auditable — which matters when the output feeds a bid.

**The engine is deterministic end to end.** No sampling, no model weights, no randomness. The
same drawing produces the same numbers every time. That is a requirement, not a nicety: a
takeoff that changes between runs cannot go into a commercial document.

---

# Architecture

## Backend — Python 3.12, FastAPI, PyMuPDF, NumPy, SQLite

`mepiq_core` is a pure library with **no web framework and no I/O assumptions**; only `app/`
knows about HTTP. That separation is why the evaluation script reuses the exact code path the
API uses.

| Module | Responsibility |
|---|---|
| `mepiq_core/pdfdoc.py` | Vector primitive extraction; the foreground / screened split |
| `mepiq_core/geometry.py` | Polygons, circles, hatch runs, parallel pairs, spatial indexes |
| `mepiq_core/shapes.py` | Legend-driven shape classification (Level 1) |
| `mepiq_core/matching.py` | Exact rigid-transform geometric hashing |
| `mepiq_core/symbols.py` | Catalogue, detection pipeline, glyph mining, learning library |
| `mepiq_core/linear.py` | Layer recovery, centrelines, run chaining, measurement (Level 2) |
| `mepiq_core/scale.py` | Five scale estimators with provenance |
| `mepiq_core/discipline.py` | Sheet triage — which trade, and is it a plan? |
| `mepiq_core/validate.py` | The twelve validation rules (Level 4) |
| `mepiq_core/clash.py` | Cross-discipline 2-D coordination screen (Level 4) |
| `mepiq_core/exporters.py` | COCO, CSV, BOQ, IFC4, BCF |
| `mepiq_core/pipeline.py` | Orchestration with progress reporting |
| `app/main.py` | FastAPI application and all endpoints |
| `app/store.py` | SQLite schema and file storage |
| `app/copilot.py` | Nine copilot tools, LLM loop, deterministic router |

**Three decisions worth noting.** Analysis runs as a background job and streams progress over
server-sent events, so the UI names the real work rather than showing a spinner. Reviewer
decisions are stored append-only and applied **on read** — the analysis file is never mutated, so
re-analysis does not lose corrections and every decision stays auditable. Rendered sheets are
cached on disk (0.39 s first request → 0.01 s thereafter).

## Frontend — React 18, Vite, Redux Toolkit (RTK Query)

| Store | Holds |
|---|---|
| RTK Query cache | Everything the server owns — projects, results, chat, library |
| `uiSlice` | Which project, document and page you are looking at |
| `viewerSlice` | Zoom and pan, active tool, layer toggles, selection, filters |

The viewer works in three coordinate spaces at once — PDF points (what the engine computes),
render pixels at 130 DPI (the sheet image), and screen pixels (after pan and zoom). The sheet is
an `<img>` and every overlay is **SVG in the drawing's own coordinate space**, both inside one
container carrying a single CSS transform. That is why overlays stay vector-sharp at any zoom and
land exactly on the strokes they describe.

The bundle is 314 kB (100 kB gzipped) with no UI framework.

## Repository map

```
backend/
  mepiq_core/          the engine — no web framework, no I/O assumptions
  app/                 FastAPI: uploads, jobs, results, review, exports, copilot
  tests/               39 tests, no dataset required
  evaluate_dataset.py  reproducible evaluation against the supplied annotations
frontend/
  src/pages/           one file per screen
  src/components/      SheetCanvas is the drawing viewer
  src/store/           RTK Query api + uiSlice + viewerSlice
  test/                layout invariants and page smoke tests
deploy/                Render, Railway, Fly.io, Vercel blueprints
docs/                  architecture, deployment, user manual, problem statement
evaluation/            RESULTS.md and measured output
docker-compose.yml     two-tier stack
Dockerfile             single-container build (API serves the UI)
run-lan.ps1 / .sh      serve on a local network for a demo
```

---

# Running it yourself

## Docker Compose

```bash
cp .env.example .env        # optional: add OPENAI_API_KEY for the LLM copilot
docker compose up --build
```

App on <http://localhost:8080>, API docs on <http://localhost:8000/docs>.

## Single container — one image, one port

```bash
docker build -t mepiq .
docker run -p 8000:8000 -v mepiq-data:/data mepiq
```

Serves both API and UI from <http://localhost:8000>. This is what the live deployment runs.

## Local development

```powershell
.\run-local.ps1        # Windows — installs deps, starts both, opens the browser
```

```bash
./run-local.sh         # macOS / Linux
```

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `MEPIQ_DATA_DIR` | `./data` | Uploads, results, SQLite, library. The only state. |
| `MEPIQ_WORKERS` | `2` | Concurrent analyses. Bounded by RAM, not CPU. |
| `MEPIQ_MAX_SHEETS` | `40` | Ceiling on sheets analysed per run. |
| `MEPIQ_MAX_UPLOAD_MB` | `200` | Per-file upload cap. |
| `MEPIQ_BIND` | `0.0.0.0` | Set to `127.0.0.1` to keep it to one machine. |
| `OPENAI_API_KEY` | unset | Optional — without it the copilot uses its deterministic engine. |

**Sizing.** The engine is CPU-bound and holds one sheet at a time in memory. A `t3.micro` (1 GB)
is too small — the Docker build alone will likely run out of memory. Use `t3.small` (2 GB)
minimum, `t3.medium` (4 GB) comfortably. ~20 GB of disk is plenty.

## Testing and CI

```bash
cd backend  && pytest -q                    # 39 tests
cd frontend && node test/check-layout.mjs   # 7 layout invariants
cd frontend && npm run build                # production bundle
```

`.github/workflows/ci.yml` runs all of the above, builds the Docker image, and smoke-tests the
running container on every push.

---

# What we would build next

1. **Flexible duct recall** — the weakest detector (0.84 precision / 0.26 recall). Curved flex
   duct changes its hash-mark length as it bends, breaking run chaining. Fixing it would lift
   the Level 1 aggregate noticeably, since flex duct is the only annotated class on roughly a
   third of the sheets.
2. **Multi-sheet system tracing** — follow match-line callouts so a duct main becomes one object
   across a whole floor.
3. **True 3-D clash detection** — parse elevation annotations ("BOD +10'-6\"") to turn the 2-D
   screen into real clearance checking.
4. **Multi-modal reasoning** — bring the specification and equipment schedules into the copilot
   so it can answer "does this diffuser meet the airflow in the schedule?"
5. **Production hardening** — authentication, an out-of-process job queue, object storage, and a
   Playwright suite.
