"""
Analyze the full CTD MEP dataset (Level-1 object-detection ground truth).

Walks every training COCO file, merges classes by name, and reports:
  - global class list (per discipline and combined)
  - per-class instance counts
  - per-sheet annotation counts
  - image size distribution
  - bounding-box size distribution (helps choose tile size / anchors)

Outputs (written to --out):
  class_counts.csv, sheet_counts.csv, box_sizes.csv,
  dataset_report.json, dataset_report.md, and PNG histograms.

Run:
  python -m src.analysis.analyze_dataset \
      --dataset "E:/CTA Dataset/CTD Dataset" --out outputs/analysis
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow "python src/analysis/analyze_dataset.py" as well as -m execution.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.common.coco_utils import (  # noqa: E402
    CocoFile, build_global_class_map, find_object_detection_cocos,
    iter_annotations, save_class_map,
)


def analyze(dataset_root: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cocos = find_object_detection_cocos(dataset_root, "training")
    if not cocos:
        raise SystemExit(f"No object-detection COCO files found under {dataset_root}/training")

    per_class = Counter()                      # class name -> instances
    per_class_by_disc = defaultdict(Counter)   # discipline -> class -> instances
    per_sheet_rows = []                        # one row per image/sheet
    box_rows = []                              # per-box size samples
    disc_files = Counter()

    for cf in cocos:
        disc_files[cf.discipline] += 1
        sheet_counts = defaultdict(Counter)    # image_id -> class -> n
        for img, ann, name in iter_annotations(cf):
            per_class[name] += 1
            per_class_by_disc[cf.discipline][name] += 1
            sheet_counts[img["id"]][name] += 1
            bw, bh = float(ann["bbox"][2]), float(ann["bbox"][3])
            box_rows.append({
                "discipline": cf.discipline, "class": name,
                "w": round(bw, 2), "h": round(bh, 2),
                "area": round(bw * bh, 2),
                "img_w": img.get("width"), "img_h": img.get("height"),
            })
        for image_id, counts in sheet_counts.items():
            img = cf.images[image_id]
            per_sheet_rows.append({
                "discipline": cf.discipline,
                "coco_file": cf.path.name,
                "image_id": image_id,
                "file_name": img.get("file_name"),
                "width": img.get("width"),
                "height": img.get("height"),
                "num_objects": sum(counts.values()),
                "num_classes": len(counts),
            })

    combined_map = build_global_class_map(cocos)
    mech_map = build_global_class_map(cocos, disciplines={"mechanical"})
    elec_map = build_global_class_map(cocos, disciplines={"electrical"})

    report = {
        "dataset_root": str(dataset_root),
        "num_coco_files": len(cocos),
        "files_per_discipline": dict(disc_files),
        "num_sheets": len(per_sheet_rows),
        "total_annotations": int(sum(per_class.values())),
        "num_classes_combined": len(combined_map),
        "num_classes_mechanical": len(mech_map),
        "num_classes_electrical": len(elec_map),
        "classes_mechanical": sorted(mech_map),
        "classes_electrical": sorted(elec_map),
        "per_class_counts": dict(per_class.most_common()),
        "per_class_by_discipline": {
            d: dict(c.most_common()) for d, c in per_class_by_disc.items()
        },
    }

    _write_csv(out_dir / "class_counts.csv",
               ["class", "discipline", "instances"],
               [(name, disc, n)
                for disc, c in per_class_by_disc.items()
                for name, n in c.most_common()])
    _write_csv(out_dir / "sheet_counts.csv",
               ["discipline", "coco_file", "file_name", "width", "height",
                "num_objects", "num_classes"],
               [(r["discipline"], r["coco_file"], r["file_name"], r["width"],
                 r["height"], r["num_objects"], r["num_classes"])
                for r in per_sheet_rows])
    _write_csv(out_dir / "box_sizes.csv",
               ["discipline", "class", "w", "h", "area", "img_w", "img_h"],
               [(b["discipline"], b["class"], b["w"], b["h"], b["area"],
                 b["img_w"], b["img_h"]) for b in box_rows])

    with open(out_dir / "dataset_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    # Save the class maps we will train against.
    save_class_map(combined_map, out_dir / "classes_combined.json")
    save_class_map(mech_map, out_dir / "classes_mechanical.json")
    save_class_map(elec_map, out_dir / "classes_electrical.json")

    _write_markdown(out_dir / "dataset_report.md", report, per_sheet_rows, box_rows)
    _plots(out_dir, per_class, box_rows, per_sheet_rows)

    print(f"[analyze] {len(cocos)} COCO files, {len(per_sheet_rows)} sheets, "
          f"{report['total_annotations']} annotations")
    print(f"[analyze] classes: mech={len(mech_map)} elec={len(elec_map)} "
          f"combined={len(combined_map)}")
    print(f"[analyze] wrote report to {out_dir}")
    return report


def _write_csv(path: Path, header, rows) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _write_markdown(path: Path, report: dict, sheet_rows, box_rows) -> None:
    lines = ["# Dataset Analysis — Level 1 (Detection & Counting)", ""]
    lines.append(f"- COCO files: **{report['num_coco_files']}** "
                 f"({report['files_per_discipline']})")
    lines.append(f"- Sheets/pages: **{report['num_sheets']}**")
    lines.append(f"- Total annotations: **{report['total_annotations']}**")
    lines.append(f"- Classes — mechanical **{report['num_classes_mechanical']}**, "
                 f"electrical **{report['num_classes_electrical']}**, "
                 f"combined **{report['num_classes_combined']}**")
    lines.append("")
    for disc in ("mechanical", "electrical"):
        counts = report["per_class_by_discipline"].get(disc, {})
        if not counts:
            continue
        lines.append(f"## {disc.title()} classes")
        lines.append("")
        lines.append("| Class | Instances |")
        lines.append("|---|---:|")
        for name, n in counts.items():
            lines.append(f"| {name} | {n} |")
        lines.append(f"| **TOTAL** | **{sum(counts.values())}** |")
        lines.append("")
    if box_rows:
        areas = sorted(b["area"] for b in box_rows)
        n = len(areas)
        lines.append("## Bounding-box size (px area)")
        lines.append("")
        lines.append(f"- min {areas[0]:.0f}, median {areas[n // 2]:.0f}, "
                     f"max {areas[-1]:.0f}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _plots(out_dir: Path, per_class: Counter, box_rows, sheet_rows) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[analyze] matplotlib unavailable, skipping plots ({exc})")
        return

    if per_class:
        names = [k for k, _ in per_class.most_common()]
        vals = [per_class[k] for k in names]
        plt.figure(figsize=(10, max(4, len(names) * 0.4)))
        plt.barh(names[::-1], vals[::-1])
        plt.xlabel("instances")
        plt.title("Instances per class")
        plt.tight_layout()
        plt.savefig(out_dir / "plot_class_counts.png", dpi=120)
        plt.close()

    if box_rows:
        import numpy as np
        areas = np.sqrt(np.array([b["area"] for b in box_rows], dtype=float))
        plt.figure(figsize=(8, 5))
        plt.hist(areas, bins=60)
        plt.xlabel("sqrt(box area) in px  (~symbol side length)")
        plt.ylabel("count")
        plt.title("Symbol size distribution")
        plt.tight_layout()
        plt.savefig(out_dir / "plot_box_sizes.png", dpi=120)
        plt.close()

    if sheet_rows:
        objs = [r["num_objects"] for r in sheet_rows]
        plt.figure(figsize=(8, 5))
        plt.hist(objs, bins=30)
        plt.xlabel("objects per sheet")
        plt.ylabel("sheets")
        plt.title("Annotations per sheet")
        plt.tight_layout()
        plt.savefig(out_dir / "plot_objects_per_sheet.png", dpi=120)
        plt.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze CTD MEP dataset")
    ap.add_argument("--dataset", required=True, help="path to 'CTD Dataset' root")
    ap.add_argument("--out", default="outputs/analysis", help="output directory")
    args = ap.parse_args()
    analyze(Path(args.dataset), Path(args.out))


if __name__ == "__main__":
    main()
