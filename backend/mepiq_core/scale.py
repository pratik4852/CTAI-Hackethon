"""
Drawing-scale detection.

Getting the scale wrong makes every length wrong, so this module does not rely
on a single trick. It runs a ladder of independent estimators, each returning a
candidate with its own confidence and a human-readable justification, then picks
the best. The provenance string is surfaced in the UI so a reviewer can see *why*
the app believes a sheet is 1/4" = 1'-0" — and override it in one click.

Estimators, strongest first:

1. ``title_block``      — the scale is literally printed on the sheet.
2. ``dimension_string`` — a dimension annotation ("7' - 8 1/2\"") sitting on a
                          dimension line of known drawn length.
3. ``duct_tag``         — a duct tagged "42/20" drawn as a parallel pair whose
                          gap must therefore be 42 inches.
4. ``known_component``  — square ceiling diffusers are a 24" ceiling module.
5. ``sheet_size``       — last-resort prior from the paper size.
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .pdfdoc import PT_PER_INCH, Primitive, Sheet

# ---------------------------------------------------------------------------
# Standard scales, expressed as real-world inches per PDF point
# ---------------------------------------------------------------------------

def _imperial(paper_inches: float) -> float:
    """paper_inches of drawing == 1 foot of building -> real inches per point."""
    return (12.0 / paper_inches) / PT_PER_INCH


STANDARD_SCALES: dict[str, float] = {
    '1/32" = 1\'-0"': _imperial(1 / 32),
    '1/16" = 1\'-0"': _imperial(1 / 16),
    '3/32" = 1\'-0"': _imperial(3 / 32),
    '1/8" = 1\'-0"': _imperial(1 / 8),
    '3/16" = 1\'-0"': _imperial(3 / 16),
    '1/4" = 1\'-0"': _imperial(1 / 4),
    '3/8" = 1\'-0"': _imperial(3 / 8),
    '1/2" = 1\'-0"': _imperial(1 / 2),
    '3/4" = 1\'-0"': _imperial(3 / 4),
    '1" = 1\'-0"': _imperial(1.0),
    '1-1/2" = 1\'-0"': _imperial(1.5),
    '3" = 1\'-0"': _imperial(3.0),
    "1:20": 20 / 25.4 * (25.4 / PT_PER_INCH),
    "1:50": 50 * (25.4 / PT_PER_INCH) / 25.4,
    "1:75": 75 * (25.4 / PT_PER_INCH) / 25.4,
    "1:100": 100 * (25.4 / PT_PER_INCH) / 25.4,
    "1:150": 150 * (25.4 / PT_PER_INCH) / 25.4,
    "1:200": 200 * (25.4 / PT_PER_INCH) / 25.4,
}

# Note: for metric, in/pt = (mm_real per mm_paper) * (25.4mm/inch paper) / 72pt/inch / 25.4
# which simplifies to ratio / PT_PER_INCH  -> handled above.

METRIC_SCALES = {k: v for k, v in STANDARD_SCALES.items() if k.startswith("1:")}


@dataclass
class ScaleInfo:
    """Everything the rest of the system needs to convert points to reality."""

    inches_per_pt: float
    label: str
    method: str
    confidence: float
    evidence: str = ""
    units: str = "imperial"
    candidates: list[dict] = field(default_factory=list)
    manual: bool = False

    # -- conversions --------------------------------------------------------

    @property
    def feet_per_pt(self) -> float:
        return self.inches_per_pt / 12.0

    @property
    def mm_per_pt(self) -> float:
        return self.inches_per_pt * 25.4

    def to_feet(self, pts: float) -> float:
        return pts * self.feet_per_pt

    def to_inches(self, pts: float) -> float:
        return pts * self.inches_per_pt

    def to_metres(self, pts: float) -> float:
        return pts * self.inches_per_pt * 0.0254

    def format_length(self, pts: float) -> str:
        if self.units == "metric":
            return f"{self.to_metres(pts):.2f} m"
        ft = self.to_feet(pts)
        whole = int(ft)
        inches = (ft - whole) * 12.0
        return f"{whole}'-{inches:.1f}\""

    def as_dict(self) -> dict:
        return {
            "inches_per_pt": self.inches_per_pt,
            "feet_per_pt": self.feet_per_pt,
            "label": self.label,
            "method": self.method,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "units": self.units,
            "manual": self.manual,
            "candidates": self.candidates,
        }


def snap_to_standard(
    inches_per_pt: float,
    tolerance: float = 0.06,
    allow_metric: bool = False,
) -> tuple[str, float] | None:
    """
    Snap a measured ratio onto a real drafting scale.

    Metric ratios sit between the imperial ones, so a noisy imperial estimate
    will happily land on '1:75'. Metric is therefore only considered when the
    sheet gives us a reason to believe it is a metric drawing.
    """
    pool = STANDARD_SCALES if allow_metric else {
        k: v for k, v in STANDARD_SCALES.items() if not k.startswith("1:")
    }
    best = None
    for name, val in pool.items():
        err = abs(val - inches_per_pt) / val
        if err <= tolerance and (best is None or err < best[2]):
            best = (name, val, err)
    if best is None:
        return None
    return best[0], best[1]


# ---------------------------------------------------------------------------
# 1. Title-block text
# ---------------------------------------------------------------------------

_FRAC = r"(?:\d+\s*/\s*\d+|\d+(?:\s+\d+\s*/\s*\d+)?)"
_IMP_RE = re.compile(rf'({_FRAC})\s*"?\s*=\s*(\d+)\s*\'\s*-?\s*(\d+)?\s*"?')
_RATIO_RE = re.compile(r"\b1\s*:\s*(\d{1,4})\b")
_NTS_RE = re.compile(r"\b(N\.?T\.?S\.?|NOT\s+TO\s+SCALE)\b", re.I)


def _parse_fraction(txt: str) -> float | None:
    txt = txt.strip()
    try:
        if "/" in txt:
            parts = txt.split()
            if len(parts) == 2:  # "1 1/2"
                num, frac = parts
                a, b = frac.split("/")
                return float(num) + float(a) / float(b)
            a, b = txt.split("/")
            return float(a) / float(b)
        return float(txt)
    except Exception:
        return None


def scale_from_title_block(sheet: Sheet) -> ScaleInfo | None:
    """Look for '1/8" = 1'-0"' or '1:100' in the sheet text."""
    text = sheet.text_blob()
    if not text:
        return None
    votes: collections.Counter[tuple[str, float, str]] = collections.Counter()

    for m in _IMP_RE.finditer(text):
        paper = _parse_fraction(m.group(1))
        feet = float(m.group(2) or 0)
        inches = float(m.group(3) or 0)
        real_ft = feet + inches / 12.0
        if not paper or paper <= 0 or real_ft <= 0:
            continue
        ipt = (real_ft * 12.0 / paper) / PT_PER_INCH
        snapped = snap_to_standard(ipt)
        if snapped:
            votes[(snapped[0], snapped[1], "imperial")] += 1

    for m in _RATIO_RE.finditer(text):
        ratio = float(m.group(1))
        if ratio < 5 or ratio > 2000:
            continue
        ipt = ratio / PT_PER_INCH
        snapped = snap_to_standard(ipt)
        label = snapped[0] if snapped else f"1:{int(ratio)}"
        val = snapped[1] if snapped else ipt
        votes[(label, val, "metric")] += 1

    if not votes:
        return None
    (label, val, units), n = votes.most_common(1)[0]
    conf = min(0.98, 0.86 + 0.03 * n)
    return ScaleInfo(val, label, "title_block", conf, f"Scale text found on sheet ({n} occurrence(s))", units)


# ---------------------------------------------------------------------------
# 2. Dimension strings
# ---------------------------------------------------------------------------

_DIM_RE = re.compile(r"^\(?\s*(\d{1,3})\s*'\s*-?\s*(\d{1,2})?\s*(?:(\d+)\s*/\s*(\d+))?\s*\"?\s*\)?$")
_DIM_MM_RE = re.compile(r"^\(?\s*(\d{3,5})\s*(?:mm)?\s*\)?$", re.I)


def _dim_value_inches(txt: str) -> float | None:
    m = _DIM_RE.match(txt.strip())
    if m:
        ft = float(m.group(1))
        inch = float(m.group(2) or 0)
        if m.group(3) and m.group(4):
            inch += float(m.group(3)) / float(m.group(4))
        val = ft * 12 + inch
        return val if 12 <= val <= 2400 else None
    return None


def _sheet_is_metric(sheet: Sheet) -> bool:
    blob = sheet.text_blob().lower()
    return ("mm" in blob or " m " in blob) and '"' not in blob[:4000]


def scale_from_dimension_strings(sheet: Sheet, max_samples: int = 400) -> ScaleInfo | None:
    """Match a dimension annotation to the dimension line it labels."""
    dims: list[tuple[float, tuple[float, float]]] = []
    for t in sheet.texts:
        v = _dim_value_inches(t.text)
        if v is not None:
            dims.append((v, t.center))
        if len(dims) >= max_samples:
            break
    if len(dims) < 2:
        return None

    fg = [p for p in sheet.foreground() if p.length > 8]
    grid = _SpatialIndex(fg, cell=60.0)
    metric = _sheet_is_metric(sheet)

    votes: collections.Counter[str] = collections.Counter()
    samples = 0
    for value_in, (cx, cy) in dims:
        near = grid.query(cx, cy, 90.0)
        # A dimension line runs *through* the text: pick the longest nearly
        # collinear segment whose midpoint is closest to the label.
        best = None
        for p in near:
            mx, my = p.midpoint
            d = math.hypot(mx - cx, my - cy)
            if d > 90:
                continue
            if best is None or (p.length > best.length and d < 60):
                best = p
        if best is None or best.length < 5:
            continue
        ipt = value_in / best.length
        snapped = snap_to_standard(ipt, tolerance=0.08, allow_metric=metric)
        if snapped:
            votes[snapped[0]] += 1
            samples += 1

    if not votes or samples < 2:
        return None
    label, n = votes.most_common(1)[0]
    total = sum(votes.values())
    agreement = n / total
    conf = min(0.92, 0.55 + 0.35 * agreement + 0.02 * n)
    return ScaleInfo(
        STANDARD_SCALES[label], label, "dimension_string", conf,
        f"{n}/{total} dimension annotations agree", "imperial",
    )


# ---------------------------------------------------------------------------
# 3. Duct size tags
# ---------------------------------------------------------------------------

_DUCT_TAG = re.compile(r"^x?\s*(\d{1,3})\s*/\s*(\d{1,3})\b")


class _SpatialIndex:
    """Uniform grid over primitives — keeps neighbour queries near O(1)."""

    def __init__(self, prims: Sequence[Primitive], cell: float = 50.0):
        self.cell = cell
        self.buckets: dict[tuple[int, int], list[Primitive]] = collections.defaultdict(list)
        for p in prims:
            mx, my = p.midpoint
            self.buckets[(int(mx // cell), int(my // cell))].append(p)

    def query(self, x: float, y: float, radius: float) -> list[Primitive]:
        c = self.cell
        out: list[Primitive] = []
        for gx in range(int((x - radius) // c), int((x + radius) // c) + 1):
            for gy in range(int((y - radius) // c), int((y + radius) // c) + 1):
                out.extend(self.buckets.get((gx, gy), ()))
        return out


def _parallel_gaps(near: Sequence[Primitive], cx: float, cy: float, max_gap: float = 260.0) -> list[float]:
    """Perpendicular gaps of overlapping parallel pairs, nearest centre first."""
    found: list[tuple[float, float]] = []
    n = len(near)
    for i in range(n):
        a = near[i]
        if a.length < 8:
            continue
        ang = a.angle
        ux, uy = math.cos(ang), math.sin(ang)
        for j in range(i + 1, n):
            b = near[j]
            if b.length < 8 or abs(b.width - a.width) > 0.02:
                continue
            da = abs(ang - b.angle)
            da = min(da, math.pi - da)
            if da > 0.02:
                continue
            perp = abs(-uy * (b.x0 - a.x0) + ux * (b.y0 - a.y0))
            if perp < 2.0 or perp > max_gap:
                continue
            pa = sorted((a.x0 * ux + a.y0 * uy, a.x1 * ux + a.y1 * uy))
            pb = sorted((b.x0 * ux + b.y0 * uy, b.x1 * ux + b.y1 * uy))
            overlap = min(pa[1], pb[1]) - max(pa[0], pb[0])
            if overlap < min(a.length, b.length) * 0.6:
                continue
            mcx = (a.midpoint[0] + b.midpoint[0]) / 2
            mcy = (a.midpoint[1] + b.midpoint[1]) / 2
            found.append((math.hypot(mcx - cx, mcy - cy), perp))
    found.sort()
    return [f[1] for f in found[:4]]


def scale_from_duct_tags(sheet: Sheet) -> ScaleInfo | None:
    """A duct tagged 42/20 is 42 inches across — so its drawn gap fixes the scale."""
    tags: list[tuple[int, tuple[float, float]]] = []
    for t in sheet.texts:
        m = _DUCT_TAG.match(t.text)
        if not m:
            continue
        big = max(int(m.group(1)), int(m.group(2)))
        if 4 <= big <= 144:
            tags.append((big, t.center))
    if len(tags) < 3:
        return None

    fg = [p for p in sheet.foreground() if p.length > 8]
    grid = _SpatialIndex(fg, cell=50.0)

    metric = _sheet_is_metric(sheet)
    votes: collections.Counter[str] = collections.Counter()
    used = 0
    for size_in, (cx, cy) in tags[:300]:
        gaps = _parallel_gaps(grid.query(cx, cy, 100.0), cx, cy)
        if not gaps:
            continue
        used += 1
        hits: set[str] = set()
        pool = STANDARD_SCALES if metric else {k: v for k, v in STANDARD_SCALES.items() if not k.startswith("1:")}
        for name, ipt in pool.items():
            for g in gaps:
                if abs(g * ipt - size_in) / size_in < 0.08:
                    hits.add(name)
                    break
        for h in hits:
            votes[h] += 1

    if not votes or used < 3:
        return None
    label, n = votes.most_common(1)[0]
    agreement = n / max(1, used)
    if agreement < 0.25:
        return None
    conf = min(0.9, 0.45 + 0.5 * agreement)
    return ScaleInfo(
        STANDARD_SCALES[label], label, "duct_tag", conf,
        f"{n}/{used} tagged ducts match this scale", "imperial",
    )


# ---------------------------------------------------------------------------
# 4. Known-component calibration
# ---------------------------------------------------------------------------

#: Real-world size, in inches, of components that are drawn true-to-scale.
KNOWN_COMPONENT_SIZES: dict[str, float] = {
    "Square Supply Diffuser (4-Way)": 24.0,
    "Square Return / Exhaust Register": 24.0,
    "Round Supply Diffuser": 24.0,
}


def scale_from_known_components(detections: Iterable[dict]) -> ScaleInfo | None:
    """Ceiling diffusers sit in a 24" ceiling module — a reliable ruler."""
    samples: list[float] = []
    for det in detections:
        real = KNOWN_COMPONENT_SIZES.get(det.get("category", ""))
        if real is None:
            continue
        b = det.get("bbox_pt")
        if not b:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        side = min(w, h)
        if side < 4:
            continue
        samples.append(real / side)
    if len(samples) < 4:
        return None
    votes: collections.Counter[str] = collections.Counter()
    for s in samples:
        snapped = snap_to_standard(s, tolerance=0.10)
        if snapped:
            votes[snapped[0]] += 1
    if not votes:
        return None
    label, n = votes.most_common(1)[0]
    agreement = n / len(samples)
    if agreement < 0.35:
        return None
    conf = min(0.8, 0.35 + 0.45 * agreement)
    return ScaleInfo(
        STANDARD_SCALES[label], label, "known_component", conf,
        f"{n}/{len(samples)} ceiling diffusers measure 24\" at this scale", "imperial",
    )


# ---------------------------------------------------------------------------
# 5. Sheet-size prior
# ---------------------------------------------------------------------------


def scale_from_sheet_size(sheet: Sheet) -> ScaleInfo:
    """Weak prior: large-format floor plans are overwhelmingly 1/8" or 1/4"."""
    w_in = sheet.info.width_pt / PT_PER_INCH
    label = '1/8" = 1\'-0"' if w_in >= 36 else '1/4" = 1\'-0"'
    return ScaleInfo(
        STANDARD_SCALES[label], label, "sheet_size", 0.2,
        f"Assumed from {w_in:.0f}\" x {sheet.info.height_pt / PT_PER_INCH:.0f}\" sheet — please verify",
        "imperial",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def detect_scale(sheet: Sheet, detections: Iterable[dict] | None = None) -> ScaleInfo:
    """Run every estimator, keep them all, return the most trustworthy."""
    results: list[ScaleInfo] = []
    for fn in (scale_from_title_block, scale_from_dimension_strings, scale_from_duct_tags):
        try:
            r = fn(sheet)  # type: ignore[arg-type]
        except Exception:
            r = None
        if r:
            results.append(r)
    if detections:
        try:
            r = scale_from_known_components(detections)
            if r:
                results.append(r)
        except Exception:
            pass

    fallback = scale_from_sheet_size(sheet)
    results.append(fallback)

    # Agreement between independent estimators is the strongest signal there is.
    by_label: dict[str, list[ScaleInfo]] = collections.defaultdict(list)
    for r in results:
        by_label[r.label].append(r)
    for label, group in by_label.items():
        real = [g for g in group if g.method != "sheet_size"]
        if len(real) >= 2:
            for g in real:
                g.confidence = min(0.99, g.confidence + 0.10)

    results.sort(key=lambda r: -r.confidence)
    best = results[0]
    best.candidates = [
        {"label": r.label, "method": r.method, "confidence": round(r.confidence, 3), "evidence": r.evidence}
        for r in results
    ]
    return best


def manual_scale(inches_per_pt: float, label: str | None = None, units: str = "imperial") -> ScaleInfo:
    snapped = snap_to_standard(inches_per_pt, tolerance=0.03)
    return ScaleInfo(
        inches_per_pt,
        label or (snapped[0] if snapped else f"{inches_per_pt:.4f} in/pt"),
        "manual",
        1.0,
        "Set by reviewer",
        units,
        manual=True,
    )


def scale_from_two_points(p1: Sequence[float], p2: Sequence[float], real_inches: float) -> ScaleInfo:
    """UI calibration: reviewer clicks two points and types the real distance."""
    d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if d <= 0 or real_inches <= 0:
        raise ValueError("Calibration points must differ and the distance must be positive")
    info = manual_scale(real_inches / d)
    info.evidence = f"Calibrated on a {real_inches:.2f}\" reference measuring {d:.2f} pt"
    return info
