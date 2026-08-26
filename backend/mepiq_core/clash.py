"""
Level 4 — cross-discipline coordination.

Clash detection normally requires a federated 3-D model, which is exactly what
does not exist at the stage where these drawings are produced. But most
coordination failures are visible in 2-D long before anyone builds a model: a
duct main and a sanitary line occupying the same corridor, a panel board sitting
under a duct drop, sprinkler mains crossing the return air plenum route.

This module overlays same-level sheets from different trades and reports where
their systems occupy the same plan space, ranked by how much they overlap. It is
a screening tool — it flags candidates for a human to check, and says so.
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Sequence

from .linear import LinearRun
from .scale import ScaleInfo
from .symbols import Detection

#: Minimum clear separation, in inches, expected between systems of two trades
#: before a 2-D overlap is worth a coordination note.
TRADE_CLEARANCE_IN: dict[frozenset, float] = {
    frozenset({"mechanical", "plumbing"}): 6.0,
    frozenset({"mechanical", "electrical"}): 12.0,
    frozenset({"mechanical", "fire_protection"}): 6.0,
    frozenset({"plumbing", "electrical"}): 12.0,
    frozenset({"plumbing", "fire_protection"}): 3.0,
    frozenset({"electrical", "fire_protection"}): 12.0,
}

_LEVEL_RE = re.compile(r"\b(?:LEVEL|LVL|FLOOR|FLR|L)\s*[-_ ]?\s*(\d{1,2})\b", re.I)
_PAGE_LEVEL_RE = re.compile(r"\b([A-Z]{1,3})[-_ ]?(\d)(\d{2})(?:\.\d+)?\b")


def infer_level(sheet_label: str, sheet_title: str = "", filename: str = "") -> str | None:
    """Best-effort building level from the sheet number or title."""
    hay = " ".join(filter(None, (sheet_title, sheet_label, filename)))
    m = _LEVEL_RE.search(hay)
    if m:
        return f"Level {int(m.group(1))}"
    m = _PAGE_LEVEL_RE.search(sheet_label or "")
    if m:
        return f"Level {int(m.group(2))}"
    return None


@dataclass
class Clash:
    id: int
    trade_a: str
    trade_b: str
    sheet_a: str
    sheet_b: str
    level: str | None
    kind: str                        # run-run | run-equipment | equipment-equipment
    ref_a: str
    ref_b: str
    location_pt: list[float]
    overlap_in: float
    clearance_required_in: float
    severity: str
    message: str
    status: str = "open"

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _seg_distance(a0, a1, b0, b1) -> tuple[float, tuple[float, float]]:
    """Closest distance between two 2-D segments and the midpoint of that approach."""
    def clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    ax, ay = a1[0] - a0[0], a1[1] - a0[1]
    bx, by = b1[0] - b0[0], b1[1] - b0[1]
    wx, wy = a0[0] - b0[0], a0[1] - b0[1]
    A = ax * ax + ay * ay
    B = ax * bx + ay * by
    C = bx * bx + by * by
    D = ax * wx + ay * wy
    E = bx * wx + by * wy
    denom = A * C - B * B
    if denom < 1e-9:
        s = 0.0
        t = clamp(E / C) if C > 1e-9 else 0.0
    else:
        s = clamp((B * E - C * D) / denom)
        t = clamp((A * E - B * D) / denom)
    px, py = a0[0] + s * ax, a0[1] + s * ay
    qx, qy = b0[0] + t * bx, b0[1] + t * by
    return math.hypot(px - qx, py - qy), ((px + qx) / 2.0, (py + qy) / 2.0)


class _RunGrid:
    def __init__(self, runs: Sequence[LinearRun], cell: float = 40.0):
        self.cell = cell
        self.items: dict[tuple[int, int], list[tuple[int, int]]] = collections.defaultdict(list)
        self.runs = runs
        for ri, r in enumerate(runs):
            for si in range(len(r.points) - 1):
                x0, y0 = r.points[si]
                x1, y1 = r.points[si + 1]
                for gx in range(int(min(x0, x1) // cell), int(max(x0, x1) // cell) + 1):
                    for gy in range(int(min(y0, y1) // cell), int(max(y0, y1) // cell) + 1):
                        self.items[(gx, gy)].append((ri, si))

    def near(self, x0: float, y0: float, x1: float, y1: float, pad: float) -> set[tuple[int, int]]:
        c = self.cell
        out: set[tuple[int, int]] = set()
        for gx in range(int((min(x0, x1) - pad) // c), int((max(x0, x1) + pad) // c) + 1):
            for gy in range(int((min(y0, y1) - pad) // c), int((max(y0, y1) + pad) // c) + 1):
                out.update(self.items.get((gx, gy), ()))
        return out


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class SheetSystems:
    """One sheet's traced systems, ready to be overlaid on another trade's."""

    sheet_key: str
    sheet_label: str
    discipline: str
    level: str | None
    scale: ScaleInfo
    runs: list[LinearRun] = field(default_factory=list)
    equipment: list[Detection] = field(default_factory=list)
    width_pt: float = 0.0
    height_pt: float = 0.0


def detect_clashes(
    systems: Sequence[SheetSystems],
    max_per_pair: int = 150,
    min_overlap_in: float = 0.5,
) -> list[Clash]:
    """
    Overlay every pair of same-level sheets from different trades.

    Sheets are aligned on their shared drawing frame, which holds whenever the
    set was published from one model at one scale — the normal case for a
    coordinated package. Where scales differ the comparison is skipped rather
    than guessed at.
    """
    out: list[Clash] = []
    cid = 0

    for i in range(len(systems)):
        for j in range(i + 1, len(systems)):
            a, b = systems[i], systems[j]
            if a.discipline == b.discipline or a.discipline == "unknown" or b.discipline == "unknown":
                continue
            if a.level and b.level and a.level != b.level:
                continue
            if abs(a.scale.inches_per_pt - b.scale.inches_per_pt) / max(a.scale.inches_per_pt, 1e-9) > 0.02:
                continue
            if abs(a.width_pt - b.width_pt) > 2.0 or abs(a.height_pt - b.height_pt) > 2.0:
                continue

            clearance = TRADE_CLEARANCE_IN.get(frozenset({a.discipline, b.discipline}), 6.0)
            ipt = a.scale.inches_per_pt
            # Half-widths of the two systems plus the required clear gap, in points.
            found = 0
            grid = _RunGrid(b.runs)

            for ra in a.runs:
                if ra.length_ft < 3.0:
                    continue
                half_a = (ra.width_pt / 2.0) if ra.width_pt else (2.0 / max(ipt, 1e-9)) / 2.0
                for si in range(len(ra.points) - 1):
                    p0, p1 = ra.points[si], ra.points[si + 1]
                    pad = half_a + (clearance / max(ipt, 1e-9)) + 12.0
                    for (rj, sj) in grid.near(p0[0], p0[1], p1[0], p1[1], pad):
                        rb = b.runs[rj]
                        if rb.length_ft < 3.0:
                            continue
                        q0, q1 = rb.points[sj], rb.points[sj + 1]
                        d, mid = _seg_distance(p0, p1, q0, q1)
                        half_b = (rb.width_pt / 2.0) if rb.width_pt else (2.0 / max(ipt, 1e-9)) / 2.0
                        gap_in = (d - half_a - half_b) * ipt
                        if gap_in > clearance:
                            continue
                        overlap_in = max(0.0, clearance - gap_in)
                        if overlap_in < min_overlap_in:
                            continue
                        cid += 1
                        found += 1
                        hard = gap_in <= 0
                        out.append(Clash(
                            cid, a.discipline, b.discipline, a.sheet_label, b.sheet_label, a.level or b.level,
                            "run-run",
                            f"{a.discipline} run #{ra.id}" + (f" ({ra.size_label})" if ra.size_label else ""),
                            f"{b.discipline} run #{rb.id}" + (f" ({rb.size_label})" if rb.size_label else ""),
                            [round(mid[0] - 6, 2), round(mid[1] - 6, 2), round(mid[0] + 6, 2), round(mid[1] + 6, 2)],
                            round(overlap_in, 1), clearance,
                            "critical" if hard else ("high" if gap_in < clearance * 0.4 else "medium"),
                            (f"{a.discipline.title()} and {b.discipline} systems overlap in plan"
                             if hard else
                             f"Only {gap_in:.1f}\" clear between {a.discipline} and {b.discipline} systems "
                             f"(want {clearance:.0f}\")"),
                        ))
                        if found >= max_per_pair:
                            break
                    if found >= max_per_pair:
                        break
                if found >= max_per_pair:
                    break

            # Equipment sitting under another trade's run.
            eq_found = 0
            for det in b.equipment:
                bx = det.bbox_pt
                cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
                pad = max(bx[2] - bx[0], bx[3] - bx[1]) / 2 + 4.0
                for (rj, sj) in _RunGrid(a.runs).near(cx, cy, cx, cy, pad):
                    ra = a.runs[rj]
                    p0, p1 = ra.points[sj], ra.points[sj + 1]
                    d, mid = _seg_distance((cx, cy), (cx, cy), p0, p1)
                    if d > pad:
                        continue
                    cid += 1
                    eq_found += 1
                    out.append(Clash(
                        cid, a.discipline, b.discipline, a.sheet_label, b.sheet_label, a.level or b.level,
                        "run-equipment",
                        f"{a.discipline} run #{ra.id}", f"{det.category}",
                        [round(v, 2) for v in bx], round((pad - d) * ipt, 1), clearance,
                        "high",
                        f"{a.discipline.title()} ductwork passes directly over {det.category} — "
                        f"verify access and clearance.",
                    ))
                    break
                if eq_found >= 40:
                    break

    return out


def summarise_clashes(clashes: Sequence[Clash]) -> dict:
    by_sev: collections.Counter = collections.Counter()
    by_pair: collections.Counter = collections.Counter()
    for c in clashes:
        if c.status == "dismissed":
            continue
        by_sev[c.severity] += 1
        by_pair[f"{c.trade_a} / {c.trade_b}"] += 1
    return {
        "total": sum(by_sev.values()),
        "by_severity": dict(by_sev),
        "by_trade_pair": [{"pair": k, "count": v} for k, v in by_pair.most_common()],
    }
