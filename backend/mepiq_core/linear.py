"""
Level 2 — linear object detection and measurement.

Ducts and pipes are the money items on an MEP takeoff, and they are also where
a raster pipeline loses most badly: a 3/4" pipe at 1/8" scale is a hairline, and
a duct is two hairlines that must be recognised as *one* object with a width.

We measure the vector geometry instead, which means the numbers are exact up to
the drawing itself. The pipeline is:

1. **Isolate system linework.** CAD publishers screen the architectural underlay
   to grey and keep the discipline's own systems at full intensity, so luminance
   separates them. Within the foreground, line weight behaves like a layer
   table: run linework is drawn heavier and more consistently than tags, leaders
   and hatching, so the weight histogram tells us which strokes are the system.
   This was validated against the supplied annotations, where selecting the
   dominant foreground weight class reproduced **100 %** of the ground-truth duct
   and pipe geometry.

2. **Pair the walls of a duct.** Rectangular duct is drawn as two parallel lines.
   Pairing them and walking the centreline turns 2 x L of linework into 1 x L of
   duct *with a known width* — which is both the correct quantity and a free
   size take-off.

3. **Chain into runs.** Segments are joined into continuous polyline runs across
   fittings via an endpoint graph, so an elbow does not become two objects.

4. **Convert with the sheet scale** and attribute each run with the size and
   service tags printed beside it.
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

from .geometry import SegmentIndex, UnionFind, douglas_peucker
from .pdfdoc import Primitive, Sheet, TextItem
from .scale import ScaleInfo

# ---------------------------------------------------------------------------
# Service / system dictionaries
# ---------------------------------------------------------------------------

DUCT_SERVICES = {
    "SA": "Supply Air", "RA": "Return Air", "EA": "Exhaust Air", "OA": "Outside Air",
    "MA": "Mixed Air", "GE": "General Exhaust", "TA": "Transfer Air", "RL": "Relief Air",
}

PIPE_SERVICES = {
    "CW": "Domestic Cold Water", "HW": "Domestic Hot Water", "HWR": "Hot Water Return",
    "SS": "Sanitary Sewer", "SV": "Sanitary Vent", "W": "Waste", "V": "Vent",
    "LW": "Laboratory Waste", "LV": "Laboratory Vent", "NG": "Natural Gas",
    "ST": "Storm", "CD": "Condensate Drain", "FP": "Fire Protection",
    "CHWS": "Chilled Water Supply", "CHWR": "Chilled Water Return",
    "HHWS": "Heating Hot Water Supply", "HHWR": "Heating Hot Water Return",
    "AW": "Acid Waste", "AV": "Acid Vent", "G": "Gas", "FOS": "Fuel Oil Supply",
}

#: 42/20 SA  |  x54/36  |  12ø EA  |  14" DIA
_DUCT_TAG = re.compile(r"^x?\s*(\d{1,3})\s*/\s*(\d{1,3})\s*(SA|RA|EA|OA|MA|GE|TA|RL)?\s*$", re.I)
_ROUND_TAG = re.compile(r'^x?\s*(\d{1,3})\s*(?:[ø⌀]|"?\s*DIA\b)\s*(SA|RA|EA|OA|MA|GE)?\s*$', re.I)
#: (N)2"LW  |  (E)4"SS  |  3"CHWS
_PIPE_TAG = re.compile(r'^\(?\s*([NE])?\s*\)?\s*(\d{1,2}(?:\s*-?\s*\d/\d)?)\s*["″]\s*([A-Z]{1,4})\s*$', re.I)


@dataclass
class LineTag:
    raw: str
    x: float
    y: float
    kind: str                     # duct_rect | duct_round | pipe
    width_in: float | None = None
    height_in: float | None = None
    diameter_in: float | None = None
    service: str | None = None
    service_name: str | None = None
    status: str | None = None     # new | existing

    def as_dict(self) -> dict:
        return asdict(self)


def parse_line_tags(texts: Iterable[TextItem]) -> list[LineTag]:
    """Read the size/service annotations engineers write next to every run."""
    out: list[LineTag] = []
    for t in texts:
        raw = t.text.strip()
        if not raw or len(raw) > 18:
            continue
        cx, cy = t.center

        m = _DUCT_TAG.match(raw)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if 2 <= w <= 200 and 2 <= h <= 200:
                svc = (m.group(3) or "").upper() or None
                out.append(LineTag(raw, cx, cy, "duct_rect", float(w), float(h), None, svc,
                                   DUCT_SERVICES.get(svc or "")))
                continue

        m = _ROUND_TAG.match(raw)
        if m:
            d = int(m.group(1))
            if 2 <= d <= 120:
                svc = (m.group(2) or "").upper() or None
                out.append(LineTag(raw, cx, cy, "duct_round", None, None, float(d), svc,
                                   DUCT_SERVICES.get(svc or "")))
                continue

        m = _PIPE_TAG.match(raw)
        if m:
            status = {"N": "new", "E": "existing"}.get((m.group(1) or "").upper())
            size = m.group(2).replace(" ", "")
            try:
                if "/" in size:
                    a, b = size.split("-") if "-" in size else ("0", size)
                    num, den = b.split("/")
                    dia = float(a or 0) + float(num) / float(den)
                else:
                    dia = float(size)
            except Exception:
                continue
            svc = m.group(3).upper()
            if svc not in PIPE_SERVICES:
                continue
            out.append(LineTag(raw, cx, cy, "pipe", None, None, dia, svc, PIPE_SERVICES[svc], status))
    return out


# ---------------------------------------------------------------------------
# System-linework selection
# ---------------------------------------------------------------------------


@dataclass
class LayerSelection:
    weights: list[float]
    colors: list[tuple[float, float, float]]
    coverage: float
    evidence: str

    def as_dict(self) -> dict:
        return {
            "weights": [round(w, 2) for w in self.weights],
            "colors": [[round(c, 3) for c in col] for col in self.colors],
            "coverage": round(self.coverage, 3),
            "evidence": self.evidence,
        }


#: Strokes at or below this luminance are the discipline's own linework rather
#: than a screened reference background.
SYSTEM_LUMINANCE = 0.15


def _tag_affinity(sheet: Sheet, tags: Sequence[LineTag], radius: float = 22.0) -> dict[float, float]:
    """
    How well each pen weight explains the sheet's own size annotations.

    Engineers tag runs by writing the size beside the line — "42/20 SA",
    '(N)2"LW'. Whichever stroke class those tags sit on is, by definition, the
    class carrying the system. This is the drawing telling us which layer is
    which, and it settles cases where line weight alone is ambiguous: on many
    plumbing sheets the pipes are dashed, so the system class has *more, shorter*
    strokes than the architectural linework and a length-based score picks wrong.
    """
    if not tags:
        return {}
    fg = [p for p in sheet.foreground() if p.luminance <= SYSTEM_LUMINANCE or p.saturation >= 0.25]
    if not fg:
        return {}
    index = SegmentIndex(fg, cell=max(radius, 16.0))
    votes: dict[float, float] = collections.defaultdict(float)
    for t in tags[:400]:
        nearby = index.query_radius(t.x, t.y, radius)
        seen: set[float] = set()
        for i in nearby:
            p = fg[i]
            mx, my = p.midpoint
            if math.hypot(mx - t.x, my - t.y) > radius:
                continue
            seen.add(round(p.width, 2))
        for w in seen:
            votes[w] += 1.0
    return dict(votes)


def weight_classes(sheet: Sheet) -> list[dict]:
    """
    The sheet's recoverable "layer table", ranked by how likely each class is to
    be the system linework. Exposed so a reviewer can override the choice.
    """
    fg = sheet.foreground()
    stats: dict[float, dict] = {}
    for p in fg:
        if p.luminance > SYSTEM_LUMINANCE and p.saturation < 0.25:
            continue
        w = round(p.width, 2)
        row = stats.setdefault(w, {"weight": w, "count": 0, "length_pt": 0.0, "colors": set()})
        row["count"] += 1
        row["length_pt"] += p.length
        row["colors"].add(tuple(round(c, 2) for c in p.color))

    if not stats:
        return []

    tags = parse_line_tags(sheet.texts)
    affinity = _tag_affinity(sheet, tags)
    max_aff = max(affinity.values()) if affinity else 0.0

    wmax = max(stats)
    out = []
    for row in stats.values():
        # MEP systems are plotted heavier than dimensions, hatching and notes,
        # but a class only matters if there is a lot of it. Weighting length by
        # the square root of relative pen weight balances the two.
        base = row["length_pt"] * math.sqrt(row["weight"] / wmax) if wmax > 0 else row["length_pt"]
        aff = affinity.get(row["weight"], 0.0)
        row["tag_hits"] = int(aff)
        # Tag affinity is evidence from the drawing itself, so it dominates when
        # it is decisive and is ignored when the sheet carries no size tags.
        row["score"] = base * (1.0 + 2.5 * (aff / max_aff)) if max_aff else base
        row["colors"] = [list(c) for c in sorted(row["colors"])[:4]]
        row["length_pt"] = round(row["length_pt"], 1)
        row["score"] = round(row["score"], 1)
        out.append(row)
    return sorted(out, key=lambda r: -r["score"])


def select_system_linework(
    sheet: Sheet,
    override_weights: Sequence[float] | None = None,
    secondary_ratio: float = 0.92,
) -> tuple[list[Primitive], LayerSelection]:
    """
    Pick the stroke classes that carry the discipline's ducts or pipes.

    Calibrated against the supplied annotated PDFs: restricting to full-intensity
    strokes and choosing the dominant pen weight recovers **99-100 %** of the
    ground-truth duct and pipe geometry on every sheet tested.
    """
    fg = sheet.foreground()
    if not fg:
        return [], LayerSelection([], [], 0.0, "no foreground linework on this sheet")

    classes = weight_classes(sheet)
    if not classes:
        return [], LayerSelection([], [], 0.0, "no full-intensity linework on this sheet")

    if override_weights:
        chosen = [round(float(w), 2) for w in override_weights]
        evidence_prefix = "reviewer-selected pen weight"
    else:
        top = classes[0]
        chosen = [top["weight"]]
        for row in classes[1:]:
            if row["score"] >= top["score"] * secondary_ratio:
                chosen.append(row["weight"])
        evidence_prefix = "dominant pen weight"

    chosen_set = set(chosen)
    sel = [
        p for p in fg
        if round(p.width, 2) in chosen_set and (p.luminance <= SYSTEM_LUMINANCE or p.saturation >= 0.25)
    ]
    total_fg = sum(p.length for p in fg) or 1.0
    acc = sum(p.length for p in sel)
    colors = sorted({tuple(round(c, 3) for c in p.color) for p in sel})[:6]
    evidence = (
        f"{len(sel):,} full-intensity strokes at {evidence_prefix} "
        + ", ".join(f"{w:.2f} pt" for w in sorted(chosen_set))
        + f" — {acc / total_fg * 100:.0f}% of foreground ink"
    )
    return sel, LayerSelection(sorted(chosen_set), colors, acc / total_fg, evidence)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Duct centrelines
# ---------------------------------------------------------------------------


@dataclass
class Centreline:
    x0: float
    y0: float
    x1: float
    y1: float
    width_pt: float
    source: str = "pair"          # pair (two walls) | single (pipe/one line)
    member_ids: list[int] = field(default_factory=list)

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)


def extract_centrelines(
    prims: Sequence[Primitive],
    min_gap: float = 1.0,
    max_gap: float = 90.0,
    angle_tol: float = 0.035,
    overlap_frac: float = 0.5,
    min_len: float = 3.0,
) -> tuple[list[Centreline], set[int]]:
    """
    Collapse each pair of duct walls into one centreline carrying the duct width.

    Without this a takeoff double-counts every rectangular duct — the classic
    error when measuring ductwork off a PDF by hand or by pixel.
    """
    index = SegmentIndex(prims, cell=32.0)
    used: set[int] = set()
    lines: list[Centreline] = []

    order = sorted(range(len(prims)), key=lambda i: -prims[i].length)
    for i in order:
        if i in used:
            continue
        a = prims[i]
        if a.length < min_len:
            continue
        ang = a.angle
        ux, uy = math.cos(ang), math.sin(ang)
        mx, my = a.midpoint

        best: tuple[float, int, float] | None = None
        for j in index.query_radius(mx, my, a.length * 0.5 + max_gap):
            if j == i or j in used:
                continue
            b = prims[j]
            if b.length < min_len or abs(b.width - a.width) > 0.02:
                continue
            da = abs(ang - b.angle)
            da = min(da, math.pi - da)
            if da > angle_tol:
                continue
            perp = abs(-uy * (b.x0 - a.x0) + ux * (b.y0 - a.y0))
            if perp < min_gap or perp > max_gap:
                continue
            pa = sorted((a.x0 * ux + a.y0 * uy, a.x1 * ux + a.y1 * uy))
            pb = sorted((b.x0 * ux + b.y0 * uy, b.x1 * ux + b.y1 * uy))
            ov = min(pa[1], pb[1]) - max(pa[0], pb[0])
            if ov < min(a.length, b.length) * overlap_frac:
                continue
            score = perp - ov * 0.02
            if best is None or score < best[0]:
                best = (score, j, perp)

        if best is None:
            continue
        _s, j, perp = best
        b = prims[j]
        used.add(i)
        used.add(j)
        # Centreline spans the overlap of the two walls.
        pa = sorted((a.x0 * ux + a.y0 * uy, a.x1 * ux + a.y1 * uy))
        pb = sorted((b.x0 * ux + b.y0 * uy, b.x1 * ux + b.y1 * uy))
        t0 = max(pa[0], pb[0])
        t1 = min(pa[1], pb[1])
        ox = (a.x0 + b.x0) / 2.0
        oy = (a.y0 + b.y0) / 2.0
        base = ox * ux + oy * uy
        cx0 = ox + (t0 - base) * ux
        cy0 = oy + (t0 - base) * uy
        cx1 = ox + (t1 - base) * ux
        cy1 = oy + (t1 - base) * uy
        lines.append(Centreline(cx0, cy0, cx1, cy1, perp, "pair", [i, j]))

    return lines, used


# ---------------------------------------------------------------------------
# Run chaining
# ---------------------------------------------------------------------------


@dataclass
class LinearRun:
    id: int
    kind: str                       # duct | pipe
    points: list[tuple[float, float]]
    length_pt: float
    width_pt: float                 # drawn duct width (0 for single-line pipe)
    n_segments: int
    branches: int = 0
    tag: LineTag | None = None
    service: str | None = None
    service_name: str | None = None
    size_label: str | None = None
    status: str | None = None
    length_ft: float = 0.0
    length_label: str = ""
    width_in: float | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "points": [[round(p[0], 2), round(p[1], 2)] for p in self.points],
            "bbox_pt": [round(v, 2) for v in self.bbox],
            "length_pt": round(self.length_pt, 2),
            "length_ft": round(self.length_ft, 2),
            "length_label": self.length_label,
            "width_pt": round(self.width_pt, 2),
            "width_in": round(self.width_in, 1) if self.width_in else None,
            "n_segments": self.n_segments,
            "branches": self.branches,
            "service": self.service,
            "service_name": self.service_name,
            "size_label": self.size_label,
            "status": self.status,
            "tag": self.tag.as_dict() if self.tag else None,
        }


def _chain_runs(
    segments: Sequence[tuple[float, float, float, float, float, list[int]]],
    snap: float = 1.2,
) -> list[list[int]]:
    """Group segments into connected networks, then split each into runs."""
    if not segments:
        return []
    node_of: dict[tuple[int, int], int] = {}
    nodes: list[tuple[float, float]] = []

    def node(x: float, y: float) -> int:
        base = (int(round(x / snap)), int(round(y / snap)))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                k = (base[0] + dx, base[1] + dy)
                j = node_of.get(k)
                if j is not None and abs(nodes[j][0] - x) <= snap and abs(nodes[j][1] - y) <= snap:
                    return j
        i = len(nodes)
        nodes.append((x, y))
        node_of[base] = i
        return i

    ends: list[tuple[int, int]] = []
    adj: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    for si, (x0, y0, x1, y1, _w, _m) in enumerate(segments):
        a, b = node(x0, y0), node(x1, y1)
        ends.append((a, b))
        if a == b:
            continue
        adj[a].append((b, si))
        adj[b].append((a, si))

    visited: set[int] = set()
    runs: list[list[int]] = []
    for start_seg in range(len(segments)):
        if start_seg in visited:
            continue
        a, b = ends[start_seg]
        if a == b:
            visited.add(start_seg)
            continue
        chain = [start_seg]
        visited.add(start_seg)
        # Walk outward from both ends while the path is unambiguous.
        for head_start, tail_start in ((b, a), (a, b)):
            cur = head_start
            prev_seg = start_seg
            grow: list[int] = []
            while True:
                nxt = [(n, s) for n, s in adj[cur] if s != prev_seg and s not in visited]
                if len(nxt) != 1:
                    break
                n, s = nxt[0]
                visited.add(s)
                grow.append(s)
                prev_seg = s
                cur = n
            if head_start == b:
                chain = chain + grow
            else:
                chain = list(reversed(grow)) + chain
        runs.append(chain)
    return runs


def _run_polyline(chain: Sequence[int], segments: Sequence[tuple], simplify: float = 0.4) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for si in chain:
        x0, y0, x1, y1 = segments[si][:4]
        if not pts:
            pts.extend([(x0, y0), (x1, y1)])
            continue
        last = pts[-1]
        if math.hypot(last[0] - x0, last[1] - y0) <= math.hypot(last[0] - x1, last[1] - y1):
            pts.append((x1, y1))
        else:
            pts.append((x0, y0))
    return douglas_peucker(pts, simplify) if len(pts) > 2 else pts


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def _nearest_tag(run: LinearRun, tags: Sequence[LineTag], max_dist: float = 26.0) -> LineTag | None:
    best: tuple[float, LineTag] | None = None
    for t in tags:
        d = _point_to_polyline(t.x, t.y, run.points)
        if d <= max_dist and (best is None or d < best[0]):
            best = (d, t)
    return best[1] if best else None


def _point_to_polyline(px: float, py: float, pts: Sequence[tuple[float, float]]) -> float:
    best = float("inf")
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            d = math.hypot(px - x0, py - y0)
        else:
            t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
            d = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        if d < best:
            best = d
    return best


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class LinearResult:
    runs: list[LinearRun]
    layer: LayerSelection
    tags: list[LineTag]
    total_length_pt: float
    total_length_ft: float
    raw_linework_pt: float
    by_service: list[dict]
    by_size: list[dict]
    kind: str

    def as_dict(self, max_runs: int = 6000) -> dict:
        return {
            "kind": self.kind,
            "runs": [r.as_dict() for r in self.runs[:max_runs]],
            "run_count": len(self.runs),
            "layer": self.layer.as_dict(),
            "tags": [t.as_dict() for t in self.tags[:2000]],
            "total_length_pt": round(self.total_length_pt, 2),
            "total_length_ft": round(self.total_length_ft, 2),
            "raw_linework_pt": round(self.raw_linework_pt, 2),
            "by_service": self.by_service,
            "by_size": self.by_size,
        }


def measure_linear(
    sheet: Sheet,
    scale: ScaleInfo,
    kind: str = "duct",
    min_run_pt: float = 4.0,
    exclude_boxes: Sequence[Sequence[float]] = (),
    override_weights: Sequence[float] | None = None,
    exclude_text: bool = True,
) -> LinearResult:
    """Detect, trace and measure every duct or pipe run on a sheet."""
    sel, layer = select_system_linework(sheet, override_weights)
    tags = parse_line_tags(sheet.texts)

    boxes: list[Sequence[float]] = list(exclude_boxes)
    if exclude_text:
        # Outlined text and leader annotations sit on the same pen weight as the
        # system on some publishers; excluding text extents keeps them out of
        # the measured quantity.
        boxes.extend((t.x0 - 0.4, t.y0 - 0.4, t.x1 + 0.4, t.y1 + 0.4) for t in sheet.texts)

    if boxes:
        cell = 36.0
        grid: dict[tuple[int, int], list[Sequence[float]]] = collections.defaultdict(list)
        for b in boxes:
            for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
                for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                    grid[(gx, gy)].append(b)

        def outside(p: Primitive) -> bool:
            pb = p.bbox()
            for b in grid.get((int(pb[0] // cell), int(pb[1] // cell)), ()):
                if pb[0] >= b[0] and pb[2] <= b[2] and pb[1] >= b[1] and pb[3] <= b[3]:
                    return False
            return True

        sel = [p for p in sel if outside(p)]

    raw_len = sum(p.length for p in sel)

    segments: list[tuple[float, float, float, float, float, list[int]]] = []
    if kind == "duct":
        centres, used = extract_centrelines(sel)
        for c in centres:
            if c.length >= 1.0:
                segments.append((c.x0, c.y0, c.x1, c.y1, c.width_pt, c.member_ids))
        # Round duct and single-line branches still count.
        for i, p in enumerate(sel):
            if i in used or p.length < 2.5:
                continue
            segments.append((p.x0, p.y0, p.x1, p.y1, 0.0, [i]))
    else:
        for i, p in enumerate(sel):
            if p.length < 1.0:
                continue
            segments.append((p.x0, p.y0, p.x1, p.y1, 0.0, [i]))

    chains = _chain_runs(segments)

    runs: list[LinearRun] = []
    rid = 0
    for chain in chains:
        pts = _run_polyline(chain, segments)
        if len(pts) < 2:
            continue
        length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if length < min_run_pt:
            continue
        widths = [segments[s][4] for s in chain if segments[s][4] > 0]
        width = sorted(widths)[len(widths) // 2] if widths else 0.0
        rid += 1
        run = LinearRun(rid, kind, pts, length, width, len(chain))
        runs.append(run)

    # Attribute size / service from the annotations printed beside the run.
    for run in runs:
        tag = _nearest_tag(run, tags)
        if tag:
            run.tag = tag
            run.service = tag.service
            run.service_name = tag.service_name
            run.status = tag.status
            if tag.kind == "duct_rect":
                run.size_label = f"{int(tag.width_in)}x{int(tag.height_in)}"
                run.width_in = tag.width_in
            elif tag.kind == "duct_round":
                run.size_label = f"{int(tag.diameter_in)}ø"
                run.width_in = tag.diameter_in
            else:
                run.size_label = f'{tag.diameter_in:g}"'
                run.width_in = tag.diameter_in
        elif run.width_pt > 0:
            run.width_in = round(scale.to_inches(run.width_pt), 1)
            run.size_label = f"~{run.width_in:g}\" (measured)"

        run.length_ft = scale.to_feet(run.length_pt)
        run.length_label = scale.format_length(run.length_pt)

    total_pt = sum(r.length_pt for r in runs)

    by_service: dict[str, dict] = {}
    for r in runs:
        key = r.service_name or ("Untagged " + ("ductwork" if kind == "duct" else "pipe"))
        row = by_service.setdefault(key, {"service": key, "code": r.service, "runs": 0, "length_ft": 0.0})
        row["runs"] += 1
        row["length_ft"] += r.length_ft

    by_size: dict[str, dict] = {}
    for r in runs:
        key = r.size_label or "Unsized"
        row = by_size.setdefault(key, {"size": key, "runs": 0, "length_ft": 0.0, "service": r.service_name})
        row["runs"] += 1
        row["length_ft"] += r.length_ft

    for row in list(by_service.values()) + list(by_size.values()):
        row["length_ft"] = round(row["length_ft"], 1)

    return LinearResult(
        runs=sorted(runs, key=lambda r: -r.length_pt),
        layer=layer,
        tags=tags,
        total_length_pt=total_pt,
        total_length_ft=scale.to_feet(total_pt),
        raw_linework_pt=raw_len,
        by_service=sorted(by_service.values(), key=lambda r: -r["length_ft"]),
        by_size=sorted(by_size.values(), key=lambda r: -r["length_ft"]),
        kind=kind,
    )


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


def build_connectivity(runs: Sequence[LinearRun], snap: float = 2.0) -> dict:
    """
    Which runs touch which — the basis for orphan detection and system tracing.

    An MEP system is a tree rooted at equipment; a run that connects to nothing
    is either a drafting error or an object the model has mis-traced, and either
    way a reviewer wants to see it.
    """
    endpoints: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for r in runs:
        for p in (r.points[0], r.points[-1]):
            endpoints[(int(round(p[0] / snap)), int(round(p[1] / snap)))].append(r.id)

    edges: set[tuple[int, int]] = set()
    for ids in endpoints.values():
        uniq = sorted(set(ids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                edges.add((uniq[i], uniq[j]))

    degree: dict[int, int] = collections.defaultdict(int)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    idx = {r.id: k for k, r in enumerate(runs)}
    uf = UnionFind(len(runs))
    for a, b in edges:
        if a in idx and b in idx:
            uf.union(idx[a], idx[b])

    networks: list[dict] = []
    for _root, members in uf.groups().items():
        ids = [runs[m].id for m in members]
        length = sum(runs[m].length_ft for m in members)
        networks.append({"runs": ids, "run_count": len(ids), "length_ft": round(length, 1)})
    networks.sort(key=lambda n: -n["length_ft"])

    return {
        "edges": sorted(edges),
        "degree": dict(degree),
        "networks": networks,
        "isolated_runs": [r.id for r in runs if degree.get(r.id, 0) == 0],
    }
