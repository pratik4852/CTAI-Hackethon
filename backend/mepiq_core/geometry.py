"""
Mid-level shape assembly.

PDF content streams are shredded: a diffuser is not "a diffuser", it is eleven
unrelated line and curve operators that happen to sit next to each other. This
module rebuilds the vocabulary an engineer actually reasons in — closed
polygons, circles, hatch runs, parallel pairs — so the symbol rules in
``symbols.py`` can be written the way the drawing legend describes them.
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .pdfdoc import Primitive

# ---------------------------------------------------------------------------
# Spatial index / union-find
# ---------------------------------------------------------------------------


class UnionFind:
    __slots__ = ("parent", "rank")

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = collections.defaultdict(list)
        for i in range(len(self.parent)):
            out[self.find(i)].append(i)
        return out


class PointIndex:
    """Grid index over 2-D points with an epsilon-neighbourhood query."""

    def __init__(self, eps: float = 0.6):
        self.eps = eps
        self.cell = max(eps * 2.0, 0.5)
        self.buckets: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        self.points: list[tuple[float, float]] = []

    def add(self, x: float, y: float) -> int:
        i = len(self.points)
        self.points.append((x, y))
        self.buckets[(int(x // self.cell), int(y // self.cell))].append(i)
        return i

    def near(self, x: float, y: float, radius: float | None = None) -> list[int]:
        r = self.eps if radius is None else radius
        c = self.cell
        out: list[int] = []
        for gx in range(int((x - r) // c), int((x + r) // c) + 1):
            for gy in range(int((y - r) // c), int((y + r) // c) + 1):
                for i in self.buckets.get((gx, gy), ()):
                    px, py = self.points[i]
                    if (px - x) ** 2 + (py - y) ** 2 <= r * r:
                        out.append(i)
        return out


class SegmentIndex:
    """Grid index over primitive midpoints — the workhorse for locality queries."""

    def __init__(self, prims: Sequence[Primitive], cell: float = 24.0):
        self.cell = cell
        self.prims = prims
        self.buckets: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        for i, p in enumerate(prims):
            x0, y0, x1, y1 = p.bbox()
            for gx in range(int(x0 // cell), int(x1 // cell) + 1):
                for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                    self.buckets[(gx, gy)].append(i)

    def query_box(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        c = self.cell
        seen: set[int] = set()
        for gx in range(int(x0 // c), int(x1 // c) + 1):
            for gy in range(int(y0 // c), int(y1 // c) + 1):
                seen.update(self.buckets.get((gx, gy), ()))
        return list(seen)

    def query_radius(self, x: float, y: float, r: float) -> list[int]:
        return self.query_box(x - r, y - r, x + r, y + r)


# ---------------------------------------------------------------------------
# Assembled shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Polygon:
    points: list[tuple[float, float]]
    member_ids: list[int]
    closed: bool = True
    width: float = 0.0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def size(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return (x1 - x0, y1 - y0)

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    @property
    def area(self) -> float:
        pts = self.points
        n = len(pts)
        s = 0.0
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    def is_rectangle(self, tol: float = 0.16) -> bool:
        if len(self.points) != 4:
            return False
        w, h = self.size
        if w < 1e-6 or h < 1e-6:
            return False
        return self.area >= (1.0 - tol) * w * h

    def is_square(self, tol: float = 0.22) -> bool:
        w, h = self.size
        if max(w, h) < 1e-6:
            return False
        return self.is_rectangle() and abs(w - h) / max(w, h) <= tol


@dataclass(slots=True)
class Circle:
    cx: float
    cy: float
    r: float
    member_ids: list[int] = field(default_factory=list)
    filled: bool = False
    width: float = 0.0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r)


@dataclass(slots=True)
class HatchRun:
    """A spine with regularly spaced perpendicular ticks — i.e. flexible duct."""

    x0: float
    y0: float
    x1: float
    y1: float
    n_ticks: int
    pitch: float
    tick_len: float
    member_ids: list[int] = field(default_factory=list)
    #: True extent of the hash marks, which is how the object is boxed.
    extent: tuple[float, float, float, float] | None = None

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if self.extent:
            return self.extent
        pad = self.tick_len / 2.0
        return (
            min(self.x0, self.x1) - pad, min(self.y0, self.y1) - pad,
            max(self.x0, self.x1) + pad, max(self.y0, self.y1) + pad,
        )


# ---------------------------------------------------------------------------
# Assembly routines
# ---------------------------------------------------------------------------


def _node_key(x: float, y: float, q: float) -> tuple[int, int]:
    return (int(round(x / q)), int(round(y / q)))


def build_node_graph(prims: Sequence[Primitive], snap: float = 0.35):
    """Snap endpoints onto shared nodes and return (nodes, adjacency, edges)."""
    node_of: dict[tuple[int, int], int] = {}
    nodes: list[tuple[float, float]] = []
    edges: list[tuple[int, int, int]] = []  # (node_a, node_b, prim_index)
    adj: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)

    def node(x: float, y: float) -> int:
        base = _node_key(x, y, snap)
        # Check the 3x3 neighbourhood so points either side of a rounding
        # boundary still merge.
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

    for idx, p in enumerate(prims):
        if p.length < 1e-9:
            continue
        a = node(p.x0, p.y0)
        b = node(p.x1, p.y1)
        if a == b:
            continue
        e = len(edges)
        edges.append((a, b, idx))
        adj[a].append((b, e))
        adj[b].append((a, e))

    return nodes, adj, edges


def find_closed_polygons(
    prims: Sequence[Primitive],
    max_size: float = 90.0,
    min_size: float = 2.0,
    max_edges: int = 6,
    snap: float = 0.35,
) -> list[Polygon]:
    """Recover small closed loops (3-6 edges) — squares, rectangles, diamonds."""
    short = [i for i, p in enumerate(prims) if min_size * 0.4 <= p.length <= max_size * 1.5]
    sub = [prims[i] for i in short]
    nodes, adj, edges = build_node_graph(sub, snap)

    polys: list[Polygon] = []
    used_edges: set[int] = set()

    # Native rectangle primitives arrive as four consecutive 're' edges — those
    # are already known-good loops, so harvest them first and cheaply.
    for e_i, (a, b, pidx) in enumerate(edges):
        if sub[pidx].kind != "re":
            continue
    # Generic small-cycle search: for each edge, walk breadth-first back to the
    # start node within max_edges steps.
    for start_e, (sa, sb, _pi) in enumerate(edges):
        if start_e in used_edges:
            continue
        stack = [(sb, [sa, sb], [start_e])]
        found: list[int] | None = None
        while stack:
            cur, path, ed = stack.pop()
            if len(ed) > max_edges:
                continue
            for nxt, e in adj[cur]:
                if e in ed:
                    continue
                if nxt == sa and len(ed) >= 2:
                    found = ed + [e]
                    stack = []
                    break
                if len(ed) < max_edges - 1 and nxt not in path:
                    stack.append((nxt, path + [nxt], ed + [e]))
            if found:
                break
        if not found:
            continue
        pts: list[tuple[float, float]] = []
        member: list[int] = []
        cur = sa
        for e in found:
            a, b, pidx = edges[e]
            pts.append(nodes[cur])
            cur = b if a == cur else a
            member.append(short[pidx])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w > max_size or h > max_size or max(w, h) < min_size:
            continue
        used_edges.update(found)
        polys.append(Polygon(pts, member, True, sub[edges[found[0]][2]].width))

    return polys


def find_circles(
    prims: Sequence[Primitive],
    max_r: float = 45.0,
    min_r: float = 0.8,
    snap: float = 0.5,
) -> list[Circle]:
    """Fit circles to clusters of curve chords (PDF draws circles as 4 beziers)."""
    idx = [i for i, p in enumerate(prims) if p.kind == "c" and p.length <= max_r * 3]
    if not idx:
        return []
    sub = [prims[i] for i in idx]
    nodes, adj, edges = build_node_graph(sub, snap)

    uf = UnionFind(len(sub))
    for a, b, pidx in edges:
        for nb, e in adj[a]:
            uf.union(pidx, edges[e][2])
        for nb, e in adj[b]:
            uf.union(pidx, edges[e][2])

    circles: list[Circle] = []
    for _root, members in uf.groups().items():
        if len(members) < 3:
            continue
        pts: list[tuple[float, float]] = []
        for m in members:
            p = sub[m]
            pts.append((p.x0, p.y0))
            pts.append((p.x1, p.y1))
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        rs = [math.hypot(q[0] - cx, q[1] - cy) for q in pts]
        r = sum(rs) / len(rs)
        if r < min_r or r > max_r:
            continue
        spread = max(abs(v - r) for v in rs)
        if spread > max(0.35, r * 0.22):  # not round enough
            continue
        circles.append(
            Circle(cx, cy, r, [idx[m] for m in members], filled=sub[members[0]].fill, width=sub[members[0]].width)
        )
    return circles


def find_hatch_runs(
    prims: Sequence[Primitive],
    index: SegmentIndex | None = None,
    min_ticks: int = 5,
    min_tick_len: float = 2.0,
    max_tick_len: float = 26.0,
    pitch_tol: float = 0.2,
    lateral_frac: float = 0.2,
) -> list[HatchRun]:
    """
    Detect flexible duct: a run crossed by evenly spaced hash marks.

    A hatch pattern is defined by its *regularity*, so the ticks are bucketed by
    quantised length **and** orientation before chaining. That is what separates
    real hash marks from everything else nearby — flexible duct is drawn with
    curved side walls, and a CAD exporter flattens each curve into dozens of
    sub-millimetre chords that sit right on top of the ticks. Bucketing on length
    ignores them; a plain "short segments near each other" rule drowns in them.
    """
    cand = [i for i, p in enumerate(prims) if min_tick_len <= p.length <= max_tick_len]
    if len(cand) < min_ticks:
        return []

    ANGLE_BINS = 36  # 5-degree resolution
    buckets: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for i in cand:
        p = prims[i]
        buckets[(int(round(p.length / 0.5)), int(p.angle / (math.pi / ANGLE_BINS)))].append(i)

    runs: list[HatchRun] = []

    for (len_bin, angle_bin), ids in buckets.items():
        if len(ids) < min_ticks:
            continue
        tick_len = len_bin * 0.5
        if tick_len < min_tick_len:
            continue
        ang = (angle_bin + 0.5) * (math.pi / ANGLE_BINS)
        # Ticks are perpendicular to the run, so the run direction is the tick's
        # normal; project midpoints onto it and look for even spacing.
        nx, ny = -math.sin(ang), math.cos(ang)

        items = []
        for i in ids:
            mx, my = prims[i].midpoint
            items.append((mx * nx + my * ny, mx * math.cos(ang) + my * math.sin(ang), i))
        items.sort()

        run: list[tuple[float, float, int]] = []

        def flush() -> None:
            if len(run) >= min_ticks:
                runs.append(_hatch_from(run, prims))

        # Pitch must be a sensible fraction of the tick length: closer than 15%
        # is the same stroke drawn twice, wider than 1.6x is not a hatch.
        lo, hi = tick_len * 0.15, tick_len * 1.6

        for it in items:
            if not run:
                run = [it]
                continue
            gap = it[0] - run[-1][0]
            # Ticks of one duct stay laterally aligned along the spine.
            lateral = abs(it[1] - run[-1][1])
            if len(run) >= 2:
                pitch = (run[-1][0] - run[0][0]) / (len(run) - 1)
                ok = abs(gap - pitch) <= max(0.25, pitch * pitch_tol)
            else:
                ok = lo <= gap <= hi
            if ok and lateral <= tick_len * lateral_frac:
                run.append(it)
                continue
            flush()
            run = [it]
        flush()

    return runs


def _hatch_from(run, prims) -> HatchRun:
    ids = [r[2] for r in run]
    pitch = (run[-1][0] - run[0][0]) / max(1, len(run) - 1)
    tick_len = sum(prims[i].length for i in ids) / len(ids)
    # The extent of the object is the union of its hash marks — which is exactly
    # how the supplied annotations box flexible duct.
    x0 = min(min(prims[i].x0, prims[i].x1) for i in ids)
    x1 = max(max(prims[i].x0, prims[i].x1) for i in ids)
    y0 = min(min(prims[i].y0, prims[i].y1) for i in ids)
    y1 = max(max(prims[i].y0, prims[i].y1) for i in ids)
    a = prims[ids[0]].midpoint
    b = prims[ids[-1]].midpoint
    return HatchRun(a[0], a[1], b[0], b[1], len(ids), abs(pitch), tick_len, ids, (x0, y0, x1, y1))


def find_parallel_pairs(
    prims: Sequence[Primitive],
    index: SegmentIndex,
    min_gap: float = 1.2,
    max_gap: float = 220.0,
    angle_tol: float = 0.03,
    overlap_frac: float = 0.55,
    min_len: float = 4.0,
) -> list[tuple[int, int, float]]:
    """Parallel, overlapping, same-weight segment pairs — the two walls of a duct."""
    out: list[tuple[int, int, float]] = []
    seen: set[tuple[int, int]] = set()
    for i, a in enumerate(prims):
        if a.length < min_len:
            continue
        ang = a.angle
        ux, uy = math.cos(ang), math.sin(ang)
        mx, my = a.midpoint
        for j in index.query_radius(mx, my, max(a.length, max_gap) * 0.75):
            if j <= i:
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
            key = (i, j)
            if key in seen:
                continue
            seen.add(key)
            out.append((i, j, perp))
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def bbox_union(boxes: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    xs0, ys0, xs1, ys1 = [], [], [], []
    for b in boxes:
        xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def bbox_contains(outer: Sequence[float], point: Sequence[float], pad: float = 0.0) -> bool:
    return (outer[0] - pad <= point[0] <= outer[2] + pad) and (outer[1] - pad <= point[1] <= outer[3] + pad)


def nms(boxes: list[Sequence[float]], scores: list[float], iou_thresh: float = 0.3) -> list[int]:
    order = sorted(range(len(boxes)), key=lambda i: -scores[i])
    keep: list[int] = []
    for i in order:
        if all(bbox_iou(boxes[i], boxes[k]) <= iou_thresh for k in keep):
            keep.append(i)
    return keep


def douglas_peucker(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    norm = math.hypot(dx, dy)
    best_i, best_d = 0, -1.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm < 1e-9:
            d = math.hypot(px - start[0], py - start[1])
        else:
            d = abs(dy * px - dx * py + end[0] * start[1] - end[1] * start[0]) / norm
        if d > best_d:
            best_i, best_d = i, d
    if best_d > eps:
        left = douglas_peucker(points[: best_i + 1], eps)
        right = douglas_peucker(points[best_i:], eps)
        return left[:-1] + right
    return [start, end]
