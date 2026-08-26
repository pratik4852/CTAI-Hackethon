"""
Legend-driven shape classification.

The dataset's symbol catalogue defines each component in words — *"a square with
an 'X' inside"*, *"a square with a single diagonal"*, *"concentric circles"*. So
rather than learn what those look like from pixels, we **draw them from the
definition** and compare.

Every candidate blob of geometry is normalised into a small binary raster and
scored against the procedurally generated ideal symbols over the four quadrant
rotations and their mirrors. This survives the thing that breaks exact matching:
CAD exporters split one drawn square into four, eight or sixteen separate
operators depending on the publisher, and none of that changes the shape.

The score is a real, reportable quantity — the agreement between what is on the
sheet and what the legend says the symbol is — which is why the UI can say
"92% shape agreement with Square Supply Diffuser (4-Way)" instead of an
uninterpretable model logit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

import numpy as np

from .pdfdoc import Primitive

GRID = 40           #: raster resolution used for every comparison
PAD = 3             #: border so strokes on the edge are not clipped
STROKE = 2          #: stroke thickness in grid cells


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------


def _line(canvas: np.ndarray, x0: float, y0: float, x1: float, y1: float, thick: int = STROKE) -> None:
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 2
    h, w = canvas.shape
    r = thick // 2
    for i in range(n + 1):
        t = i / n
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w:
                    canvas[yy, xx] = 1.0


def _circle(canvas: np.ndarray, cx: float, cy: float, r: float, thick: int = STROKE, fill: bool = False) -> None:
    h, w = canvas.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    if fill:
        canvas[d <= r] = 1.0
    else:
        canvas[np.abs(d - r) <= thick / 2.0] = 1.0


def rasterise_blob(prims: Sequence[Primitive], ids: Sequence[int], grid: int = GRID) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Normalise a blob of primitives into a fixed-size binary raster."""
    xs: list[float] = []
    ys: list[float] = []
    for i in ids:
        p = prims[i]
        xs.extend((p.x0, p.x1))
        ys.extend((p.y0, p.y1))
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    w = max(x1 - x0, 1e-6)
    h = max(y1 - y0, 1e-6)
    span = max(w, h)
    inner = grid - 2 * PAD
    # Preserve aspect ratio: the longer side fills the box, the shorter is centred.
    sx = inner / span
    offx = PAD + (inner - w * sx) / 2.0
    offy = PAD + (inner - h * sx) / 2.0

    canvas = np.zeros((grid, grid), dtype=np.float32)
    for i in ids:
        p = prims[i]
        _line(
            canvas,
            (p.x0 - x0) * sx + offx, (p.y0 - y0) * sx + offy,
            (p.x1 - x0) * sx + offx, (p.y1 - y0) * sx + offy,
        )
    return canvas, (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# Ideal symbols, drawn from the catalogue's own descriptions
# ---------------------------------------------------------------------------


def _frame(canvas: np.ndarray, a: float, b: float) -> None:
    _line(canvas, a, a, b, a)
    _line(canvas, b, a, b, b)
    _line(canvas, b, b, a, b)
    _line(canvas, a, b, a, a)


@lru_cache(maxsize=1)
def ideal_symbols() -> dict[str, np.ndarray]:
    g = GRID
    a, b = float(PAD), float(g - PAD - 1)
    mid = (a + b) / 2.0
    side = b - a
    out: dict[str, np.ndarray] = {}

    # Square with an 'X' and a central circle -> 4-way supply diffuser
    c = np.zeros((g, g), np.float32)
    _frame(c, a, b)
    _line(c, a, a, b, b)
    _line(c, a, b, b, a)
    _circle(c, mid, mid, side * 0.17)
    out["square_supply_diffuser_4way"] = c

    # Square with an 'X' -> fire damper
    c = np.zeros((g, g), np.float32)
    _frame(c, a, b)
    _line(c, a, a, b, b)
    _line(c, a, b, b, a)
    out["fire_damper"] = c

    # Square with a single diagonal -> return / exhaust register
    c = np.zeros((g, g), np.float32)
    _frame(c, a, b)
    _line(c, a, b, b, a)
    out["square_return_exhaust_register"] = c

    # Concentric circles -> round supply diffuser
    c = np.zeros((g, g), np.float32)
    for f in (1.0, 0.66, 0.34):
        _circle(c, mid, mid, side / 2.0 * f)
    out["round_supply_diffuser"] = c

    # Rectangle with a solid diamond -> water source heat pump
    c = np.zeros((g, g), np.float32)
    _frame(c, a, b)
    q = side * 0.26
    pts = [(mid, mid - q), (mid + q, mid), (mid, mid + q), (mid - q, mid)]
    yy, xx = np.mgrid[0:g, 0:g]
    inside = (np.abs(xx - mid) / q + np.abs(yy - mid) / q) <= 1.0
    c[inside] = 1.0
    out["water_source_heat_pump"] = c

    # Long narrow rectangle with internal vane lines -> linear bar grille
    c = np.zeros((g, g), np.float32)
    top, bot = mid - side * 0.16, mid + side * 0.16
    _line(c, a, top, b, top)
    _line(c, b, top, b, bot)
    _line(c, b, bot, a, bot)
    _line(c, a, bot, a, top)
    _line(c, a, mid, b, mid)
    out["linear_bar_grille"] = c

    # Circle with alternating filled quadrants -> datum target
    c = np.zeros((g, g), np.float32)
    r = side / 2.0
    yy, xx = np.mgrid[0:g, 0:g]
    d = np.sqrt((xx - mid) ** 2 + (yy - mid) ** 2)
    quad = ((xx >= mid) ^ (yy >= mid))
    c[(d <= r) & quad] = 1.0
    _circle(c, mid, mid, r)
    out["elevation_benchmark"] = c

    return out


#: Shapes whose aspect ratio is part of their identity.
ASPECT_GATE: dict[str, tuple[float, float]] = {
    "square_supply_diffuser_4way": (0.70, 1.42),
    "fire_damper": (0.55, 1.85),
    "square_return_exhaust_register": (0.55, 1.85),
    "round_supply_diffuser": (0.80, 1.25),
    "water_source_heat_pump": (0.55, 2.20),
    "linear_bar_grille": (2.10, 40.0),
    "elevation_benchmark": (0.80, 1.25),
}


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _variants(t: np.ndarray) -> list[np.ndarray]:
    out = []
    seen: set[bytes] = set()
    for k in range(4):
        r = np.rot90(t, k)
        for m in (r, np.fliplr(r)):
            key = m.tobytes()
            if key in seen:
                continue
            seen.add(key)
            out.append(np.ascontiguousarray(m))
    return out


@lru_cache(maxsize=1)
def _ideal_variants() -> dict[str, list[np.ndarray]]:
    return {k: _variants(v) for k, v in ideal_symbols().items()}


def _dilate(a: np.ndarray, k: int = 1) -> np.ndarray:
    out = a.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out = np.maximum(out, np.roll(np.roll(a, dy, axis=0), dx, axis=1))
    return out


@lru_cache(maxsize=1)
def _ideal_stacks() -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """
    Pre-computed comparison tensors: (variants, dilated variants, ink counts).

    Scoring one candidate against the whole catalogue then becomes three
    vectorised reductions instead of ~60 Python-level array operations, which is
    the difference between a sheet taking a minute and taking a second.
    """
    out: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for key, variants in _ideal_variants().items():
        stack = np.stack([v > 0.5 for v in variants]).astype(bool)
        dil = np.stack([_dilate(v) > 0.5 for v in variants]).astype(bool)
        out[key] = (stack, dil, stack.reshape(stack.shape[0], -1).sum(axis=1).astype(np.float32))
    return out


def shape_score(blob: np.ndarray, ideal: np.ndarray) -> float:
    """
    Symmetric agreement between a candidate and an ideal symbol.

    Both directions matter: ``coverage`` catches a symbol missing a stroke, and
    ``cleanliness`` catches a blob that contains the symbol plus a lot else. A
    one-cell dilation absorbs rasterisation jitter without letting a wrong shape
    slip through.
    """
    bi = blob > 0.5
    ii = ideal > 0.5
    if not bi.any() or not ii.any():
        return 0.0
    bd = _dilate(bi.astype(np.float32)) > 0.5
    idl = _dilate(ii.astype(np.float32)) > 0.5
    coverage = float((ii & bd).sum()) / float(ii.sum())
    cleanliness = float((bi & idl).sum()) / float(bi.sum())
    return 2.0 * coverage * cleanliness / max(1e-9, coverage + cleanliness)


@dataclass
class ShapeMatch:
    key: str
    score: float
    coverage: float
    cleanliness: float


#: Per-symbol acceptance thresholds and minimum drawn size in points.
#: Shapes with little information content (a square plus one line) have to clear
#: a higher bar than distinctive ones, or they swallow every arrowhead on the
#: sheet.
ACCEPT: dict[str, tuple[float, float, int]] = {
    # key: (min_score, min_longest_side_pt, min_segments)
    "square_supply_diffuser_4way": (0.72, 5.0, 4),
    "fire_damper": (0.74, 5.0, 4),
    "square_return_exhaust_register": (0.80, 5.0, 3),
    "round_supply_diffuser": (0.74, 5.0, 4),
    "water_source_heat_pump": (0.72, 6.0, 4),
    "linear_bar_grille": (0.87, 12.0, 6),
    "elevation_benchmark": (0.76, 5.0, 6),
}


#: The three square-face symbols differ by one feature each, so a global raster
#: score cannot separate them reliably — the deciding evidence is a handful of
#: pixels. These are resolved structurally instead.
SQUARE_FAMILY = ("square_supply_diffuser_4way", "fire_damper", "square_return_exhaust_register")


def _square_family_features(prims: Sequence[Primitive], ids: Sequence[int]) -> tuple[int, bool]:
    """(number of diagonal directions present, central circle present)."""
    xs: list[float] = []
    ys: list[float] = []
    for i in ids:
        p = prims[i]
        xs.extend((p.x0, p.x1))
        ys.extend((p.y0, p.y1))
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    side = max(x1 - x0, y1 - y0)
    if side <= 0:
        return 0, False

    # A diagonal runs corner-to-corner, so its direction matches the box's own
    # diagonal and it passes close to the centre.
    down = math.atan2(y1 - y0, x1 - x0) % math.pi   # top-left -> bottom-right
    up = math.atan2(y0 - y1, x1 - x0) % math.pi     # bottom-left -> top-right
    seen_down = seen_up = False
    ring_pts: list[float] = []
    for i in ids:
        p = prims[i]
        if p.length < side * 0.25:
            # Candidate neck-circle geometry: short strokes near the middle.
            # Publishers draw the neck as bezier chords, a small polygon or a
            # filled dot, so we test the *shape* they form rather than the
            # operator used — a real circle puts its points on a ring.
            for (px, py) in ((p.x0, p.y0), (p.x1, p.y1)):
                r = math.hypot(px - cx, py - cy)
                if r <= side * 0.35:
                    ring_pts.append(r)
            continue
        ang = p.angle
        d_down = min(abs(ang - down), math.pi - abs(ang - down))
        d_up = min(abs(ang - up), math.pi - abs(ang - up))
        if min(d_down, d_up) > 0.22:
            continue
        # Must actually cross the middle third of the box.
        mx, my = p.midpoint
        if math.hypot(mx - cx, my - cy) > side * 0.55:
            continue
        if d_down <= d_up:
            seen_down = True
        else:
            seen_up = True

    n_diag = int(seen_down) + int(seen_up)

    has_circle = False
    if len(ring_pts) >= 6:
        mean_r = sum(ring_pts) / len(ring_pts)
        if side * 0.05 <= mean_r <= side * 0.30:
            spread = math.sqrt(sum((r - mean_r) ** 2 for r in ring_pts) / len(ring_pts))
            has_circle = spread <= mean_r * 0.30

    return n_diag, has_circle


def classify_blob(
    prims: Sequence[Primitive],
    ids: Sequence[int],
    min_score: float | None = None,
) -> ShapeMatch | None:
    """Identify a blob of geometry as one of the catalogue symbols."""
    if len(ids) < 2:
        return None
    canvas, box = rasterise_blob(prims, ids)
    w = max(box[2] - box[0], 1e-6)
    h = max(box[3] - box[1], 1e-6)
    aspect = w / h
    longest = max(w, h)

    has_fill = any(prims[i].fill for i in ids)

    bi = canvas > 0.5
    b_ink = float(bi.sum())
    if b_ink < 1.0:
        return None
    bd = _dilate(canvas) > 0.5

    best: ShapeMatch | None = None
    for key, (stack, dil, ink) in _ideal_stacks().items():
        lo, hi = ASPECT_GATE.get(key, (0.0, 1e9))
        if not (lo <= aspect <= hi or lo <= 1.0 / aspect <= hi):
            continue
        floor, min_side, min_seg = ACCEPT.get(key, (0.72, 4.0, 3))
        if longest < min_side or len(ids) < min_seg:
            continue
        # The legend defines these two by a *solid* element; without any filled
        # geometry the candidate is a different symbol wearing a similar outline.
        if key in ("water_source_heat_pump", "elevation_benchmark") and not has_fill:
            continue

        n = stack.shape[0]
        cov = (stack & bd).reshape(n, -1).sum(axis=1).astype(np.float32) / np.maximum(ink, 1.0)
        cln = (dil & bi).reshape(n, -1).sum(axis=1).astype(np.float32) / b_ink
        f1 = 2.0 * cov * cln / np.maximum(cov + cln, 1e-9)
        k = int(np.argmax(f1))
        if best is None or float(f1[k]) > best.score:
            best = ShapeMatch(key, float(f1[k]), float(cov[k]), float(cln[k]))

    if best is None:
        return None

    if best.key in SQUARE_FAMILY:
        n_diag, has_circle = _square_family_features(prims, ids)
        if n_diag >= 2:
            resolved = "square_supply_diffuser_4way" if has_circle else "fire_damper"
        elif n_diag == 1:
            resolved = "square_return_exhaust_register"
        else:
            # A bare square is not a component; it is a box.
            return None
        if resolved != best.key:
            stack, dil, ink = _ideal_stacks()[resolved]
            n = stack.shape[0]
            cov = (stack & bd).reshape(n, -1).sum(axis=1).astype(np.float32) / np.maximum(ink, 1.0)
            cln = (dil & bi).reshape(n, -1).sum(axis=1).astype(np.float32) / b_ink
            f1 = 2.0 * cov * cln / np.maximum(cov + cln, 1e-9)
            k = int(np.argmax(f1))
            best = ShapeMatch(resolved, max(float(f1[k]), best.score - 0.06), float(cov[k]), float(cln[k]))

    floor = min_score if min_score is not None else ACCEPT.get(best.key, (0.72, 0, 0))[0]
    return best if best.score >= floor else None


# ---------------------------------------------------------------------------
# Candidate assembly
# ---------------------------------------------------------------------------


def _blob_box(prims: Sequence[Primitive], ids: Sequence[int]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for i in ids:
        p = prims[i]
        xs.extend((p.x0, p.x1))
        ys.extend((p.y0, p.y1))
    return (min(xs), min(ys), max(xs), max(ys))


def merge_overlapping_blobs(
    prims: Sequence[Primitive],
    blobs: Sequence[Sequence[int]],
    max_size_pt: float = 90.0,
    pad: float = 0.4,
) -> list[list[int]]:
    """
    Rebuild whole symbols from their pieces.

    A fire damper is a square, two diagonals and a heavy barrier line. Depending
    on how the exporter ordered the content stream those can land in two, three
    or four separate blobs that merely *overlap* rather than touch — which is
    why clustering alone reports one square with a single diagonal instead of a
    square with an X. Overlapping bounding boxes are the missing link.
    """
    from .geometry import UnionFind

    boxes = [_blob_box(prims, b) for b in blobs]
    n = len(blobs)
    uf = UnionFind(n)

    cell = 24.0
    grid: dict[tuple[int, int], list[int]] = {}
    for i, b in enumerate(boxes):
        for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
            for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)

    for ids in grid.values():
        for ii in range(len(ids)):
            i = ids[ii]
            bi = boxes[i]
            for jj in range(ii + 1, len(ids)):
                j = ids[jj]
                bj = boxes[j]
                if bi[2] + pad < bj[0] or bj[2] + pad < bi[0] or bi[3] + pad < bj[1] or bj[3] + pad < bi[1]:
                    continue
                ux = max(bi[2], bj[2]) - min(bi[0], bj[0])
                uy = max(bi[3], bj[3]) - min(bi[1], bj[1])
                if ux > max_size_pt or uy > max_size_pt:
                    continue
                # Only fuse pieces that genuinely sit on top of each other, not
                # neighbours that happen to abut.
                ix = min(bi[2], bj[2]) - max(bi[0], bj[0])
                iy = min(bi[3], bj[3]) - max(bi[1], bj[1])
                if ix < -pad or iy < -pad:
                    continue
                inter = max(0.0, ix) * max(0.0, iy)
                area_i = max(1e-6, (bi[2] - bi[0]) * (bi[3] - bi[1]))
                area_j = max(1e-6, (bj[2] - bj[0]) * (bj[3] - bj[1]))
                if inter / min(area_i, area_j) < 0.55:
                    continue
                uf.union(i, j)

    out: list[list[int]] = []
    for _root, members in uf.groups().items():
        merged: list[int] = []
        for m in members:
            merged.extend(blobs[m])
        out.append(merged)
    return out


def absorb_contained(
    prims: Sequence[Primitive],
    group: Sequence[int],
    index,
    pad: float = 0.35,
) -> list[int]:
    """
    Pull in every primitive that lies wholly inside the candidate's bounds.

    Clustering deliberately ignores long segments so that symbols do not fuse
    into the duct network — but an 18 pt square's own diagonal is 25 pt, so that
    same cut-off throws away the 'X' that distinguishes a fire damper from a
    plain return register. Absorbing *contained* geometry restores it while
    still rejecting the duct running past, because a duct extends beyond the
    box.
    """
    x0, y0, x1, y1 = _blob_box(prims, group)
    out = set(group)
    for i in index.query_box(x0 - pad, y0 - pad, x1 + pad, y1 + pad):
        if i in out:
            continue
        b = prims[i].bbox()
        if b[0] >= x0 - pad and b[1] >= y0 - pad and b[2] <= x1 + pad and b[3] <= y1 + pad:
            out.add(i)
    return sorted(out)


def build_candidates(
    prims: Sequence[Primitive],
    blobs: Sequence[Sequence[int]],
    max_size_pt: float = 90.0,
    max_segments: int = 60,
    index=None,
) -> list[list[int]]:
    """Candidate symbol regions: merged groups and raw blobs, each completed."""
    from .geometry import SegmentIndex

    if index is None:
        index = SegmentIndex(prims, cell=24.0)

    merged = merge_overlapping_blobs(prims, blobs, max_size_pt)
    seen: set[tuple[int, ...]] = set()
    out: list[list[int]] = []
    for group in list(merged) + [list(b) for b in blobs]:
        if not (2 <= len(group) <= max_segments):
            continue
        box = _blob_box(prims, group)
        if (box[2] - box[0]) > max_size_pt or (box[3] - box[1]) > max_size_pt:
            continue
        for variant in (group, absorb_contained(prims, group, index)):
            if not (2 <= len(variant) <= max_segments):
                continue
            key = tuple(sorted(variant))
            if key in seen:
                continue
            seen.add(key)
            out.append(list(variant))
    return out
