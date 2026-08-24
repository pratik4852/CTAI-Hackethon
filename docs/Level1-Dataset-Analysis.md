# Level 1 — Dataset Analysis

Analysis of the `CTD Dataset` as it pertains to **Level 1: Quantifiable Object
Detection & Counting**. Exact per-class totals for the mechanical set are
produced by `scripts/run_1_analyze.bat`; the structure, formats, class
taxonomy, and the electrical counts below were established directly from the
files.

## 1. Dataset structure

```
CTD Dataset/
├── training/
│   ├── mechanical/                 29 sheets, one folder each
│   │   ├── Symbols_for_detection.pdf     <- canonical 8-symbol legend
│   │   ├── Example File for object detection.png
│   │   └── <sheet folder>/
│   │       ├── <sheet>.pdf                    input drawing (1 page)
│   │       ├── N) <sheet>.json                OBJECT ground truth (COCO)  ← Level 1
│   │       ├── <sheet>_detected_hvac.json     duct polylines (COCO)       ← Level 2
│   │       └── <sheet>_detected_hvac.pdf      visual overlay
│   └── electrical/
│       ├── 701_dexter/  (instances_all.json + dataset_summary.csv + PDF)
│       └── electrical_2/(instances_all.json + dataset_summary.csv + PDF)
└── testing/
    ├── mechanical/  mechanical.pdf, METRO_P1_MECH_BL5.1.pdf
    ├── electrical/  Sheets_selected_Electrical_...pdf
    └── plumbing/    plumbing.pdf        (pipes → Level 2, not Level 1)
```

Key facts:

- **Annotations are COCO JSON**, aligned to page images rendered at **150 DPI**.
  Images are *not* shipped — you render the PDF pages yourself (the pipeline
  does this).
- **Category IDs are local to each file.** The same symbol has different IDs in
  different files, so classes must be merged **by name** (the code does this).
- **Two annotation types** live in the mechanical folders: the `N) <sheet>.json`
  files hold the countable **object** symbols (Level 1); the
  `*_detected_hvac.json` files hold **duct-segment polylines** (Level 2 linear
  measurement) and are excluded from Level 1.
- **Plumbing has no training annotations** — it appears only in `testing/`, so
  it belongs to Level 2 (pipe measurement), not Level 1 counting.
- Sheets are large: mechanical ≈ **6300×4500 px**, electrical ≈ **5925×5100 px**
  at 150 DPI. Symbols are small relative to the sheet → **tiling is essential**.

## 2. Classes (Level 1)

### Mechanical — 8 symbol classes (from `Symbols_for_detection.pdf`)

| Symbol | Category | Trade |
|---|---|---|
| Square Supply Diffuser (4-Way) | Air Terminals | HVAC |
| Round Supply Diffuser | Air Terminals | HVAC |
| Linear Bar Grille / Linear Slot Diffuser | Air Terminals | HVAC |
| Square Return / Exhaust Register | Air Terminals | HVAC |
| Flexible Duct (Flex Duct) | Ductwork | HVAC |
| Fire Damper (FD) | In-Line Duct Accessories | HVAC |
| Water Source Heat Pump (WSHP) / Vertical Heat Pump (VHP) | Major Equipment | HVAC |
| Elevation Benchmark (Datum Target) | Annotations & Callouts | Architecture |

Per-class instance counts across the 29 mechanical sheets (from
`outputs/analysis/class_counts.csv`):

| Class | Instances |
|---|---:|
| Fire Damper (FD) | 842 |
| Linear Bar Grille / Linear Slot Diffuser | 347 |
| Square Return / Exhaust Register | 255 |
| Flexible Duct (Flex Duct) | 165 |
| Square Supply Diffuser (4-Way) | 64 |
| Water Source Heat Pump (WSHP) / Vertical Heat Pump (VHP) | 40 |
| Elevation Benchmark (Datum Target) | 34 |
| Round Supply Diffuser | 9 |
| **TOTAL** | **1756** |

### Electrical — 14 symbol classes (union of the two datasets)

Counts are known from the two `dataset_summary.csv` files:

| Class | 701_dexter | electrical_2 | Total |
|---|---:|---:|---:|
| Auto Switch | 7 | – | 7 |
| Disconnect Switch | 2 | – | 2 |
| Double Duplex Receptacle | 22 | 87 | 109 |
| Duplex Receptacle | 18 | 377 | 395 |
| Electrical Wall Heater | 2 | – | 2 |
| Fan Connection | 17 | – | 17 |
| Junction Box | 6 | – | 6 |
| Motor Connection | 43 | – | 43 |
| Single Receptacle | 2 | – | 2 |
| Fire Alarm | – | 180 | 180 |
| Floor Box | – | 126 | 126 |
| Manual Fire Alarm | – | 434 | 434 |
| Panel Board | – | 61 | 61 |
| Surface Mounted A | – | 6 | 6 |
| **TOTAL** | **119** | **1271** | **1390** |

**Combined Level-1 label space = 8 mechanical + 14 electrical = 22 classes.**

## 3. Observations that shaped the pipeline

- **Totals: 74 sheets, 3,146 annotations** (mechanical 1,756 across 29 sheets;
  electrical 1,390 across 45 pages in 2 multi-page files).
- **Class imbalance is severe.** Mechanical ranges from Fire Damper (842) down to
  Round Supply Diffuser (9); electrical from Manual Fire Alarm (434) down to
  Single Receptacle / Disconnect Switch / Electrical Wall Heater (2 each). Expect
  weak recall on the rare classes — mitigations: keep some background tiles for
  precision, oversample rare-class tiles, and always report per-class metrics.
- **Symbols are small.** Box areas span min 21 px² (~5 px), median ~1,147 px²
  (~34 px), max ~18,884 px² (~137 px) at 150 DPI. The smallest symbols are near
  the limit of detectability → train and infer on **1280 px tiles with 20%
  overlap**, then stitch detections back and de-duplicate seam overlaps with
  class-aware NMS. If rare/tiny classes underperform, try 200 DPI renders.
- **Discipline separation is clean** (a sheet is either mechanical or
  electrical). A single 22-class "combined" model is simplest to run; per-
  discipline models are also supported (`--mode mechanical|electrical`) and
  usually squeeze out a little more accuracy.
- **Counting is the graded metric.** Detection feeds counting, so the evaluator
  reports both mAP (on the val split) and **per-class count accuracy** vs the
  COCO ground truth.

## 4. What Level 1 produces

Per sheet: a JSON record (`objects[]` with class, bbox, confidence + `counts`),
a row-per-class `counts_summary.csv`, and an annotated preview PNG with a count
legend — the inputs Level 3 (copilot) and quantity-takeoff will consume.
