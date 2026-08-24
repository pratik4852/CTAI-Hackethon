"""
Evaluate Level-1 results two ways:

1. Detection quality (mAP / precision / recall) on the tiled val split, via
   Ultralytics' built-in validator:
     python -m src.eval.evaluate map --weights <best.pt> --data data/yolo/dataset.yaml

2. Count accuracy on annotated sheets (the metric the hackathon rewards). We
   render each training sheet, run the detector, and compare predicted per-class
   counts to the COCO ground truth:
     python -m src.eval.evaluate counts --weights <best.pt> \
         --classes data/yolo/classes.json --dataset "E:/CTA Dataset/CTD Dataset"
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.common.coco_utils import (  # noqa: E402
    build_global_class_map, find_object_detection_cocos, iter_annotations,
    resolve_source_pdf,
)
from src.common.pdf_render import render_page  # noqa: E402
from src.infer.predict_sheet import (  # noqa: E402
    counts_from_labels, load_class_names, predict_on_sheet,
)


def eval_map(weights: str, data: str, imgsz: int = 1280) -> None:
    from ultralytics import YOLO
    model = YOLO(weights)
    metrics = model.val(data=str(Path(data).resolve()), imgsz=imgsz, verbose=True)
    try:
        print(f"[eval] mAP50-95: {metrics.box.map:.4f}  mAP50: {metrics.box.map50:.4f}")
    except Exception:  # noqa: BLE001
        pass


def eval_counts(weights: str, classes_json: str, dataset_root: str,
                mode: str = "combined", tile_size: int = 1280,
                overlap: float = 0.2, dpi: int = 150, conf: float = 0.25,
                out_csv: str = "outputs/eval/count_accuracy.csv") -> None:
    from ultralytics import YOLO

    names = load_class_names(Path(classes_json))
    model = YOLO(weights)
    disciplines = None if mode == "combined" else {mode}
    cocos = find_object_detection_cocos(Path(dataset_root), "training")
    if disciplines:
        cocos = [c for c in cocos if c.discipline in disciplines]

    rows = []
    tot_abs_err = Counter()
    tot_gt = Counter()

    for cf in cocos:
        # GT counts per image per class.
        gt = defaultdict(Counter)
        for img, ann, name in iter_annotations(cf):
            gt[img["id"]][name] += 1

        for image_id, img in cf.images.items():
            pdf_path, page = resolve_source_pdf(cf, img)
            if pdf_path is None:
                continue
            iw, ih = int(img.get("width", 0)), int(img.get("height", 0))
            try:
                raster = render_page(pdf_path, page, dpi=dpi,
                                     target_size=(iw, ih) if iw and ih else None)
            except Exception as exc:  # noqa: BLE001
                print(f"[eval] render failed {pdf_path} p{page}: {exc}")
                continue
            _, _, labels = predict_on_sheet(model, raster, tile_size, overlap, conf)
            pred = counts_from_labels(labels, names)

            classes = set(gt[image_id]) | set(pred)
            for cls in classes:
                g, p = gt[image_id].get(cls, 0), pred.get(cls, 0)
                rows.append((cf.discipline, cf.path.name, image_id, cls, g, p, abs(g - p)))
                tot_abs_err[cls] += abs(g - p)
                tot_gt[cls] += g

    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["discipline", "coco_file", "image_id", "class", "gt", "pred", "abs_err"])
        w.writerows(rows)

    print("\n[eval] Per-class count accuracy (1 - sum|pred-gt| / sum gt):")
    grand_err = grand_gt = 0
    for cls in sorted(tot_gt):
        g = tot_gt[cls]
        e = tot_abs_err[cls]
        acc = (1 - e / g) if g else float("nan")
        grand_err += e
        grand_gt += g
        print(f"  {cls:45s} gt={g:5d}  abs_err={e:5d}  acc={acc:6.2%}")
    if grand_gt:
        print(f"  {'OVERALL':45s} gt={grand_gt:5d}  abs_err={grand_err:5d}  "
              f"acc={1 - grand_err / grand_gt:6.2%}")
    print(f"[eval] wrote {out_csv}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate Level-1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="detection mAP on val split")
    m.add_argument("--weights", required=True)
    m.add_argument("--data", required=True)
    m.add_argument("--imgsz", type=int, default=1280)

    c = sub.add_parser("counts", help="count accuracy vs COCO ground truth")
    c.add_argument("--weights", required=True)
    c.add_argument("--classes", required=True)
    c.add_argument("--dataset", required=True)
    c.add_argument("--mode", default="combined",
                   choices=["combined", "mechanical", "electrical"])
    c.add_argument("--tile", type=int, default=1280)
    c.add_argument("--overlap", type=float, default=0.2)
    c.add_argument("--dpi", type=int, default=150)
    c.add_argument("--conf", type=float, default=0.25)
    c.add_argument("--out", default="outputs/eval/count_accuracy.csv")

    args = ap.parse_args()
    if args.cmd == "map":
        eval_map(args.weights, args.data, args.imgsz)
    else:
        eval_counts(args.weights, args.classes, args.dataset, args.mode,
                    args.tile, args.overlap, args.dpi, args.conf, args.out)


if __name__ == "__main__":
    main()
