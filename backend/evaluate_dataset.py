#!/usr/bin/env python3
"""
Evaluate MEPIQ against the CTD dataset's published annotations.

Run:
    python evaluate_dataset.py --dataset "../CTD Dataset/CTD Dataset" --out ../evaluation

Two things are measured, because the dataset gives two kinds of truth:

**Level 1 — detection and counting.** ``instances_all.json`` / the per-sheet COCO
files carry boxes for quantifiable components. We report precision, recall and F1
at IoU 0.3, plus *count accuracy*, which is what a takeoff actually depends on.

A caveat we state rather than hide: those annotations carry ``score`` fields and
``orig_detection_id`` references, i.e. they are themselves the output of a
detector, not hand-drawn truth. Box extents for one component type vary by more
than 2x within a single sheet. Count accuracy is therefore the more meaningful
number, and IoU-based scores understate agreement.

**Level 2 — linear measurement.** The ``_detected_hvac`` / ``_detected_pipelines``
files contain the exact vector geometry that was marked as duct or pipe. That is
unambiguous truth, so we measure how much of it the engine's layer selection
recovers, segment for segment.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mepiq_core.geometry import bbox_iou  # noqa: E402
from mepiq_core.linear import select_system_linework  # noqa: E402
from mepiq_core.pdfdoc import DrawingDocument, bbox_px_to_pt  # noqa: E402
from mepiq_core.symbols import detect_symbols  # noqa: E402


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def load_component_gt(folder: str) -> list[tuple[str, list[float]]]:
    files = [f for f in glob.glob(os.path.join(folder, "*.json")) if "_detected" not in os.path.basename(f)]
    if not files:
        return []
    data = json.load(open(files[0], encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in data.get("categories", [])}
    return [(cats.get(a["category_id"], "?"), bbox_px_to_pt(a["bbox"])) for a in data.get("annotations", [])]


def _seg_key(x0: float, y0: float, x1: float, y1: float, q: float = 0.05):
    a = (round(x0 / q), round(y0 / q))
    b = (round(x1 / q), round(y1 / q))
    return (a, b) if a <= b else (b, a)


def load_linear_gt(folder: str, suffix: str) -> set | None:
    files = glob.glob(os.path.join(folder, f"*{suffix}.pdf"))
    if not files:
        return None
    with DrawingDocument(files[0]) as doc:
        sheet = doc.sheet(0)
        return {
            _seg_key(p.x0, p.y0, p.x1, p.y1)
            for p in sheet.primitives
            if max(p.color) - min(p.color) > 0.3      # the highlight colour
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def match(preds, gts, iou_thresh: float = 0.3, class_aware: bool = True):
    used: set[int] = set()
    tp = 0
    for cat, box, conf in sorted(preds, key=lambda p: -p[2]):
        best, best_i = -1.0, None
        for i, (gcat, gbox) in enumerate(gts):
            if i in used:
                continue
            if class_aware and gcat != cat:
                continue
            v = bbox_iou(box, gbox)
            if v > best:
                best, best_i = v, i
        if best >= iou_thresh and best_i is not None:
            used.add(best_i)
            tp += 1
    fp = len(preds) - tp
    fn = len(gts) - tp
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(p, 4), "recall": round(r, 4),
        "f1": round(2 * p * r / max(1e-9, p + r), 4),
    }


def count_accuracy(preds, gts) -> dict:
    pc = collections.Counter(c for c, _b, _s in preds)
    gc = collections.Counter(c for c, _b in gts)
    rows = []
    total_err = 0
    total_gt = 0
    for cat in sorted(set(pc) | set(gc)):
        p, g = pc.get(cat, 0), gc.get(cat, 0)
        err = abs(p - g)
        total_err += err
        total_gt += g
        rows.append({
            "category": cat, "predicted": p, "ground_truth": g,
            "abs_error": err,
            "accuracy": round(1 - err / g, 4) if g else None,
        })
    return {
        "per_class": rows,
        "total_predicted": sum(pc.values()),
        "total_ground_truth": total_gt,
        "count_accuracy": round(max(0.0, 1 - total_err / max(1, total_gt)), 4),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def evaluate(dataset: str, out_dir: str, limit: int | None = None,
             only: str = "all", offset: int = 0) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    report: dict = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "level1": {}, "level2": {}}

    # ---- Level 1 ---------------------------------------------------------
    sheets = []
    if only in ("all", "level1"):
      for folder in sorted(glob.glob(os.path.join(dataset, "training", "mechanical", "*/"))):
        folder = folder.rstrip("/\\")
        pdfs = [p for p in glob.glob(os.path.join(folder, "*.pdf")) if "_detected" not in os.path.basename(p)]
        if not pdfs or not load_component_gt(folder):
            continue
        sheets.append((folder, pdfs[0]))
    sheets = sheets[offset:]
    if limit:
        sheets = sheets[:limit]

    all_preds: list = []
    all_gts: list = []
    per_sheet = []

    for folder, pdf in sheets:
        gts = load_component_gt(folder)
        t0 = time.time()
        try:
            with DrawingDocument(pdf) as doc:
                sheet = doc.sheet(0)
                dets, _glyphs = detect_symbols(sheet, discipline="mechanical", mine=False)
        except Exception as exc:  # pragma: no cover
            print(f"  ! {os.path.basename(folder)[:40]}: {exc}")
            continue
        preds = [(d.category, d.bbox_pt, d.confidence) for d in dets]
        m = match(preds, gts)
        ma = match(preds, gts, class_aware=False)
        ca = count_accuracy(preds, gts)
        per_sheet.append({
            "sheet": os.path.basename(folder),
            "seconds": round(time.time() - t0, 2),
            "predicted": len(preds), "ground_truth": len(gts),
            "detection": m, "localisation_recall": ma["recall"],
            "count_accuracy": ca["count_accuracy"],
        })
        all_preds.extend(preds)
        all_gts.extend(gts)
        print(
            f"  {os.path.basename(folder)[-30:]:32s} "
            f"pred={len(preds):4d} gt={len(gts):4d} "
            f"P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} "
            f"loc-R={ma['recall']:.2f} count-acc={ca['count_accuracy']:.2f} "
            f"({per_sheet[-1]['seconds']}s)"
        )

    report["level1"] = {
        "sheets": per_sheet,
        "overall_detection": match(all_preds, all_gts),
        "overall_localisation": match(all_preds, all_gts, class_aware=False),
        "overall_counts": count_accuracy(all_preds, all_gts),
        "mean_seconds_per_sheet": round(
            sum(s["seconds"] for s in per_sheet) / max(1, len(per_sheet)), 2
        ),
    }

    # ---- Level 2 ---------------------------------------------------------
    lin_rows = []
    for disc, pattern, suffix in (() if only == "level1" else (
        ("mechanical", os.path.join("training", "mechanical", "*/"), "_detected_hvac"),
        ("plumbing", os.path.join("training", "plumbing", "*/"), "_detected_pipelines"),
    )):
        folders = sorted(glob.glob(os.path.join(dataset, pattern)))
        if True:
            folders = folders[offset:]
            if limit:
                folders = folders[:limit]
        for folder in folders:
            folder = folder.rstrip("/\\")
            pdfs = [p for p in glob.glob(os.path.join(folder, "*.pdf")) if "_detected" not in os.path.basename(p)]
            gt = load_linear_gt(folder, suffix)
            if not pdfs or not gt:
                continue
            try:
                with DrawingDocument(pdfs[0]) as doc:
                    sheet = doc.sheet(0)
                    sel, layer = select_system_linework(sheet)
            except Exception as exc:  # pragma: no cover
                print(f"  ! {os.path.basename(folder)[:40]}: {exc}")
                continue
            got = {_seg_key(p.x0, p.y0, p.x1, p.y1) for p in sel}
            hit = len(gt & got)
            row = {
                "sheet": os.path.basename(folder), "discipline": disc,
                "gt_segments": len(gt), "selected_segments": len(got),
                "recovered": hit,
                "recall": round(hit / max(1, len(gt)), 4),
                "precision": round(hit / max(1, len(got)), 4),
                "layer": layer.as_dict(),
            }
            lin_rows.append(row)
            print(
                f"  [{disc[:4]}] {os.path.basename(folder)[-28:]:30s} "
                f"gt={len(gt):6d} sel={len(got):6d} recall={row['recall']:.3f} prec={row['precision']:.3f}"
            )

    tot_gt = sum(r["gt_segments"] for r in lin_rows)
    tot_hit = sum(r["recovered"] for r in lin_rows)
    tot_sel = sum(r["selected_segments"] for r in lin_rows)
    report["level2"] = {
        "sheets": lin_rows,
        "overall_recall": round(tot_hit / max(1, tot_gt), 4),
        "overall_precision": round(tot_hit / max(1, tot_sel), 4),
        "mechanical_recall": round(
            sum(r["recovered"] for r in lin_rows if r["discipline"] == "mechanical")
            / max(1, sum(r["gt_segments"] for r in lin_rows if r["discipline"] == "mechanical")), 4
        ),
        "plumbing_recall": round(
            sum(r["recovered"] for r in lin_rows if r["discipline"] == "plumbing")
            / max(1, sum(r["gt_segments"] for r in lin_rows if r["discipline"] == "plumbing")), 4
        ),
    }

    path = os.path.join(out_dir, f"evaluation{'' if only == 'all' else '_' + only}{'' if not offset else '_' + str(offset)}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nWrote {path}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="../CTD Dataset/CTD Dataset")
    ap.add_argument("--out", default="../evaluation")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", choices=["all", "level1", "level2"], default="all")
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    print("=== Level 1 — detection, classification and counting ===")
    report = evaluate(args.dataset, args.out, args.limit, args.only, args.offset)

    l1 = report["level1"]
    l2 = report["level2"]
    print("\n=== Summary ===")
    print(f"Level 1  detection  P={l1['overall_detection']['precision']:.3f} "
          f"R={l1['overall_detection']['recall']:.3f} F1={l1['overall_detection']['f1']:.3f}")
    print(f"Level 1  localisation recall (class-agnostic) = {l1['overall_localisation']['recall']:.3f}")
    print(f"Level 1  count accuracy = {l1['overall_counts']['count_accuracy']:.3f}")
    print(f"Level 1  mean time per sheet = {l1['mean_seconds_per_sheet']}s")
    print(f"Level 2  geometry recall = {l2['overall_recall']:.3f} "
          f"(mech {l2['mechanical_recall']:.3f}, plumb {l2['plumbing_recall']:.3f})")
    print(f"Level 2  geometry precision = {l2['overall_precision']:.3f}")


if __name__ == "__main__":
    main()
