"""
Convert the CTD MEP COCO ground truth into a tiled YOLO dataset.

Steps per sheet:
  1. Resolve the source PDF page and render it at 150 DPI (aligned to the
     annotation coordinate space).
  2. Slice the sheet into overlapping tiles.
  3. Write each tile as a PNG and a YOLO label file, remapping boxes into
     tile-local normalized coordinates.

Train/val split is done at the SHEET level (all tiles of a sheet share a split)
so no symbol leaks between train and val.

Run:
  python -m src.data_prep.coco_to_yolo \
      --dataset "E:/CTA Dataset/CTD Dataset" \
      --out data/yolo --mode combined --tile 1280 --overlap 0.2
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.common.coco_utils import (  # noqa: E402
    build_global_class_map, find_object_detection_cocos, resolve_source_pdf,
    save_class_map,
)
from src.common.pdf_render import render_page, save_image  # noqa: E402
from src.common.tiling import (  # noqa: E402
    clip_box_to_tile, tile_grid, xywh_to_yolo,
)


def _split_for(key: str, val_frac: float) -> str:
    """Deterministic per-sheet split from a stable hash of the sheet key."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16) % 10_000
    return "val" if h < int(val_frac * 10_000) else "train"


def convert(dataset_root: Path, out_dir: Path, mode: str = "combined",
            tile_size: int = 1280, overlap: float = 0.2, dpi: int = 150,
            val_frac: float = 0.2, empty_frac: float = 0.1,
            min_visibility: float = 0.3, seed: int = 0) -> None:
    random.seed(seed)
    disciplines = None if mode == "combined" else {mode}
    cocos = find_object_detection_cocos(dataset_root, "training")
    if disciplines:
        cocos = [c for c in cocos if c.discipline in disciplines]
    if not cocos:
        raise SystemExit(f"No COCO files for mode={mode} under {dataset_root}")

    class_map = build_global_class_map(cocos, disciplines)
    out_dir = Path(out_dir)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    save_class_map(class_map, out_dir / "classes.json")

    tile_stats = Counter()
    box_stats = Counter()
    rendered_cache: dict = {}

    for cf in cocos:
        # Group annotations by image so we render each page once.
        anns_by_image: dict = {}
        for ann in cf.data.get("annotations", []):
            anns_by_image.setdefault(ann["image_id"], []).append(ann)

        for image_id, img in cf.images.items():
            iw, ih = int(img.get("width", 0)), int(img.get("height", 0))
            pdf_path, page = resolve_source_pdf(cf, img)
            if pdf_path is None:
                print(f"[prep] WARN no source PDF for {cf.path.name} image {image_id}")
                continue

            sheet_key = f"{cf.path.name}#{image_id}"
            split = _split_for(sheet_key, val_frac)

            cache_key = f"{pdf_path}#{page}#{iw}x{ih}"
            if cache_key in rendered_cache:
                raster = rendered_cache[cache_key]
            else:
                try:
                    raster = render_page(pdf_path, page, dpi=dpi,
                                         target_size=(iw, ih) if iw and ih else None)
                except Exception as exc:  # noqa: BLE001
                    print(f"[prep] WARN render failed {pdf_path} p{page}: {exc}")
                    continue
                rendered_cache = {cache_key: raster}  # keep only last (memory)

            H, W = raster.shape[:2]
            # Prepare boxes as (class_id, [x,y,w,h]).
            boxes = []
            for ann in anns_by_image.get(image_id, []):
                name = cf.categories.get(ann["category_id"])
                if name not in class_map:
                    continue
                boxes.append((class_map[name], [float(v) for v in ann["bbox"]]))

            stem = _safe_stem(f"{cf.discipline}_{Path(img.get('file_name', sheet_key)).stem}_{image_id}")
            for t_idx, tile in enumerate(tile_grid(W, H, tile_size, overlap)):
                tx0, ty0, tx1, ty1 = tile
                tw, th = tx1 - tx0, ty1 - ty0
                lines = []
                for cls_id, box in boxes:
                    local = clip_box_to_tile(box, tile, min_visibility)
                    if local is None:
                        continue
                    xc, yc, ww, hh = xywh_to_yolo(local, tw, th)
                    lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {ww:.6f} {hh:.6f}")

                if not lines and random.random() > empty_frac:
                    continue  # drop most empty (background) tiles

                tile_name = f"{stem}__t{t_idx}_{tx0}_{ty0}"
                crop = raster[ty0:ty1, tx0:tx1]
                save_image(crop, out_dir / f"images/{split}/{tile_name}.png")
                with open(out_dir / f"labels/{split}/{tile_name}.txt", "w",
                          encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
                tile_stats[split] += 1
                box_stats[split] += len(lines)
            print(f"[prep] {cf.discipline:11s} {stem}  split={split}  "
                  f"boxes={len(boxes)}")

    _write_dataset_yaml(out_dir, class_map)
    print(f"[prep] tiles: {dict(tile_stats)}  boxes: {dict(box_stats)}")
    print(f"[prep] dataset.yaml written to {out_dir/'dataset.yaml'}")


def _safe_stem(s: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in s]
    return "".join(keep)[:120]


def _write_dataset_yaml(out_dir: Path, class_map) -> None:
    inv = {v: k for k, v in class_map.items()}
    names = [inv[i] for i in range(len(inv))]
    # Write YAML by hand to avoid quoting surprises with special characters.
    lines = [
        f"path: {out_dir.resolve().as_posix()}",
        "train: images/train",
        "val: images/val",
        f"nc: {len(names)}",
        "names:",
    ]
    for i, n in enumerate(names):
        safe = n.replace('"', "'")
        lines.append(f'  {i}: "{safe}"')
    with open(out_dir / "dataset.yaml", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="COCO -> tiled YOLO dataset")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default="data/yolo")
    ap.add_argument("--mode", default="combined",
                    choices=["combined", "mechanical", "electrical"])
    ap.add_argument("--tile", type=int, default=1280)
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--empty-frac", type=float, default=0.1,
                    help="fraction of background (no-object) tiles to keep")
    ap.add_argument("--min-visibility", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    convert(Path(args.dataset), Path(args.out), args.mode, args.tile, args.overlap,
            args.dpi, args.val_frac, args.empty_frac, args.min_visibility, args.seed)


if __name__ == "__main__":
    main()
