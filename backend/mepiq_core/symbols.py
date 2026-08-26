"""
Level 1 — quantifiable object detection, identification and counting.

Two detectors run side by side and their outputs are fused:

**A. Symbol grammar (supervised by the drawing legend, not by pixels).**
The dataset ships a symbol catalogue that defines each component *geometrically*
— "a square with an X and a central circle", "a square with a single diagonal",
"a line crossed by evenly spaced hash marks". Those are executable rules over
the shapes assembled in ``geometry.py``. Because the rule is the definition, a
detection is exact, scale-free, rotation-free and explainable: the app can tell
a reviewer *"18.0 x 18.0 pt square, two corner-to-corner diagonals, 3.1 pt
central circle"*, which is something no bounding-box confidence score can do.

**B. Glyph mining (unsupervised).**
CAD symbols are stamped from blocks, so every instance of a symbol is the same
geometry translated and rotated. Mining recurring canonical geometry signatures
finds *every* repeated component on a sheet — including symbols nobody has ever
labelled. Counts from mining are exact by construction. A one-click label from
the reviewer turns a mined glyph into a named library entry that then applies to
every future drawing: the product gets better with use.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

from .geometry import (
    Circle,
    HatchRun,
    Polygon,
    SegmentIndex,
    UnionFind,
    bbox_iou,
    bbox_union,
    find_circles,
    find_closed_polygons,
    find_hatch_runs,
    nms,
)
from .pdfdoc import GT_DPI, PT_PER_INCH, Primitive, Sheet, bbox_pt_to_px

# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolSpec:
    key: str
    name: str
    trade: str
    category: str
    description: str
    unit: str = "EA"
    countable: bool = True


CATALOGUE: dict[str, SymbolSpec] = {
    s.key: s
    for s in [
        SymbolSpec(
            "square_supply_diffuser_4way", "Square Supply Diffuser (4-Way)", "HVAC", "Air Terminals",
            "Square ceiling diffuser with a 4-way throw pattern: an 'X' across the face for the "
            "louvre directions and a central circle for the round neck connection.",
        ),
        SymbolSpec(
            "flexible_duct", "Flexible Duct (Flex Duct)", "HVAC", "Ductwork",
            "A line crossed by evenly spaced perpendicular hash marks, representing flexible "
            "ductwork between a rigid branch and an air terminal.", unit="LF", countable=True,
        ),
        SymbolSpec(
            "fire_damper", "Fire Damper (FD)", "HVAC", "In-Line Duct Accessories",
            "A square with an 'X' inside, drawn in-line with ductwork, with one heavy side "
            "denoting the fire-rated barrier it penetrates.",
        ),
        SymbolSpec(
            "square_return_exhaust_register", "Square Return / Exhaust Register", "HVAC", "Air Terminals",
            "A square ceiling register with a single diagonal across the face — the standard "
            "convention distinguishing return/exhaust from a supply diffuser.",
        ),
        SymbolSpec(
            "water_source_heat_pump", "Water Source Heat Pump (WSHP) / Vertical Heat Pump (VHP)", "HVAC",
            "Major Equipment",
            "A packaged heat-pump footprint: a rectangle containing a prominent solid diamond.",
        ),
        SymbolSpec(
            "round_supply_diffuser", "Round Supply Diffuser", "HVAC", "Air Terminals",
            "Concentric circles representing the conical rings of a 360-degree radial diffuser.",
        ),
        SymbolSpec(
            "linear_bar_grille", "Linear Bar Grille / Linear Slot Diffuser", "HVAC", "Air Terminals",
            "A long narrow rectangle with internal parallel lines representing slots or vanes.",
        ),
        SymbolSpec(
            "elevation_benchmark", "Elevation Benchmark (Datum Target)", "Architecture", "Annotations and Callouts",
            "A circle divided into alternating filled and open quadrants, marking a datum "
            "elevation reference.",
        ),
    ]
}

CATALOGUE_BY_NAME = {s.name: s for s in CATALOGUE.values()}


# ---------------------------------------------------------------------------
# Detection record
# ---------------------------------------------------------------------------


@dataclass
class Detection:
    category: str
    category_key: str
    trade: str
    bbox_pt: list[float]           # [x0, y0, x1, y1] in PDF points
    confidence: float
    detector: str                  # "grammar" | "glyph" | "library" | "manual"
    rationale: str = ""
    attributes: dict = field(default_factory=dict)
    glyph_id: str | None = None
    review: str = "unreviewed"     # unreviewed | confirmed | rejected | corrected
    id: int = 0

    @property
    def center(self) -> tuple[float, float]:
        b = self.bbox_pt
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def to_coco(self, image_id: int, category_id: int, dpi: float = GT_DPI) -> dict:
        x, y, w, h = bbox_pt_to_px(self.bbox_pt, dpi)
        return {
            "id": self.id,
            "image_id": image_id,
            "category_id": category_id,
            "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
            "area": round(w * h, 2),
            "iscrowd": 0,
            "score": round(self.confidence, 3),
            "trade": self.trade,
            "detector": self.detector,
            "rationale": self.rationale,
            "attributes": self.attributes,
        }

    def as_dict(self) -> dict:
        d = asdict(self)
        d["center_pt"] = list(self.center)
        return d


def bbox_pt_to_px_xywh(b: Sequence[float], dpi: float = GT_DPI) -> list[float]:
    return bbox_pt_to_px(b, dpi)


# ---------------------------------------------------------------------------
# A. Symbol grammar
# ---------------------------------------------------------------------------


def _diagonals_in(poly: Polygon, prims: Sequence[Primitive], index: SegmentIndex, tol: float = 0.9) -> list[int]:
    """Segments that run corner-to-corner across a quadrilateral."""
    if len(poly.points) != 4:
        return []
    pts = poly.points
    diag_targets = [(pts[0], pts[2]), (pts[1], pts[3])]
    x0, y0, x1, y1 = poly.bbox
    found: list[int] = []
    for i in index.query_box(x0 - tol, y0 - tol, x1 + tol, y1 + tol):
        p = prims[i]
        if i in poly.member_ids:
            continue
        a, b = (p.x0, p.y0), (p.x1, p.y1)
        for da, db in diag_targets:
            ok = (
                math.hypot(a[0] - da[0], a[1] - da[1]) <= tol and math.hypot(b[0] - db[0], b[1] - db[1]) <= tol
            ) or (
                math.hypot(a[0] - db[0], a[1] - db[1]) <= tol and math.hypot(b[0] - da[0], b[1] - da[1]) <= tol
            )
            if ok:
                found.append(i)
                break
    return found


def _circles_centred_in(poly: Polygon, circles: Sequence[Circle], frac: float = 0.28) -> list[Circle]:
    cx, cy = poly.center
    w, h = poly.size
    side = min(w, h)
    out = []
    for c in circles:
        if math.hypot(c.cx - cx, c.cy - cy) <= side * frac and c.r <= side * 0.48:
            out.append(c)
    return out


def _interior_parallel_lines(poly: Polygon, prims: Sequence[Primitive], index: SegmentIndex) -> int:
    """Count segments running along the long axis inside a narrow rectangle."""
    x0, y0, x1, y1 = poly.bbox
    w, h = x1 - x0, y1 - y0
    horizontal = w >= h
    n = 0
    for i in index.query_box(x0, y0, x1, y1):
        if i in poly.member_ids:
            continue
        p = prims[i]
        bx0, by0, bx1, by1 = p.bbox()
        if bx0 < x0 - 0.4 or bx1 > x1 + 0.4 or by0 < y0 - 0.4 or by1 > y1 + 0.4:
            continue
        ang = p.angle
        along = ang < 0.15 or ang > math.pi - 0.15 if horizontal else abs(ang - math.pi / 2) < 0.15
        if along and p.length >= max(w, h) * 0.45:
            n += 1
    return n


def _is_filled_diamond(poly: Polygon) -> bool:
    if len(poly.points) != 4:
        return False
    w, h = poly.size
    if max(w, h) < 1e-6 or min(w, h) / max(w, h) < 0.45:
        return False
    # A diamond's vertices sit at the edge midpoints of its bounding box.
    x0, y0, x1, y1 = poly.bbox
    mids = [((x0 + x1) / 2, y0), (x1, (y0 + y1) / 2), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2)]
    tol = max(w, h) * 0.22
    matched = 0
    for m in mids:
        if any(math.hypot(p[0] - m[0], p[1] - m[1]) <= tol for p in poly.points):
            matched += 1
    return matched >= 3


def detect_by_grammar(
    prims: Sequence[Primitive],
    index: SegmentIndex,
    max_symbol_pt: float = 90.0,
) -> list[Detection]:
    """Apply the legend's geometric definitions directly."""
    out: list[Detection] = []

    polys = find_closed_polygons(prims, max_size=max_symbol_pt, min_size=2.5)
    circles = find_circles(prims, max_r=max_symbol_pt / 2)
    hatches = find_hatch_runs(prims)

    circ_index_pts = circles
    consumed_polys: set[int] = set()

    # --- squares with diagonals -------------------------------------------
    for pi, poly in enumerate(polys):
        if not poly.is_rectangle():
            continue
        w, h = poly.size
        if max(w, h) < 3.0 or max(w, h) > max_symbol_pt:
            continue
        aspect = max(w, h) / max(min(w, h), 1e-6)

        diags = _diagonals_in(poly, prims, index)
        inner_circles = _circles_centred_in(poly, circ_index_pts)

        if aspect <= 1.35 and len(diags) >= 2:
            if inner_circles:
                c = max(inner_circles, key=lambda c: c.r)
                out.append(
                    Detection(
                        CATALOGUE["square_supply_diffuser_4way"].name, "square_supply_diffuser_4way", "HVAC",
                        list(poly.bbox), 0.94, "grammar",
                        f"{w:.1f}x{h:.1f} pt square with 2 corner diagonals and a {c.r * 2:.1f} pt central circle",
                        {"face_size_pt": round(max(w, h), 2), "neck_dia_pt": round(c.r * 2, 2)},
                    )
                )
            else:
                heavy = max((prims[i].width for i in poly.member_ids), default=0.0)
                light = min((prims[i].width for i in poly.member_ids), default=0.0)
                bold_side = heavy > light * 1.4 and heavy > 0.5
                out.append(
                    Detection(
                        CATALOGUE["fire_damper"].name, "fire_damper", "HVAC",
                        list(poly.bbox), 0.90 if bold_side else 0.83, "grammar",
                        f"{w:.1f}x{h:.1f} pt square with an internal 'X'"
                        + (f"; heavy {heavy:.2f} pt side indicates the rated barrier" if bold_side else ""),
                        {"barrier_side_weight": round(heavy, 2)},
                    )
                )
            consumed_polys.add(pi)
            continue

        if aspect <= 1.45 and len(diags) == 1:
            out.append(
                Detection(
                    CATALOGUE["square_return_exhaust_register"].name, "square_return_exhaust_register", "HVAC",
                    list(poly.bbox), 0.88, "grammar",
                    f"{w:.1f}x{h:.1f} pt square with a single diagonal (return/exhaust convention)",
                    {"face_size_pt": round(max(w, h), 2)},
                )
            )
            consumed_polys.add(pi)
            continue

        # --- linear bar grille --------------------------------------------
        if aspect >= 2.2 and max(w, h) >= 8.0:
            n_int = _interior_parallel_lines(poly, prims, index)
            if n_int >= 1:
                out.append(
                    Detection(
                        CATALOGUE["linear_bar_grille"].name, "linear_bar_grille", "HVAC",
                        list(poly.bbox), min(0.93, 0.74 + 0.06 * n_int), "grammar",
                        f"{max(w, h):.1f}x{min(w, h):.1f} pt slot with {n_int} internal vane line(s)",
                        {"length_pt": round(max(w, h), 2), "slots": n_int},
                    )
                )
                consumed_polys.add(pi)
                continue

        # --- heat pump: rectangle containing a filled diamond ---------------
        if 1.0 <= aspect <= 2.6 and max(w, h) >= 6.0:
            x0, y0, x1, y1 = poly.bbox
            for pj, inner in enumerate(polys):
                if pj == pi or pj in consumed_polys:
                    continue
                ix0, iy0, ix1, iy1 = inner.bbox
                if ix0 < x0 - 0.3 or ix1 > x1 + 0.3 or iy0 < y0 - 0.3 or iy1 > y1 + 0.3:
                    continue
                if inner.area < poly.area * 0.06:
                    continue
                if _is_filled_diamond(inner):
                    out.append(
                        Detection(
                            CATALOGUE["water_source_heat_pump"].name, "water_source_heat_pump", "HVAC",
                            list(poly.bbox), 0.86, "grammar",
                            f"{w:.1f}x{h:.1f} pt equipment footprint containing a solid diamond",
                            {"footprint_pt": [round(w, 2), round(h, 2)]},
                        )
                    )
                    consumed_polys.add(pi)
                    consumed_polys.add(pj)
                    break

    # --- concentric circles: round supply diffuser -------------------------
    used_circles: set[int] = set()
    by_centre: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for ci, c in enumerate(circles):
        by_centre[(int(round(c.cx)), int(round(c.cy)))].append(ci)
    # merge nearby centres
    centres = sorted(by_centre.items())
    for key, ids in centres:
        group = list(ids)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                group += by_centre.get((key[0] + dx, key[1] + dy), [])
        group = [g for g in dict.fromkeys(group) if g not in used_circles]
        if len(group) < 2:
            continue
        rs = sorted(circles[g].r for g in group)
        if rs[-1] < 1.5 or rs[-1] / max(rs[0], 1e-6) < 1.35:
            continue
        used_circles.update(group)
        cs = [circles[g] for g in group]
        box = bbox_union([c.bbox for c in cs])
        out.append(
            Detection(
                CATALOGUE["round_supply_diffuser"].name, "round_supply_diffuser", "HVAC",
                list(box), min(0.93, 0.78 + 0.05 * len(group)), "grammar",
                f"{len(group)} concentric circles, outer diameter {rs[-1] * 2:.1f} pt",
                {"outer_dia_pt": round(rs[-1] * 2, 2), "rings": len(group)},
            )
        )

    # --- flexible duct -----------------------------------------------------
    for hr in hatches:
        if hr.length < 4.0:
            continue
        out.append(
            Detection(
                CATALOGUE["flexible_duct"].name, "flexible_duct", "HVAC",
                list(hr.bbox), min(0.94, 0.70 + 0.03 * hr.n_ticks), "grammar",
                f"spine of {hr.length:.1f} pt crossed by {hr.n_ticks} hash marks at {hr.pitch:.2f} pt pitch",
                {"length_pt": round(hr.length, 2), "ticks": hr.n_ticks, "pitch_pt": round(hr.pitch, 2)},
            )
        )

    # --- datum target: circle with filled quadrants ------------------------
    for ci, c in enumerate(circles):
        if ci in used_circles or c.r < 2.0 or c.r > 25.0:
            continue
        filled_near = 0
        for i in index.query_radius(c.cx, c.cy, c.r * 1.2):
            p = prims[i]
            if p.fill and p.length <= c.r * 3:
                filled_near += 1
        if filled_near >= 6:
            out.append(
                Detection(
                    CATALOGUE["elevation_benchmark"].name, "elevation_benchmark", "Architecture",
                    list(c.bbox), 0.80, "grammar",
                    f"{c.r * 2:.1f} pt circle with filled quadrant wedges",
                    {"dia_pt": round(c.r * 2, 2)},
                )
            )

    boxes = [d.bbox_pt for d in out]
    scores = [d.confidence for d in out]
    keep = nms(boxes, scores, 0.45)
    return [out[i] for i in sorted(keep)]


# ---------------------------------------------------------------------------
# B. Glyph mining
# ---------------------------------------------------------------------------


@dataclass
class GlyphClass:
    glyph_id: str
    count: int
    width_pt: float
    height_pt: float
    n_segments: int
    instances: list[list[float]]           # bboxes in points
    label: str | None = None
    trade: str | None = None
    source: str = "mined"

    def as_dict(self, max_instances: int = 4000) -> dict:
        return {
            "glyph_id": self.glyph_id,
            "count": self.count,
            "width_pt": round(self.width_pt, 2),
            "height_pt": round(self.height_pt, 2),
            "n_segments": self.n_segments,
            "label": self.label,
            "trade": self.trade,
            "source": self.source,
            "instances": [[round(v, 2) for v in b] for b in self.instances[:max_instances]],
        }


def _canonical_signature(prims: Sequence[Primitive], ids: Sequence[int], quant: float = 0.25) -> tuple[str, tuple[float, float, float, float]]:
    pts: list[tuple[float, float]] = []
    for i in ids:
        p = prims[i]
        pts.append((p.x0, p.y0))
        pts.append((p.x1, p.y1))
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    ox, oy = min(xs), min(ys)
    W, H = max(xs) - ox, max(ys) - oy

    def rotate(pt: tuple[float, float], k: int) -> tuple[float, float]:
        x, y = pt
        if k == 0:
            return (x, y)
        if k == 1:
            return (H - y, x)
        if k == 2:
            return (W - x, H - y)
        return (y, W - x)

    best: tuple | None = None
    for k in range(4):
        rows = []
        for i in ids:
            p = prims[i]
            a = rotate((p.x0 - ox, p.y0 - oy), k)
            b = rotate((p.x1 - ox, p.y1 - oy), k)
            qa = (round(a[0] / quant), round(a[1] / quant))
            qb = (round(b[0] / quant), round(b[1] / quant))
            rows.append((min(qa, qb), max(qa, qb), round(p.width, 2), 1 if p.fill else 0))
        cand = tuple(sorted(rows))
        if best is None or cand < best:
            best = cand
    gid = hashlib.blake2s(repr(best).encode(), digest_size=6).hexdigest()
    return gid, (ox, oy, ox + W, oy + H)


def cluster_short_geometry(
    prims: Sequence[Primitive],
    max_segment_pt: float = 20.0,
    gap: float = 0.6,
    min_segments: int = 2,
) -> list[list[int]]:
    """
    Group touching short segments into candidate glyph blobs.

    Only short segments participate, which is what keeps symbols from fusing
    into the duct network they sit on: run linework is long, symbol strokes are
    not.
    """
    ids = [i for i, p in enumerate(prims) if 0.05 <= p.length <= max_segment_pt]
    if not ids:
        return []

    uf = UnionFind(len(ids))
    cell = max(gap * 2.0, 1.2)
    buckets: dict[tuple[int, int], list[tuple[int, float, float]]] = collections.defaultdict(list)
    for j, i in enumerate(ids):
        p = prims[i]
        for (px, py) in ((p.x0, p.y0), (p.x1, p.y1)):
            buckets[(int(px // cell), int(py // cell))].append((j, px, py))

    for (gx, gy), lst in list(buckets.items()):
        neigh: list[tuple[int, float, float]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neigh.extend(buckets.get((gx + dx, gy + dy), ()))
        for j, px, py in lst:
            for k, qx, qy in neigh:
                if j != k and abs(px - qx) <= gap and abs(py - qy) <= gap:
                    uf.union(j, k)

    out: list[list[int]] = []
    for _root, members in uf.groups().items():
        if len(members) < min_segments:
            continue
        out.append([ids[m] for m in members])
    return out


def mine_glyphs(
    prims: Sequence[Primitive],
    max_segment_pt: float = 20.0,
    gap: float = 0.6,
    min_segments: int = 2,
    max_glyph_pt: float = 90.0,
    min_count: int = 2,
) -> list[GlyphClass]:
    """Find geometry that repeats verbatim across the sheet, with exact counts."""
    classes: dict[str, GlyphClass] = {}
    for member_ids in cluster_short_geometry(prims, max_segment_pt, gap, min_segments):
        gid, box = _canonical_signature(prims, member_ids)
        w, h = box[2] - box[0], box[3] - box[1]
        if w > max_glyph_pt or h > max_glyph_pt or max(w, h) < 1.0:
            continue
        g = classes.get(gid)
        if g is None:
            classes[gid] = GlyphClass(gid, 1, w, h, len(member_ids), [list(box)])
        else:
            g.count += 1
            g.instances.append(list(box))

    return sorted(
        (g for g in classes.values() if g.count >= min_count),
        key=lambda g: -g.count,
    )


def mine_templates(
    prims: Sequence[Primitive],
    min_count: int = 3,
    max_glyph_pt: float = 90.0,
    max_segment_pt: float = 20.0,
) -> list:
    """
    Learn symbol templates from the sheet itself.

    Every glyph blob that occurs at least ``min_count`` times becomes a template
    that ``matching.find_instances`` then hunts for across the whole sheet —
    including the instances that clustering could not isolate.
    """
    from .matching import build_template, dedupe_templates

    reps: dict[str, dict] = {}
    for member_ids in cluster_short_geometry(prims, max_segment_pt=max_segment_pt):
        gid, box = _canonical_signature(prims, member_ids)
        w, h = box[2] - box[0], box[3] - box[1]
        if w > max_glyph_pt or h > max_glyph_pt or max(w, h) < 1.0:
            continue
        e = reps.get(gid)
        if e is None:
            reps[gid] = {"ids": member_ids, "n": 1}
        else:
            e["n"] += 1
            # Prefer the richest exemplar as the template geometry.
            if len(member_ids) > len(e["ids"]):
                e["ids"] = member_ids

    templates = [
        build_template(prims, e["ids"], gid, e["n"])
        for gid, e in reps.items()
        if e["n"] >= min_count
    ]
    templates.sort(key=lambda t: (-t.seed_count, -t.n_segments))
    return dedupe_templates(templates)


# ---------------------------------------------------------------------------
# Symbol library (feedback learning)
# ---------------------------------------------------------------------------


class SymbolLibrary:
    """
    Glyph signature -> component label, persisted as JSON.

    This is what makes the product improve with use: a reviewer names an unknown
    glyph once and every subsequent sheet in every subsequent project recognises
    it automatically, with full confidence, because the match is exact geometry.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = str(path) if path else None
        self.entries: dict[str, dict] = {}
        if self.path and os.path.exists(self.path):
            self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:  # type: ignore[arg-type]
                self.entries = json.load(fh).get("glyphs", {})
        except Exception:
            self.entries = {}

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "glyphs": self.entries}, fh, indent=2)
        os.replace(tmp, self.path)

    def lookup(self, glyph_id: str) -> dict | None:
        return self.entries.get(glyph_id)

    def learn(self, glyph_id: str, label: str, trade: str = "", category: str = "", note: str = "", size: Sequence[float] | None = None) -> dict:
        entry = {
            "label": label,
            "trade": trade,
            "category": category,
            "note": note,
            "size_pt": [round(float(s), 2) for s in size] if size else None,
            "confirmations": self.entries.get(glyph_id, {}).get("confirmations", 0) + 1,
        }
        self.entries[glyph_id] = entry
        self.save()
        return entry

    def forget(self, glyph_id: str) -> None:
        self.entries.pop(glyph_id, None)
        self.save()

    def as_list(self) -> list[dict]:
        return [{"glyph_id": k, **v} for k, v in sorted(self.entries.items(), key=lambda kv: -kv[1].get("confirmations", 0))]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def _text_boxes(sheet: Sheet, pad: float = 0.6) -> list[tuple[float, float, float, float]]:
    return [(t.x0 - pad, t.y0 - pad, t.x1 + pad, t.y1 + pad) for t in sheet.texts]


def _inside_any(box: Sequence[float], boxes: Sequence[tuple[float, float, float, float]]) -> bool:
    for x0, y0, x1, y1 in boxes:
        if box[0] >= x0 and box[2] <= x1 and box[1] >= y0 and box[3] <= y1:
            return True
    return False


#: The catalogue is HVAC/architectural. Running it on an electrical panel plan
#: would invent air terminals out of switchgear, so detection is scoped to the
#: disciplines whose symbols it actually describes.
GRAMMAR_DISCIPLINES = ("mechanical", "unknown")


def detect_symbols(
    sheet: Sheet,
    library: SymbolLibrary | None = None,
    min_glyph_count: int = 3,
    max_symbol_pt: float = 90.0,
    mine: bool = True,
    discipline: str = "unknown",
) -> tuple[list[Detection], list[GlyphClass]]:
    """
    Level 1 pipeline.

    1. Cluster short foreground geometry into blobs, then reassemble overlapping
       blobs into whole symbols.
    2. Classify every candidate against the legend's ideal symbols.
    3. Resolve overlaps, preferring the richer, better-scoring interpretation.
    4. Mine repeated glyphs so components outside the catalogue are still
       counted exactly and can be named by a reviewer.
    """
    from .shapes import build_candidates, classify_blob, _blob_box

    prims = sheet.foreground()
    if not prims:
        return [], []

    index = SegmentIndex(prims, cell=24.0)
    blobs = cluster_short_geometry(prims)
    candidates = build_candidates(prims, blobs, max_size_pt=max_symbol_pt, index=index)
    tboxes = _text_boxes(sheet)

    use_grammar = discipline in GRAMMAR_DISCIPLINES

    scored: list[tuple[float, int, Detection]] = []
    for ids in (candidates if use_grammar else ()):
        box = _blob_box(prims, ids)
        if _inside_any(box, tboxes):
            continue
        m = classify_blob(prims, ids)
        if m is None:
            continue
        spec = CATALOGUE[m.key]
        w, h = box[2] - box[0], box[3] - box[1]
        det = Detection(
            spec.name, m.key, spec.trade, list(box),
            round(min(0.99, m.score), 3), "grammar",
            f"{w:.1f} x {h:.1f} pt glyph matching the '{spec.name}' definition "
            f"({m.coverage * 100:.0f}% of the symbol present, {m.cleanliness * 100:.0f}% of the ink explained)",
            {"shape_score": round(m.score, 3), "coverage": round(m.coverage, 3),
             "cleanliness": round(m.cleanliness, 3), "size_pt": [round(w, 2), round(h, 2)]},
        )
        scored.append((m.score, len(ids), det))

    # Prefer the interpretation that explains more geometry at a higher score.
    scored.sort(key=lambda t: (-t[0] * (1.0 + 0.02 * min(t[1], 20)), -t[1]))
    kept: list[Detection] = []
    boxes: list[list[float]] = []
    for _s, _n, det in scored:
        if any(bbox_iou(det.bbox_pt, b) > 0.35 for b in boxes):
            continue
        kept.append(det)
        boxes.append(det.bbox_pt)

    # Flexible duct is a run, not a blob: a spine crossed by evenly spaced hash
    # marks. It gets its own detector because clustering by touch never groups
    # ticks that never touch each other.
    for hr in (find_hatch_runs(prims) if use_grammar else ()):
        if hr.length < 4.0 or hr.n_ticks < 4:
            continue
        box = list(hr.bbox)
        if any(bbox_iou(box, b) > 0.55 for b in boxes):
            continue
        spec = CATALOGUE["flexible_duct"]
        det = Detection(
            spec.name, "flexible_duct", spec.trade, box,
            round(min(0.95, 0.68 + 0.03 * hr.n_ticks), 3), "grammar",
            f"{hr.length:.1f} pt spine crossed by {hr.n_ticks} hash marks at {hr.pitch:.2f} pt pitch",
            {"length_pt": round(hr.length, 2), "ticks": hr.n_ticks, "pitch_pt": round(hr.pitch, 2)},
        )
        kept.append(det)
        boxes.append(box)

    # --- Template propagation -------------------------------------------
    # Classification only sees a symbol when clustering managed to isolate it.
    # Wherever a diffuser is fused to the flex duct feeding it, the blob is too
    # big to recognise — and those are the majority on a busy sheet. So we take
    # each confidently classified instance, lift its clean geometry as a
    # template, and search the whole sheet for rigid copies of it. Since CAD
    # symbols are stamped from blocks, the copies are exact, and the recovered
    # instances inherit the seed's identity.
    if kept:
        from .matching import SheetGeometryIndex, build_template, clean_selection, find_instances

        geo = SheetGeometryIndex(prims)
        by_cat: dict[str, list[tuple[float, list[int], Detection]]] = collections.defaultdict(list)
        member_lookup = {tuple(sorted(ids)): ids for ids in candidates}
        for det in kept:
            box = det.bbox_pt
            ids = [
                i for i in index.query_box(box[0] - 0.3, box[1] - 0.3, box[2] + 0.3, box[3] + 0.3)
                if prims[i].bbox()[0] >= box[0] - 0.3 and prims[i].bbox()[2] <= box[2] + 0.3
                and prims[i].bbox()[1] >= box[1] - 0.3 and prims[i].bbox()[3] <= box[3] + 0.3
            ]
            if 2 <= len(ids) <= 200:
                by_cat[det.category_key].append((det.confidence, ids, det))

        for cat_key, seeds in by_cat.items():
            seeds.sort(key=lambda t: -t[0])
            spec = CATALOGUE.get(cat_key)
            if spec is None:
                continue
            seen_templates: set[str] = set()
            for conf, ids, seed in seeds[:4]:
                clean = clean_selection(prims, ids)
                if len(clean) < 3:
                    continue
                gid, _box = _canonical_signature(prims, clean)
                if gid in seen_templates:
                    continue
                seen_templates.add(gid)
                template = build_template(prims, clean, gid, 1)
                if template.n_segments < 3 or max(template.width_pt, template.height_pt) < 4:
                    continue
                try:
                    found = find_instances(template, prims, geo, min_score=0.9)
                except Exception:
                    continue
                for m in found:
                    box = list(m.bbox)
                    if any(bbox_iou(box, b) > 0.3 for b in boxes):
                        continue
                    det = Detection(
                        spec.name, cat_key, spec.trade, box,
                        round(min(0.97, conf * 0.97), 3), "template",
                        f"exact geometry match to a confirmed {spec.name} on this sheet "
                        f"({template.n_segments} strokes, {template.width_pt:.1f} x {template.height_pt:.1f} pt)",
                        {"glyph_id": gid, "seeded_by": seed.id, "shape_score": round(m.score, 3)},
                        glyph_id=gid,
                    )
                    kept.append(det)
                    boxes.append(box)

    glyphs = mine_glyphs(prims, max_glyph_pt=max_symbol_pt) if mine else []

    # Name mined glyphs from the library, and flag the ones the catalogue
    # already explains so the review queue stays short.
    for g in glyphs:
        entry = library.lookup(g.glyph_id) if library else None
        if entry:
            g.label = entry.get("label")
            g.trade = entry.get("trade")
            g.source = "library"
        explained = sum(1 for b in g.instances if any(bbox_iou(b, kb) > 0.4 for kb in boxes))
        if explained > len(g.instances) * 0.5:
            g.source = "explained"

    # Library-named glyphs that the catalogue rules missed are still real counts.
    for g in glyphs:
        if g.source != "library" or not g.label:
            continue
        spec = CATALOGUE_BY_NAME.get(g.label)
        for box in g.instances:
            if any(bbox_iou(box, b) > 0.35 for b in boxes):
                continue
            det = Detection(
                g.label, spec.key if spec else f"glyph:{g.glyph_id}",
                g.trade or (spec.trade if spec else ""), list(box), 0.97, "library",
                f"exact geometry match to the library entry '{g.label}'",
                {"glyph_id": g.glyph_id}, glyph_id=g.glyph_id,
            )
            kept.append(det)
            boxes.append(det.bbox_pt)

    for i, d in enumerate(kept, start=1):
        d.id = i
    return kept, glyphs


def summarise_counts(detections: Iterable[Detection]) -> list[dict]:
    agg: dict[str, dict] = {}
    for d in detections:
        if d.review == "rejected":
            continue
        row = agg.setdefault(
            d.category,
            {"category": d.category, "category_key": d.category_key, "trade": d.trade,
             "count": 0, "confidence_sum": 0.0, "detectors": collections.Counter()},
        )
        row["count"] += 1
        row["confidence_sum"] += d.confidence
        row["detectors"][d.detector] += 1
    out = []
    for row in agg.values():
        n = row.pop("confidence_sum")
        c = row["count"]
        row["mean_confidence"] = round(n / c, 3) if c else 0.0
        row["detectors"] = dict(row["detectors"])
        spec = CATALOGUE_BY_NAME.get(row["category"])
        row["category_group"] = spec.category if spec else "Discovered"
        row["unit"] = spec.unit if spec else "EA"
        out.append(row)
    return sorted(out, key=lambda r: -r["count"])
