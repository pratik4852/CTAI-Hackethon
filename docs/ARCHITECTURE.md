# Architecture

## The premise

A construction PDF issued from Revit, AutoCAD or Navisworks is a vector document. Every duct
wall, diffuser and pipe is in the file as a path, with its stroke colour and pen weight intact.
Rasterising it and running a detector throws away the exact information and replaces it with a
guess.

MEPIQ reads the geometry. Everything else follows from that.

```
PDF ─► primitives ─► foreground split ─► shape assembly ─┬─► symbols   (Level 1)
                                                          ├─► runs      (Level 2)
                                                          ├─► rules     (Level 4)
                                                          └─► clash     (Level 4)
                                                                  │
                                          scale detection ─────────┤
                                                                  ▼
                                            results ─► API ─► UI ─► copilot (Level 3)
                                                          └─► COCO / CSV / BOQ / IFC / BCF
```

---

## 1. Primitive extraction — `pdfdoc.py`

PyMuPDF gives one dict per drawn path; each is flattened into straight `Primitive` segments
carrying colour, pen width, dash state and fill. Bezier curves become their control chords,
which is enough for length and topology and far cheaper than tessellating on a sheet with
100,000 primitives.

Two derived properties do most of the work downstream:

```python
is_foreground = luminance <= 0.35 or saturation >= 0.12
```

**Why:** CAD publishers screen the reference background — the architectural underlay, grid and
room outlines — to a light grey, and keep the discipline's own systems at full intensity. So
luminance separates "the sheet I am responsible for" from "context" without any content
heuristic. Measured on the supplied data, this holds on every publisher in the set.

`quick_sheet()` provides a text-only view with drawing density estimated from the content-stream
size. Triaging a 400-page bid set by fully parsing every page would take minutes; triaging on
text and density takes about a second.

---

## 2. Scale — `scale.py`

Get the scale wrong and every length is wrong, so five independent estimators run and each
returns a candidate with its own confidence and a human-readable justification:

| Estimator | Signal | Typical confidence |
|---|---|---|
| `title_block` | `1/8" = 1'-0"` or `1:100` printed on the sheet | 0.86 – 0.98 |
| `dimension_string` | `7'-8 1/2"` sitting on a dimension line of known drawn length | 0.55 – 0.92 |
| `duct_tag` | a duct tagged `42/20` must be 42 inches across | 0.45 – 0.90 |
| `known_component` | square ceiling diffusers are a 24" ceiling module | 0.35 – 0.80 |
| `sheet_size` | last-resort prior from the paper size | 0.20 |

Agreement between two independent estimators raises confidence by 0.10 — a genuinely stronger
signal than either alone. Candidates ranked below the winner are kept and shown in the UI, so a
reviewer can see the alternatives rather than a single opaque answer.

Every ratio is snapped to a real drafting scale. Metric ratios sit *between* the imperial ones,
so metric is only considered when the sheet reads metric — otherwise a noisy imperial estimate
lands on "1:75" and quietly rescales the whole takeoff.

**Reviewer override:** click two points on the drawing, type the real distance, and every length
on the sheet is rescaled. That is one API call and it is the honest answer to a low-confidence
sheet.

---

## 3. Level 1 — detection and counting

### 3a. Legend-driven shape classification — `shapes.py`

The dataset ships a symbol catalogue that defines each component *in words*: "a square with an
'X' and a central circle", "a square with a single diagonal", "concentric circles". So instead
of learning what those look like from pixels, MEPIQ **draws them from the definition** and
compares.

1. Cluster short foreground segments that touch into blobs. Only short segments participate —
   run linework is long, symbol strokes are not — which is what stops symbols fusing into the
   duct network they sit on.
2. Merge blobs whose bounding boxes overlap. A fire damper is a square, two diagonals and a
   heavy barrier line, and depending on how the exporter ordered the content stream those can
   land in separate blobs that *overlap* rather than touch.
3. Absorb any primitive wholly contained in the candidate's bounds. An 18 pt square's own
   diagonal is 25 pt, so the short-segment cut-off would otherwise discard the very 'X' that
   distinguishes a fire damper from a plain register. A duct passing through extends beyond the
   box, so it is not absorbed.
4. Normalise the candidate to a 40 × 40 binary raster and score it against the procedurally
   generated ideal symbols over four rotations and their mirrors.

The score is the harmonic mean of two quantities that both matter — **coverage** (how much of
the symbol is present) and **cleanliness** (how much of the candidate is explained by the
symbol). Coverage alone misses a symbol with a stroke absent; cleanliness alone accepts a blob
that contains the symbol plus a lot else.

**Structural tie-breaks.** The three square-faced symbols differ by one feature, and a global
raster score cannot separate them — the deciding evidence is a handful of pixels. So they are
resolved structurally instead: count corner-to-corner diagonals, and test whether the short
strokes near the middle lie on a *ring* (a real neck circle) rather than merely being near the
centre.

Scoring is vectorised: all rotations and mirrors of the catalogue are pre-computed and
pre-dilated once, so classifying a candidate is three array reductions rather than sixty
Python-level operations. That is the difference between a sheet taking 35 s and taking 3.6 s.

### 3b. Exact template propagation — `matching.py`

Classification only sees a symbol when clustering managed to isolate it. Wherever a diffuser is
fused to the flexible duct feeding it, the blob is too big to recognise — and on a busy sheet
those are the majority.

So each confidently classified instance is lifted as a **template** and the whole sheet is
searched for rigid copies of it. Because CAD symbols are stamped from blocks, every instance is
the same geometry under a rigid transform, and the search is an *exact* match rather than a
similarity score:

- index every segment by its quantised direction vector and pen weight;
- anchor on the template's three rarest, longest segments (one anchor is fragile — if that
  stroke is drawn slightly differently on some instances, all of them are missed);
- for each candidate placement, verify every template segment exists within 0.18 pt;
- accept at ≥ 90 % of segments matched, then collapse duplicate hits from rotational symmetry.

This is what makes the counts trustworthy: a match either is the symbol or it is not.

### 3c. Glyph mining and the library — `symbols.py`

Independently, MEPIQ mines geometry that repeats verbatim across the sheet by hashing
rotation-canonical signatures. That finds *every* repeated component, including ones nobody has
ever labelled, with exact counts.

Unnamed repeated glyphs surface in the review queue. Naming one writes it to the symbol library,
and because the match is on exact geometry it then applies to that sheet, the rest of the set,
and every drawing analysed afterwards. **This is the feedback-learning loop**, and it is the
answer to the fact that no fixed catalogue covers every firm's drawing conventions.

The same machinery powers **find-similar visual search** in the UI: drag a box around a symbol
and get every copy, in under a tenth of a second on a dense sheet. `clean_selection` reduces the
box to its largest connected component first — a box drawn over a diffuser also catches the duct
stub and part of the tag, and those differ at every other instance, so an uncleaned template
matches exactly once: the one it came from.

---

## 4. Level 2 — linear measurement — `linear.py`

### Layer recovery

Within the foreground, line weight behaves like a layer table. Classes are ranked by

```
score = inked_length × sqrt(weight / max_weight) × (1 + 2.5 × tag_affinity)
```

The first two terms balance "MEP systems are plotted heavier" against "a class only matters if
there is a lot of it". **Tag affinity** is the drawing telling us the answer directly: engineers
tag runs by writing the size beside the line, so whichever stroke class those tags sit on is the
one carrying the system. That settles cases line weight alone cannot — on many plumbing sheets
the pipes are dashed, so the system class has *more, shorter* strokes than the architectural
linework and a length-only score picks the wrong one.

Validated against the annotated PDFs, this recovers **99.5 %** of ground-truth duct and pipe
geometry. The full class list is exposed in the UI so a reviewer can override the choice and see
the sheet re-measure immediately.

### Duct centrelines

Rectangular duct is drawn as two parallel lines. Pairing them — same pen weight, parallel within
0.035 rad, overlapping by at least half their length, 1–90 pt apart — and walking the centreline
turns 2 × L of linework into 1 × L of duct **with a known width**.

That is both the correct quantity and a free size takeoff. Measuring the linework instead
double-counts every rectangular duct, which is the classic error when taking ductwork off a PDF
by hand or by pixel.

### Run chaining and attribution

Centrelines and single-line branches are snapped into an endpoint graph and walked outward while
the path is unambiguous, so an elbow becomes one run rather than two. Size and service come from
the annotations printed beside the run — `42/20 SA`, `(N)2"LW` — parsed into structured
dimensions, service names and new/existing status. Where there is no tag, the drawn duct width
is converted through the sheet scale and reported as measured, flagged with `~`.

Connectivity is built from shared endpoints, giving networks, node degrees, and the isolated runs
that feed rule MEP-001.

---

## 5. Level 4 — validation, clash, export

**`validate.py`** — twelve rules, each returning findings with a severity, an explanation in
engineering language, the evidence that triggered it, and a location the UI can fly to.
Unconnected runs, air terminals with no ductwork within reach, untagged runs, dampers not on a
duct, undersized branches, terminal density, unconfirmed scale, unidentified repeated symbols.

**`clash.py`** — same-level sheets from different trades are overlaid on their shared drawing
frame, and segment-to-segment distances are compared against per-trade-pair clearances. Sheets at
different scales or frames are skipped rather than guessed at. This is a screening pass: plan
geometry cannot know elevations, and the app says so rather than implying certainty.

**`exporters.py`** — COCO at the dataset's own 150 DPI so results drop into an existing
evaluation harness; CSVs for estimating; a rolled-up bill of quantities; a valid IFC4 SPF file
placing components and runs in plan (elevations unknown, so everything sits at the storey datum
and is flagged 2-D-derived); BCF-shaped issue topics for coordination tools.

---

## 6. Level 3 — the copilot — `app/copilot.py`

Nine tools read the analysis result: overview, counts, linear quantities, longest runs, findings,
clashes, sheet detail, bill of quantities, detection explanations.

**It never invents a number.** Every quantity comes from a tool call, and each answer carries the
citations — sheet, run id, rule id — that produced it. The LLM chooses tools, reads what comes
back and explains it; it does not recall figures.

**It works without an LLM.** The same tools are wired to a deterministic intent router, so the
assistant answers "how much 12-inch supply duct is on M-3.1?" with no API key configured. Where
`OPENAI_API_KEY` is set, the model handles the open-ended reasoning — *why* something was
flagged, what to check next — that rules cannot. If the model call fails mid-demo, the answer
falls back to the deterministic path and says so.

---

## 7. API and UI

**FastAPI** with an in-process thread pool. Analysis runs as a background job; progress streams
over server-sent events so the UI shows the actual work ("tracing ductwork on M-3.1") rather than
a spinner. Metadata lives in SQLite; analysis payloads are JSON on disk, because they are large
and always read whole.

Reviewer decisions are stored as an append-only `reviews` table and **overlaid on read**. The
analysis is never mutated, so a re-analysis does not lose corrections and every decision remains
auditable.

**React 18 + Vite + Redux Toolkit**, with RTK Query for the data layer and two slices for UI and
viewer state. The drawing viewer renders the sheet as a raster and everything the analysis found
as SVG in the drawing's own coordinate space — so overlays stay crisp at any zoom, and every box
on screen is the actual geometry the engine measured rather than an approximation of it.
