"""
Exact geometric template matching.

Glyph mining (``symbols.mine_glyphs``) recovers a symbol's geometry cleanly
wherever the symbol happens to stand alone, but under-counts wherever it touches
something else — a diffuser fused to the flex duct feeding it becomes one big
blob and drops out of its class. That is the whole reason counts from naive
clustering come up short.

So mining is used only to *learn the template*, and this module then searches the
entire sheet for that template by geometric hashing. Because CAD symbols are
stamped from blocks, every instance is the same geometry under a rigid transform,
and the search is an exact match rather than a similarity score. That is what
makes the counts trustworthy: a match either is the symbol or it is not.
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import Sequence

from .geometry import UnionFind
from .pdfdoc import Primitive

# Rigid transforms considered: 4 quadrant rotations, optionally mirrored.
_ROTS = (0, 1, 2, 3)


@dataclass
class Template:
    """Symbol geometry normalised to its own bounding-box origin."""

    glyph_id: str
    segments: list[tuple[float, float, float, float, float]]  # dx0, dy0, dx1, dy1, width
    width_pt: float
    height_pt: float
    seed_count: int = 0
    label: str | None = None
    trade: str | None = None
    source: str = "mined"
    meta: dict = field(default_factory=dict)

    @property
    def n_segments(self) -> int:
        return len(self.segments)

    @property
    def ink(self) -> float:
        return sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in self.segments)

    def as_dict(self) -> dict:
        return {
            "glyph_id": self.glyph_id,
            "n_segments": self.n_segments,
            "width_pt": round(self.width_pt, 2),
            "height_pt": round(self.height_pt, 2),
            "seed_count": self.seed_count,
            "label": self.label,
            "trade": self.trade,
            "source": self.source,
            "segments": [[round(v, 3) for v in s] for s in self.segments],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Template":
        return cls(
            glyph_id=d["glyph_id"],
            segments=[tuple(s) for s in d["segments"]],  # type: ignore[misc]
            width_pt=d.get("width_pt", 0.0),
            height_pt=d.get("height_pt", 0.0),
            seed_count=d.get("seed_count", 0),
            label=d.get("label"),
            trade=d.get("trade"),
            source=d.get("source", "library"),
            meta=d.get("meta", {}),
        )

    def svg_path(self, scale: float = 1.0) -> str:
        """Tiny preview path so the UI can render the glyph next to its count."""
        parts = []
        for x0, y0, x1, y1, _w in self.segments:
            parts.append(f"M{x0 * scale:.2f},{y0 * scale:.2f}L{x1 * scale:.2f},{y1 * scale:.2f}")
        return "".join(parts)


def clean_selection(prims: Sequence[Primitive], ids: Sequence[int], gap: float = 0.8) -> list[int]:
    """
    Reduce a rectangular selection to the symbol it was drawn around.

    A box drawn over a diffuser also catches the duct stub feeding it and part
    of its tag — and those differ at every other instance, so a template built
    from the raw selection matches exactly once: the one it came from. Keeping
    only the largest connected piece of geometry gives back the symbol itself.
    """
    if len(ids) < 3:
        return list(ids)

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

    groups = uf.groups()
    if not groups:
        return list(ids)
    best = max(groups.values(), key=lambda members: sum(prims[ids[m]].length for m in members))
    return [ids[m] for m in best]


def build_template(prims: Sequence[Primitive], ids: Sequence[int], glyph_id: str, seed_count: int = 0) -> Template:
    xs: list[float] = []
    ys: list[float] = []
    for i in ids:
        p = prims[i]
        xs.extend((p.x0, p.x1))
        ys.extend((p.y0, p.y1))
    ox, oy = min(xs), min(ys)
    segs = []
    for i in ids:
        p = prims[i]
        segs.append((p.x0 - ox, p.y0 - oy, p.x1 - ox, p.y1 - oy, p.width))
    return Template(glyph_id, segs, max(xs) - ox, max(ys) - oy, seed_count)


# ---------------------------------------------------------------------------
# Sheet index
# ---------------------------------------------------------------------------


def _akey(dx: float, dy: float, q: float = 0.06) -> tuple[int, int]:
    """Direction-insensitive quantised vector key."""
    if (dx, dy) < (-dx, -dy):
        dx, dy = -dx, -dy
    return (int(round(dx / q)), int(round(dy / q)))


class SheetGeometryIndex:
    """
    Two indexes over a sheet's primitives:

    * ``by_shape`` — segments grouped by their (vector, width) signature. Used to
      pick a rare anchor so hypothesis generation stays cheap.
    * ``by_cell``  — segments grouped by quantised midpoint. Used to verify a
      hypothesised transform in O(1) per template segment.
    """

    def __init__(self, prims: Sequence[Primitive], cell: float = 2.0, tol: float = 0.18):
        self.prims = prims
        self.cell = cell
        self.tol = tol
        self.by_shape: dict[tuple[int, int, int], list[int]] = collections.defaultdict(list)
        self.by_cell: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        for i, p in enumerate(prims):
            if p.length < 1e-6:
                continue
            k = _akey(p.x1 - p.x0, p.y1 - p.y0)
            self.by_shape[(k[0], k[1], int(round(p.width * 50)))].append(i)
            mx, my = p.midpoint
            self.by_cell[(int(mx // cell), int(my // cell))].append(i)

    def shape_count(self, dx: float, dy: float, width: float) -> int:
        k = _akey(dx, dy)
        return len(self.by_shape.get((k[0], k[1], int(round(width * 50))), ()))

    def candidates_for(self, dx: float, dy: float, width: float) -> list[int]:
        k = _akey(dx, dy)
        return self.by_shape.get((k[0], k[1], int(round(width * 50))), [])

    def has_segment(self, x0: float, y0: float, x1: float, y1: float, width: float) -> bool:
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        c = self.cell
        gx, gy = int(mx // c), int(my // c)
        tol = self.tol
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                for i in self.by_cell.get((gx + ddx, gy + ddy), ()):
                    p = self.prims[i]
                    if abs(p.width - width) > 0.02:
                        continue
                    if (
                        abs(p.x0 - x0) <= tol and abs(p.y0 - y0) <= tol
                        and abs(p.x1 - x1) <= tol and abs(p.y1 - y1) <= tol
                    ) or (
                        abs(p.x0 - x1) <= tol and abs(p.y0 - y1) <= tol
                        and abs(p.x1 - x0) <= tol and abs(p.y1 - y0) <= tol
                    ):
                        return True
        return False

    def segment_ids_in(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        c = self.cell
        out: list[int] = []
        for gx in range(int(x0 // c), int(x1 // c) + 1):
            for gy in range(int(y0 // c), int(y1 // c) + 1):
                out.extend(self.by_cell.get((gx, gy), ()))
        return out


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------


def _rot(x: float, y: float, k: int, mirror: bool = False) -> tuple[float, float]:
    if mirror:
        x = -x
    if k == 0:
        return (x, y)
    if k == 1:
        return (-y, x)
    if k == 2:
        return (-x, -y)
    return (y, -x)


@dataclass
class Match:
    template: Template
    bbox: tuple[float, float, float, float]
    score: float
    rotation: int
    mirror: bool
    member_ids: list[int]


def find_instances(
    template: Template,
    prims: Sequence[Primitive],
    index: SheetGeometryIndex,
    min_score: float = 0.85,
    allow_mirror: bool = True,
    max_hypotheses: int = 60000,
) -> list[Match]:
    """Locate every rigid-transform instance of ``template`` on the sheet."""
    segs = template.segments
    if not segs:
        return []

    # Anchor on the template's most distinctive *long* segments. A single anchor
    # is fragile — if that one stroke is drawn slightly differently on some
    # instances, every one of them is missed. Trying the three rarest, longest
    # candidates and merging the results costs little and is far more robust.
    scored = sorted(
        range(len(segs)),
        key=lambda i: (
            index.shape_count(segs[i][2] - segs[i][0], segs[i][3] - segs[i][1], segs[i][4]),
            -math.hypot(segs[i][2] - segs[i][0], segs[i][3] - segs[i][1]),
        ),
    )
    long_enough = [i for i in scored if math.hypot(segs[i][2] - segs[i][0], segs[i][3] - segs[i][1]) >= 1.0]
    anchors = (long_enough or scored)[:3]

    rots = _ROTS
    mirrors = (False, True) if allow_mirror else (False,)

    seen_origins: set[tuple[int, int, int, int]] = set()
    matches: list[Match] = []
    hypotheses = 0
    need = max(1, int(math.ceil(len(segs) * min_score)))

    for anchor_i in anchors:
        ax0, ay0, ax1, ay1, aw = segs[anchor_i]
        adx, ady = ax1 - ax0, ay1 - ay0
        for mirror in mirrors:
            for k in rots:
                rdx, rdy = _rot(adx, ady, k, mirror)
                cands = index.candidates_for(rdx, rdy, aw)
                if not cands:
                    continue
                ra0 = _rot(ax0, ay0, k, mirror)
                _scan(cands, prims, index, segs, k, mirror, ra0, need, seen_origins, matches, template)

    return _collapse(matches, template)


def _scan(cands, prims, index, segs, k, mirror, ra0, need, seen_origins, matches, template,
          max_hypotheses: int = 60000) -> None:
    """Test every placement implied by the anchor landing on a candidate stroke."""
    for ci in cands:
        p = prims[ci]
        for (cx, cy) in ((p.x0, p.y0), (p.x1, p.y1)):
            # Translation that puts the template's anchor start onto this endpoint.
            tx, ty = cx - ra0[0], cy - ra0[1]
            okey = (k, int(mirror), int(round(tx / 0.25)), int(round(ty / 0.25)))
            if okey in seen_origins:
                continue
            seen_origins.add(okey)
            if len(seen_origins) > max_hypotheses:
                return

            hit = 0
            miss = 0
            xs: list[float] = []
            ys: list[float] = []
            for (sx0, sy0, sx1, sy1, sw) in segs:
                r0 = _rot(sx0, sy0, k, mirror)
                r1 = _rot(sx1, sy1, k, mirror)
                X0, Y0 = r0[0] + tx, r0[1] + ty
                X1, Y1 = r1[0] + tx, r1[1] + ty
                if index.has_segment(X0, Y0, X1, Y1, sw):
                    hit += 1
                    xs.extend((X0, X1))
                    ys.extend((Y0, Y1))
                else:
                    miss += 1
                    if miss > len(segs) - need:
                        break
            if hit < need:
                continue
            score = hit / len(segs)
            bx0, by0 = min(xs), min(ys)
            bx1, by1 = max(xs), max(ys)
            member = index.segment_ids_in(bx0 - 0.3, by0 - 0.3, bx1 + 0.3, by1 + 0.3)
            matches.append(Match(template, (bx0, by0, bx1, by1), score, k, mirror, member))


def _collapse(matches: list[Match], template: Template) -> list[Match]:
    """Collapse duplicate hits on the same spot (rotational symmetry of the glyph)."""
    matches.sort(key=lambda m: (-m.score, m.bbox))
    kept: list[Match] = []
    occupied: dict[tuple[int, int], list[Match]] = collections.defaultdict(list)
    cell = max(2.0, max(template.width_pt, template.height_pt) * 0.5)
    for m in matches:
        cx = (m.bbox[0] + m.bbox[2]) / 2
        cy = (m.bbox[1] + m.bbox[3]) / 2
        gx, gy = int(cx // cell), int(cy // cell)
        clash = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in occupied.get((gx + dx, gy + dy), ()):
                    ocx = (o.bbox[0] + o.bbox[2]) / 2
                    ocy = (o.bbox[1] + o.bbox[3]) / 2
                    if abs(ocx - cx) < max(1.0, template.width_pt * 0.4) and abs(ocy - cy) < max(1.0, template.height_pt * 0.4):
                        clash = True
                        break
                if clash:
                    break
            if clash:
                break
        if not clash:
            kept.append(m)
            occupied[(gx, gy)].append(m)
    return kept


def dedupe_templates(templates: Sequence[Template], min_segments: int = 2) -> list[Template]:
    """
    Drop templates that are strict sub-parts of a richer template.

    Mining naturally produces both "the square" and "the square plus its X",
    and counting both would double-count the same physical component.
    """
    def sig(t: Template) -> frozenset:
        out = set()
        for (x0, y0, x1, y1, w) in t.segments:
            a = (round(x0 / 0.1), round(y0 / 0.1))
            b = (round(x1 / 0.1), round(y1 / 0.1))
            out.add((min(a, b), max(a, b), round(w, 2)))
        return frozenset(out)

    ordered = sorted(templates, key=lambda t: (-t.n_segments, -t.seed_count))
    sigs = [sig(t) for t in ordered]
    keep: list[Template] = []
    keep_sigs: list[frozenset] = []
    for t, s in zip(ordered, sigs):
        if t.n_segments < min_segments:
            continue
        subsumed = False
        for ks in keep_sigs:
            if len(s) and len(s & ks) >= len(s) * 0.85:
                subsumed = True
                break
        if not subsumed:
            keep.append(t)
            keep_sigs.append(s)
    return keep
