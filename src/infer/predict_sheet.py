"""
Run Level-1 inference on a drawing: detect symbols, count them, and export
structured results + an annotated preview.

Pipeline:  render page (150 DPI) -> tile -> YOLO predict per tile ->
map boxes to sheet coords -> class-aware NMS across tile seams -> count ->
write JSON + CSV + annotated PNG.

Run:
  python -m src.infer.predict_sheet \
      --weights outputs/runs/mep/weights/best.pt \
      --classes data/yolo/classes.json \
      --pdf "E:/CTA Dataset/CTD Dataset/testing/mechanical/mechanical.pdf" \
      --out outputs/detections --conf 0.25
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.common.coco_utils import load_json  # noqa: E402
from src.common.pdf_render import page_count, render_page  # noqa: E402
from src.common.tiling import class_aware_nms, tile_grid  # noqa: E402
from src.common.viz import draw_detections  # noqa: E402


def load_class_names(classes_json: Path) -> List[str]:
    payload = load_json(Path(classes_json))
    if "names" in payload:
        return payload["names"]
    name_to_id = payload["name_to_id"]
    inv = {v: k for k, v in name_to_id.items()}
    return [inv[i] for i in range(len(inv))]


def predict_on_sheet(model, raster: np.ndarray, tile_size: int = 1280,
                     overlap: float = 0.2, conf: float = 0.25,
                     nms_iou: float = 0.5, batch: int = 16
                     ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (boxes_xyxy, scores, labels) in absolute sheet coordinates."""
    H, W = raster.shape[:2]
    tiles = tile_grid(W, H, tile_size, overlap)

    all_boxes: List[List[float]] = []
    all_scores: List[float] = []
    all_labels: List[int] = []

    for start in range(0, len(tiles), batch):
        chunk = tiles[start:start + batch]
        crops = [np.ascontiguousarray(raster[y0:y1, x0:x1][..., ::-1])  # RGB->BGR
                 for (x0, y0, x1, y1) in chunk]
        results = model.predict(crops, imgsz=tile_size, conf=conf, verbose=False)
        for (x0, y0, x1, y1), res in zip(chunk, results):
            if res.boxes is None or len(res.boxes) == 0:
                continue
            xyxy = res.boxes.xyxy.cpu().numpy()
            scores = res.boxes.conf.cpu().numpy()
            labels = res.boxes.cls.cpu().numpy().astype(int)
            for (bx1, by1, bx2, by2), s, l in zip(xyxy, scores, labels):
                all_boxes.append([bx1 + x0, by1 + y0, bx2 + x0, by2 + y0])
                all_scores.append(float(s))
                all_labels.append(int(l))

    if not all_boxes:
        return np.zeros((0, 4)), np.zeros((0,)), np.zeros((0,), dtype=int)

    boxes = np.asarray(all_boxes, dtype=float)
    scores = np.asarray(all_scores, dtype=float)
    labels = np.asarray(all_labels, dtype=int)
    keep = class_aware_nms(boxes, scores, labels, nms_iou)
    return boxes[keep], scores[keep], labels[keep]


def counts_from_labels(labels: np.ndarray, names: List[str]) -> dict:
    out = {n: 0 for n in names}
    for l in labels:
        if 0 <= int(l) < len(names):
            out[names[int(l)]] += 1
    return {k: v for k, v in out.items() if v > 0}


def build_sheet_record(sheet_id: str, source: str, page: int, W: int, H: int,
                       dpi: int, boxes, scores, labels, names) -> dict:
    objects = []
    for i, (b, s, l) in enumerate(zip(boxes, scores, labels)):
        objects.append({
            "id": f"obj_{i:05d}",
            "type": names[int(l)] if 0 <= int(l) < len(names) else str(int(l)),
            "geometry": {"kind": "bbox",
                         "coords": [round(float(v), 2) for v in b]},
            "confidence": round(float(s), 4),
        })
    return {
        "sheet_id": sheet_id,
        "source": source,
        "page": page,
        "width": W,
        "height": H,
        "dpi": dpi,
        "scale": None,  # not required for Level 1 counting
        "counts": counts_from_labels(labels, names),
        "objects": objects,
    }


def process_pdf(weights: str, classes_json: str, pdf_path: str, out_dir: str,
                tile_size: int = 1280, overlap: float = 0.2, dpi: int = 150,
                conf: float = 0.25, nms_iou: float = 0.5,
                pages: List[int] = None, save_preview: bool = True) -> None:
    from ultralytics import YOLO

    names = load_class_names(Path(classes_json))
    model = YOLO(weights)
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_pages = page_count(pdf_path)
    page_list = pages if pages else list(range(1, n_pages + 1))

    summary_rows = []
    for page in page_list:
        raster = render_page(pdf_path, page, dpi=dpi)
        H, W = raster.shape[:2]
        boxes, scores, labels = predict_on_sheet(
            model, raster, tile_size, overlap, conf, nms_iou)
        counts = counts_from_labels(labels, names)
        sheet_id = f"{pdf_path.stem}_p{page}"

        record = build_sheet_record(sheet_id, pdf_path.name, page, W, H, dpi,
                                    boxes, scores, labels, names)
        with open(out_dir / f"{sheet_id}.json", "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, ensure_ascii=False)

        for cls, n in counts.items():
            summary_rows.append((sheet_id, cls, n))

        if save_preview:
            preview = draw_detections(
                raster, boxes, labels, names, scores=scores, counts=counts)
            from PIL import Image
            Image.fromarray(preview).save(out_dir / f"{sheet_id}_annotated.png")

        print(f"[infer] {sheet_id}: {int(labels.shape[0])} objects  {counts}")

    with open(out_dir / "counts_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_id", "class", "count"])
        w.writerows(summary_rows)
    print(f"[infer] wrote results to {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Level-1 inference + counting")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--classes", required=True, help="classes.json from data prep")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="outputs/detections")
    ap.add_argument("--tile", type=int, default=1280)
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--nms-iou", type=float, default=0.5)
    ap.add_argument("--pages", type=int, nargs="*", default=None,
                    help="1-indexed pages to run (default: all)")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()
    process_pdf(args.weights, args.classes, args.pdf, args.out, args.tile,
                args.overlap, args.dpi, args.conf, args.nms_iou, args.pages,
                save_preview=not args.no_preview)


if __name__ == "__main__":
    main()
