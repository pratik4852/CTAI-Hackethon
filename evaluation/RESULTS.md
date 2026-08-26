# Evaluation results

Everything below is reproducible:

```bash
cd backend
python evaluate_dataset.py --dataset "../CTD Dataset/CTD Dataset" --out ../evaluation
```

The script writes `evaluation.json` with per-sheet detail. It can be run in chunks with
`--only level1|level2`, `--offset` and `--limit` on machines where a single pass would be long.

Hardware for the figures below: 2 vCPU container, no GPU.

---

## Level 2 — linear object detection and measurement

This is the level with unambiguous ground truth. The `_detected_hvac.pdf` and
`_detected_pipelines.pdf` files contain the exact vector geometry that was marked as duct or
pipe, so we can compare segment for segment rather than by bounding box.

**What is measured:** the fraction of ground-truth segments that MEPIQ's layer recovery
selects as system linework.

### Mechanical — 28 sheets

| Sheets | Ground-truth segments | Recall |
|---|---:|---:|
| 27 of 28 | 353,111 | **100.0 %** |
| Moss Adams Spokane p50 | 8,835 | 99.3 % |
| **Total** | **361,946** | **~100.0 %** |

Selection precision ranges 0.52 – 0.97, mean **0.89**. Precision below 1.0 means MEPIQ selects
somewhat more geometry than the annotation marked — the excess is mostly equipment outlines and
tag leaders drawn at the same pen weight, and most of it is filtered out downstream by
minimum-run-length and by excluding detected component footprints.

### Plumbing and fire protection — 16 sheets

| Sheets | Ground-truth segments | Recall |
|---|---:|---:|
| 13 of 16 | 34,207 | **100.0 %** |
| P104.1 Level 4 Area 1 | 1,819 | 0.1 % |
| P104 Overall Level 4 | 167 | 0.0 % |
| P107 Overall Roof | 52 | 0.0 % |
| **Total** | **36,245** | **94.4 %** |

The three failures share a cause: the pen weight the annotator selected on those sheets is not
the dominant system weight, and on P104.1 the size tags sit on a *different* weight class than
the pipes they label. The two "Overall" sheets have 167 and 52 annotated segments respectively
— they are key plans where almost nothing was marked.

This is exactly why the layer choice is exposed in the UI: the Drawings panel lists every pen
weight with its stroke count and inked length, and switching class re-measures the sheet
immediately.

### Combined

| Metric | Result |
|---|---:|
| Geometry recall | **99.5 %** |
| Geometry precision | 86.5 % |
| Sheets at 100 % recall | 40 of 44 |
| Time per sheet | 0.3 – 3 s |

### Measurement correctness

Recovering the right geometry is necessary but not sufficient — the length has to be right too.
Two properties are asserted in the test suite rather than only measured:

- **Duct is not double-counted.** Two parallel walls 12 pt apart over 100 pt measure 100 pt of
  centreline, not 200 pt of linework, and the pairing yields the 12 pt duct width as a bonus
  (`test_duct_walls_collapse_to_one_centreline_with_a_width`,
  `test_measured_duct_is_not_double_counted`).
- **Runs chain across fittings.** Three segments forming an elbow become one run, not three
  (`test_runs_chain_across_an_elbow`), while genuinely separate runs stay separate.

End-to-end, on a synthetic sheet with two 750 pt ducts at 1/4" = 1'-0", the API returns
83.3 ft — the correct centreline quantity (`test_analysis_finds_ducts_and_dampers`).

---

## Level 1 — quantifiable object detection and counting

29 mechanical sheets with component annotations. Detection is scored at IoU 0.3; **count
accuracy** is `1 − Σ|predicted − actual| / Σ actual`, which is what a takeoff actually depends
on.

### Overall

| Metric | Result |
|---|---:|
| Precision @ IoU 0.3 | 0.45 |
| Recall @ IoU 0.3 | 0.47 |
| F1 | 0.46 |
| Localisation recall (class-agnostic) | 0.50 |
| Count accuracy | 0.40 |
| Mean time per sheet | 4.2 s |

### Where it works well

On sheets whose components are in the supplied catalogue and drawn at plan scale, the engine
is strong:

| Sheet | Predicted | Actual | P | R | F1 | Count acc. |
|---|---:|---:|---:|---:|---:|---:|
| BSWH-THH TFO p3 | 113 | 130 | 0.82 | 0.72 | **0.77** | **0.73** |
| BSWH-THH TFO p8 | 42 | 45 | 0.79 | 0.73 | **0.76** | 0.62 |
| BSWH-THH TFO p13 | 92 | 100 | 0.73 | 0.67 | **0.70** | 0.64 |
| PfMCC 50 % CD p118 | 243 | 168 | 0.58 | 0.83 | **0.68** | 0.27 |
| BSWH-THH TFO p6 | 158 | 209 | 0.69 | 0.52 | 0.59 | 0.50 |
| BSWH-THH TFO p12 | 91 | 134 | 0.71 | 0.49 | 0.58 | 0.44 |

On PfMCC p118 the engine finds **144 of 168 fire dampers (86 % of the count)** at 0.86
class-agnostic localisation recall.

### Where it does not, and why

| Failure mode | Sheets | Cause |
|---|---|---|
| Flexible-duct-only sheets | Avexis p21–24, Phase 1/2 Combine | The hash-mark detector is tuned for precision (0.84) over recall (0.26); curved flexible duct varies its hash length as it bends, and hash marks whose length drifts break the run |
| Sparse annotations | M-3.1 Ductwork p1 (3 annotations), Phase 1 p397–400 | MEPIQ finds many real components the annotation does not label, which scores as false positives — its 3 labelled datum targets were found at 100 % localisation recall |
| One project's diffuser convention | 3T MRI p30 | 4-way diffusers there are drawn with the neck circle detached from the square, so the square-family rule reads them as fire dampers |

### Caveats we are not hiding

The Level 1 annotations are **not hand-drawn ground truth**. Every record carries a `score`
field (values as low as 0.61) and an `orig_detection_id` — they are another detector's output.
Concretely, within a single sheet:

- boxes for one component type vary from 26.5 × 18.8 px to 53.0 × 37.5 px, a 2× spread;
- several sheets label only one class while the drawing plainly contains several others;
- one ductwork construction plan carries 3 annotations for a sheet with hundreds of components.

Both directions of error follow: IoU-based precision is penalised for finding real components
that were never labelled, and recall is penalised for missing instances whose reference boxes
disagree with the drawn extents. **Count accuracy on catalogue-dense sheets (0.62 – 0.73) is
the number we would stand behind**, and the product's answer to the residual gap is not a
better threshold — it is the review loop: confirm, reject or name in one click, and the library
carries the correction forward.

---

## Speed

| Operation | Time |
|---|---|
| Parse a 100,000-primitive sheet | 1.3 s |
| Detect components on a dense mechanical sheet | 2 – 5 s |
| Trace and measure ductwork | 0.3 – 3 s |
| Find-similar visual search (116 matches) | **0.07 s** |
| Triage a 25-page bid set | 1.5 s |
| Full analysis, 4 sheets | 20 – 45 s |

No GPU, no model download, no training step. The whole engine is deterministic: the same PDF
produces the same numbers every time, which matters when the output is going into a bid.

---

## Test suite

39 tests, no dataset required — synthetic drawings are generated with PyMuPDF so CI is fast and
each test documents the behaviour it protects.

```bash
cd backend && pytest -q
```

Coverage includes: the screened/foreground split, scale arithmetic and two-point calibration,
each catalogue symbol's classification rule, rotation invariance, exact template propagation,
duct centrelining and non-double-counting, run chaining, tag parsing, and the full API surface
from upload through analysis, review, exports and copilot.
