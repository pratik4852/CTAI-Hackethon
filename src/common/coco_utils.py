"""
COCO utilities for the CTD MEP dataset.

The dataset ships ground truth in per-file COCO JSON. Two important facts drive
this module:

1. Category IDs are LOCAL to each file. The same symbol ("Duplex Receptacle")
   can be id 4 in one file and id 2 in another. We therefore ALWAYS merge
   classes by NAME, never by id, and build a single global class map.

2. Two kinds of COCO files live under training/:
   - Object-detection ground truth  -> the symbol classes (Level 1). These are
     the mechanical "N) <sheet>.json" files and the electrical
     "instances_all.json" files.
   - Duct geometry  -> a single "duct_segment" class inside
     "*_detected_hvac.json" (this is Level 2 linear data, NOT Level 1).

This module discovers the Level-1 object-detection files, loads them, and
exposes a global class map plus helpers to resolve each COCO image back to the
source PDF page so it can be rendered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# Categories that mark a file as Level-2 duct geometry rather than Level-1 objects.
_DUCT_ONLY_CATEGORY_NAMES = {"duct_segment"}


@dataclass
class CocoFile:
    """A loaded object-detection COCO file plus provenance."""

    path: Path
    discipline: str  # "mechanical" | "electrical" | "plumbing" | "unknown"
    data: dict
    images: Dict[int, dict] = field(default_factory=dict)      # image_id -> image
    categories: Dict[int, str] = field(default_factory=dict)   # local id -> name

    @property
    def folder(self) -> Path:
        return self.path.parent


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _category_names(data: dict) -> List[str]:
    return [c.get("name", "") for c in data.get("categories", [])]


def is_object_detection_coco(data: dict) -> bool:
    """True for Level-1 symbol files, False for duct_segment / empty files."""
    names = set(_category_names(data))
    if not names:
        return False
    # A file that ONLY contains duct_segment is Level-2 geometry, skip it.
    if names.issubset(_DUCT_ONLY_CATEGORY_NAMES):
        return False
    return True


def infer_discipline(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    for d in ("mechanical", "electrical", "plumbing"):
        if d in parts:
            return d
    return "unknown"


def find_object_detection_cocos(dataset_root: Path,
                                split: str = "training") -> List[CocoFile]:
    """
    Walk <dataset_root>/<split> and return every Level-1 object-detection COCO
    file, skipping the "*_detected_hvac.json" duct-geometry files.
    """
    root = Path(dataset_root) / split
    out: List[CocoFile] = []
    for jp in sorted(root.rglob("*.json")):
        if jp.name.endswith("_detected_hvac.json"):
            continue  # Level-2 duct geometry
        try:
            data = load_json(jp)
        except Exception as exc:  # noqa: BLE001 - skip unreadable files, keep going
            print(f"[coco] WARN could not parse {jp}: {exc}")
            continue
        if not isinstance(data, dict) or "annotations" not in data:
            continue
        if not is_object_detection_coco(data):
            continue
        cf = CocoFile(
            path=jp,
            discipline=infer_discipline(jp),
            data=data,
            images={img["id"]: img for img in data.get("images", [])},
            categories={c["id"]: c["name"] for c in data.get("categories", [])},
        )
        out.append(cf)
    return out


def build_global_class_map(coco_files: Iterable[CocoFile],
                           disciplines: Optional[Iterable[str]] = None
                           ) -> Dict[str, int]:
    """
    Merge all category names into one deterministic, alphabetical class map.

    disciplines: optionally restrict to e.g. {"mechanical"} or {"electrical"}.
    Returns {class_name: contiguous_id starting at 0} for YOLO.
    """
    allow = set(disciplines) if disciplines else None
    names = set()
    for cf in coco_files:
        if allow and cf.discipline not in allow:
            continue
        names.update(cf.categories.values())
    return {name: i for i, name in enumerate(sorted(names))}


def resolve_source_pdf(coco: CocoFile, image: dict) -> Tuple[Optional[Path], int]:
    """
    Map a COCO image entry back to (source_pdf_path, page_number_1indexed).

    Mechanical folders contain exactly one input PDF (the "*_detected_hvac.pdf"
    is the annotated visualization and is ignored). Electrical folders contain
    one multi-page PDF and the image's "page" field selects the page.
    """
    candidates = [
        p for p in coco.folder.glob("*.pdf")
        if not p.name.endswith("_detected_hvac.pdf")
    ]
    page = int(image.get("page", 1) or 1)
    if not candidates:
        return None, page
    if len(candidates) == 1:
        return candidates[0], page
    # Multiple PDFs: prefer one whose stem is contained in the image file name.
    stem_hint = Path(image.get("file_name", "")).stem.lower()
    for p in candidates:
        if p.stem.lower() in stem_hint:
            return p, page
    return candidates[0], page


def iter_annotations(coco: CocoFile) -> Iterable[Tuple[dict, dict, str]]:
    """Yield (image_dict, annotation_dict, class_name) for every annotation."""
    for ann in coco.data.get("annotations", []):
        img = coco.images.get(ann["image_id"])
        if img is None:
            continue
        name = coco.categories.get(ann["category_id"])
        if name is None:
            continue
        yield img, ann, name


def save_class_map(class_map: Dict[str, int], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inverted = {v: k for k, v in class_map.items()}
    payload = {
        "num_classes": len(class_map),
        "names": [inverted[i] for i in range(len(inverted))],
        "name_to_id": class_map,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def load_class_map(path: Path) -> Dict[str, int]:
    payload = load_json(Path(path))
    return payload["name_to_id"]
