# CTD 2026 — MEP AI · Level 1 (Detection & Counting)

Detect, classify, and **count** MEP symbols in Mechanical and Electrical 2D
drawings, and export structured results for downstream review / quantity
takeoff. Built with Python + YOLOv8 + PyMuPDF.

> Level 2 (linear measurement of ducts/pipes), Level 3 (copilot) and Level 4
> build on the outputs produced here. See `docs/Level1-Dataset-Analysis.md` for
> the dataset breakdown.

## Pipeline

```
PDF drawing ──render 150 DPI──▶ big raster ──tile 1280/20%──▶ tiles
   │                                                            │
   │ (training) COCO ground truth ─merge classes by name─┐      ▼
   ▼                                                     │   YOLOv8
tiled YOLO dataset  ◀───────────────────────────────────┘   detect
   │                                                            │
   ▼                                              stitch + class-aware NMS
train  ──────────────▶ best.pt ──────────▶ counts + JSON/CSV + annotated preview
```

## Setup

```bat
cd "E:\CTA Dataset\CTD Hackathon"
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

If you have an NVIDIA GPU, install a CUDA build of PyTorch first (see
https://pytorch.org) — training on CPU is slow.

## Run (Windows: use the numbered scripts in `scripts\`)

1. **Analyze the dataset** — class maps, counts, size distributions, plots.

   ```bat
   scripts\run_1_analyze.bat
   ```
   → `outputs\analysis\` (`dataset_report.md`, `class_counts.csv`,
   `classes_combined.json`, plots).

2. **Prepare training data** — render, tile, write YOLO labels + `dataset.yaml`.

   ```bat
   scripts\run_2_prepare.bat
   ```
   → `data\yolo\` (images/labels train+val, `dataset.yaml`, `classes.json`).

3. **Train** the detector.

   ```bat
   scripts\run_3_train.bat
   ```
   → `outputs\runs\mep_combined\weights\best.pt`.

4. **Infer + count** on the test drawings.

   ```bat
   scripts\run_4_infer.bat
   ```
   → `outputs\detections\` (per-sheet JSON, `counts_summary.csv`, annotated PNGs).

### Evaluate

```bat
REM Detection mAP on the held-out val tiles:
python -m src.eval.evaluate map --weights outputs\runs\mep_combined\weights\best.pt --data data\yolo\dataset.yaml

REM Count accuracy vs COCO ground truth (the graded metric):
python -m src.eval.evaluate counts --weights outputs\runs\mep_combined\weights\best.pt --classes data\yolo\classes.json --dataset "E:\CTA Dataset\CTD Dataset"
```

## Combined vs per-discipline model

Default is one **combined** 22-class model (mechanical + electrical). To train
discipline-specific models, pass `--mode mechanical` or `--mode electrical` to
`src.data_prep.coco_to_yolo` (writes a separate `data\yolo_<mode>\`) and point
training at that `dataset.yaml`.

## Project layout

```
CTD Hackathon/
├── README.md
├── requirements.txt
├── configs/level1.yaml            # default settings reference
├── docs/Level1-Dataset-Analysis.md
├── scripts/                       # run_1..run_4 .bat
└── src/
    ├── common/    coco_utils, pdf_render, tiling, viz
    ├── analysis/  analyze_dataset.py
    ├── data_prep/ coco_to_yolo.py
    ├── train/     train_yolo.py
    ├── infer/     predict_sheet.py
    └── eval/      evaluate.py
```

## Output schema (per sheet)

```json
{
  "sheet_id": "mechanical_p1",
  "source": "mechanical.pdf",
  "page": 1,
  "width": 6300, "height": 4500, "dpi": 150,
  "counts": { "Round Supply Diffuser": 12, "Fire Damper (FD)": 3 },
  "objects": [
    {"id": "obj_00000", "type": "Round Supply Diffuser",
     "geometry": {"kind": "bbox", "coords": [x1,y1,x2,y2]},
     "confidence": 0.94}
  ]
}
```

This is the contract Level 2/3/4 read from — keep it stable.

## Notes & knobs

- `--tile` must match training `--imgsz` (default 1280). Larger tiles = fewer,
  bigger symbols per tile but more GPU memory.
- Raise `--conf` to trim false positives, lower it to catch rare symbols.
- `--empty-frac` (data prep) controls how many background tiles are kept;
  raise it if the model over-predicts, lower it if it misses symbols.
