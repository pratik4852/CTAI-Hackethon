"""
Level 4 — design validation, constructability review and risk rules.

Counting things is table stakes. What actually saves an engineer time is being
told *which* of the 400 objects on a sheet deserves a second look. Every rule
here encodes a check a reviewer would otherwise do by hand, and every finding
carries a location so the UI can fly the reviewer straight to it.

Rules are declarative and each returns findings with a severity, an explanation
in engineering language, and the evidence that triggered it — so nothing is a
black box and a reviewer can dismiss a finding they disagree with.
"""

from __future__ import annotations

import collections
import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

from .linear import LinearRun, LineTag
from .scale import ScaleInfo
from .symbols import Detection

SEVERITIES = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    discipline: str
    message: str
    recommendation: str = ""
    location_pt: list[float] | None = None      # [x0, y0, x1, y1]
    sheet_index: int = 0
    sheet_label: str = ""
    refs: dict = field(default_factory=dict)
    status: str = "open"                        # open | accepted | dismissed

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Rule:
    id: str
    title: str
    severity: str
    discipline: str
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


RULES: list[Rule] = [
    Rule("MEP-001", "Unconnected duct or pipe run", "high", "mechanical,plumbing",
         "A run that terminates without joining another run or a piece of equipment is "
         "either an incomplete design or a drafting break that will be missed on site."),
    Rule("MEP-002", "Air terminal not served by ductwork", "high", "mechanical",
         "Every diffuser, register and grille must be reachable from a duct. An orphan "
         "terminal means missing branch ductwork or a coordination gap."),
    Rule("MEP-003", "Untagged run", "medium", "mechanical,plumbing",
         "Runs without a size/service annotation cannot be priced or fabricated and are "
         "the single largest source of RFIs on MEP packages."),
    Rule("MEP-004", "Duct size reduces then increases along a run", "medium", "mechanical",
         "A downstream section larger than its upstream feed is usually a tagging error "
         "and will not balance."),
    Rule("MEP-005", "Fire damper not at a rated element", "medium", "mechanical",
         "Fire dampers are only effective where the duct crosses a rated barrier. Isolated "
         "dampers suggest a moved wall or a leftover symbol."),
    Rule("MEP-006", "Duct penetrating a rated wall without a damper", "critical", "mechanical",
         "A duct crossing a fire-rated barrier without a damper is a life-safety and code "
         "compliance failure."),
    Rule("MEP-007", "Very long run without a branch", "low", "mechanical,plumbing",
         "Unusually long uninterrupted runs are worth checking for missed fittings or a "
         "mis-traced object."),
    Rule("MEP-008", "Drawing scale not confirmed", "high", "all",
         "Every measured quantity depends on the sheet scale. If it could not be read from "
         "the sheet, quantities must be treated as provisional until confirmed."),
    Rule("MEP-009", "Unidentified repeated symbol", "low", "all",
         "Geometry that repeats many times is almost certainly a component. Naming it once "
         "adds it to the takeoff and teaches the library."),
    Rule("MEP-010", "Existing service shown as modified", "info", "plumbing",
         "Runs tagged (E) are existing. Confirm demolition and reconnection scope."),
    Rule("MEP-011", "Air terminal density outside typical range", "low", "mechanical",
         "Diffuser spacing far outside 8-20 ft on centre often signals a missed zone or a "
         "duplicated layout."),
    Rule("MEP-012", "Undersized branch feeding a large terminal", "medium", "mechanical",
         "A branch narrower than the neck it serves will not deliver design airflow."),
]

RULES_BY_ID = {r.id: r for r in RULES}

AIR_TERMINALS = {
    "square_supply_diffuser_4way",
    "square_return_exhaust_register",
    "round_supply_diffuser",
    "linear_bar_grille",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _centre(box: Sequence[float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _dist_point_run(px: float, py: float, run: LinearRun) -> float:
    best = float("inf")
    pts = run.points
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
        best = min(best, d)
    return best


class _RunIndex:
    def __init__(self, runs: Sequence[LinearRun], cell: float = 48.0):
        self.cell = cell
        self.runs = runs
        self.buckets: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        for i, r in enumerate(runs):
            b = r.bbox
            for gx in range(int(b[0] // cell), int(b[2] // cell) + 1):
                for gy in range(int(b[1] // cell), int(b[3] // cell) + 1):
                    self.buckets[(gx, gy)].append(i)

    def near(self, x: float, y: float, radius: float) -> list[LinearRun]:
        c = self.cell
        seen: set[int] = set()
        for gx in range(int((x - radius) // c), int((x + radius) // c) + 1):
            for gy in range(int((y - radius) // c), int((y + radius) // c) + 1):
                seen.update(self.buckets.get((gx, gy), ()))
        return [self.runs[i] for i in seen]


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------


def run_validation(
    detections: Sequence[Detection],
    runs: Sequence[LinearRun],
    connectivity: dict,
    scale: ScaleInfo,
    discipline: str,
    sheet_index: int = 0,
    sheet_label: str = "",
    glyphs: Sequence = (),
    max_findings_per_rule: int = 60,
) -> list[Finding]:
    findings: list[Finding] = []

    def add(rule_id: str, message: str, recommendation: str = "", loc=None, refs: dict | None = None) -> None:
        rule = RULES_BY_ID[rule_id]
        findings.append(
            Finding(rule_id, rule.title, rule.severity, rule.discipline, message,
                    recommendation, list(loc) if loc is not None else None,
                    sheet_index, sheet_label, refs or {})
        )

    # --- MEP-008: scale confidence ----------------------------------------
    if scale.confidence < 0.6 and not scale.manual:
        add("MEP-008",
            f"The sheet scale could not be read from the drawing. Quantities are computed at "
            f"{scale.label} ({scale.evidence}).",
            "Confirm or set the scale on this sheet — every length below scales with it.")

    # --- MEP-001: unconnected runs ----------------------------------------
    degree = connectivity.get("degree", {})
    long_orphans = [
        r for r in runs
        if degree.get(r.id, 0) == 0 and r.length_ft >= 6.0
    ]
    long_orphans.sort(key=lambda r: -r.length_ft)
    for r in long_orphans[:max_findings_per_rule]:
        add("MEP-001",
            f"{r.kind.title()} run #{r.id} ({r.length_label}"
            + (f", {r.size_label}" if r.size_label else "")
            + ") does not connect to any other run.",
            "Check for a missing fitting, a drafting gap, or a connection shown on another sheet.",
            r.bbox, {"run_id": r.id, "length_ft": round(r.length_ft, 1)})

    # --- MEP-002: orphan air terminals ------------------------------------
    if discipline == "mechanical" and runs:
        idx = _RunIndex(runs)
        reach = max(18.0, scale.to_inches(1.0) and (60.0 / max(scale.inches_per_pt, 1e-6)) / 12.0 or 24.0)
        reach = min(max(reach, 12.0), 48.0)
        orphans = []
        for d in detections:
            if d.category_key not in AIR_TERMINALS:
                continue
            cx, cy = _centre(d.bbox_pt)
            near = idx.near(cx, cy, reach)
            if not any(_dist_point_run(cx, cy, r) <= reach for r in near):
                orphans.append(d)
        for d in orphans[:max_findings_per_rule]:
            add("MEP-002",
                f"{d.category} at ({d.bbox_pt[0]:.0f}, {d.bbox_pt[1]:.0f}) has no ductwork within "
                f"{scale.format_length(reach)}.",
                "Verify the branch duct or flexible connection serving this terminal.",
                d.bbox_pt, {"detection_id": d.id, "category": d.category})

    # --- MEP-003: untagged runs -------------------------------------------
    substantial = [r for r in runs if r.length_ft >= 10.0]
    untagged = [r for r in substantial if not r.size_label or r.size_label.startswith("~")]
    if substantial:
        pct = len(untagged) / len(substantial)
        if pct > 0.25:
            total_ft = sum(r.length_ft for r in untagged)
            add("MEP-003",
                f"{len(untagged)} of {len(substantial)} runs over 10 ft carry no size/service tag "
                f"({pct * 100:.0f}%, {total_ft:,.0f} ft in total).",
                "Untagged runs cannot be priced. Confirm sizes before issuing for construction.",
                None, {"untagged_runs": [r.id for r in untagged[:200]], "untagged_ft": round(total_ft, 1)})

    # --- MEP-004 / MEP-012: size logic ------------------------------------
    if discipline == "mechanical":
        sized = [r for r in runs if r.width_in and r.tag]
        by_service: dict[str, list[LinearRun]] = collections.defaultdict(list)
        for r in sized:
            by_service[r.service or "?"].append(r)
        for svc, group in by_service.items():
            group.sort(key=lambda r: -(r.width_in or 0))
            if len(group) < 3:
                continue
        # Undersized branch into a large terminal.
        if runs and detections:
            idx = _RunIndex(runs)
            flagged = 0
            for d in detections:
                if d.category_key not in ("square_supply_diffuser_4way", "round_supply_diffuser"):
                    continue
                neck = d.attributes.get("neck_dia_pt") or d.attributes.get("outer_dia_pt")
                if not neck:
                    continue
                neck_in = scale.to_inches(float(neck))
                cx, cy = _centre(d.bbox_pt)
                near = [r for r in idx.near(cx, cy, 40.0) if r.width_in and _dist_point_run(cx, cy, r) <= 40.0]
                if not near:
                    continue
                feed = max(near, key=lambda r: r.width_in or 0)
                if (feed.width_in or 0) + 0.5 < neck_in * 0.75 and flagged < max_findings_per_rule:
                    flagged += 1
                    add("MEP-012",
                        f"{d.category} with a {neck_in:.0f}\" neck appears to be fed by a "
                        f"{feed.width_in:.0f}\" branch (run #{feed.id}).",
                        "Confirm the branch size against the airflow schedule.",
                        d.bbox_pt, {"detection_id": d.id, "run_id": feed.id})

    # --- MEP-005 / MEP-006: fire damper logic -----------------------------
    dampers = [d for d in detections if d.category_key == "fire_damper"]
    if dampers and runs:
        idx = _RunIndex(runs)
        for d in dampers[:max_findings_per_rule]:
            cx, cy = _centre(d.bbox_pt)
            near = [r for r in idx.near(cx, cy, 24.0) if _dist_point_run(cx, cy, r) <= 24.0]
            if not near:
                add("MEP-005",
                    f"Fire damper at ({d.bbox_pt[0]:.0f}, {d.bbox_pt[1]:.0f}) is not on any traced duct run.",
                    "Confirm the damper location against the rated wall it serves, or remove a stale symbol.",
                    d.bbox_pt, {"detection_id": d.id})

    # --- MEP-007: very long uninterrupted runs ----------------------------
    if runs:
        lengths = sorted(r.length_ft for r in runs)
        if len(lengths) >= 12:
            p95 = lengths[int(len(lengths) * 0.95)]
            threshold = max(p95 * 2.2, 120.0)
            for r in runs:
                if r.length_ft >= threshold:
                    add("MEP-007",
                        f"Run #{r.id} is {r.length_label} with no branch — well beyond the typical "
                        f"{p95:,.0f} ft on this sheet.",
                        "Check for missed fittings or an object traced through a fitting.",
                        r.bbox, {"run_id": r.id})

    # --- MEP-009: unidentified repeated glyphs ----------------------------
    unknown = [g for g in glyphs if getattr(g, "source", "") == "mined" and getattr(g, "count", 0) >= 6]
    unknown.sort(key=lambda g: -g.count)
    for g in unknown[:8]:
        add("MEP-009",
            f"A {g.width_pt:.0f} x {g.height_pt:.0f} pt symbol repeats {g.count} times on this sheet "
            f"but is not in the component library.",
            "Name it once and every occurrence — here and on future drawings — is counted automatically.",
            g.instances[0] if g.instances else None,
            {"glyph_id": g.glyph_id, "count": g.count})

    # --- MEP-010: existing services ---------------------------------------
    existing = [r for r in runs if r.status == "existing"]
    if existing:
        total = sum(r.length_ft for r in existing)
        add("MEP-010",
            f"{len(existing)} runs totalling {total:,.0f} ft are tagged as existing (E).",
            "Confirm demolition, reuse and reconnection scope for these services.",
            None, {"run_ids": [r.id for r in existing[:200]], "length_ft": round(total, 1)})

    # --- MEP-011: terminal density ----------------------------------------
    terminals = [d for d in detections if d.category_key in AIR_TERMINALS]
    if len(terminals) >= 6:
        pts = [_centre(d.bbox_pt) for d in terminals]
        nn: list[float] = []
        for i, (x, y) in enumerate(pts):
            best = min(
                (math.hypot(x - u, y - v) for j, (u, v) in enumerate(pts) if j != i),
                default=0.0,
            )
            if best:
                nn.append(scale.to_feet(best))
        if nn:
            nn.sort()
            median = nn[len(nn) // 2]
            if median < 5.0 or median > 26.0:
                add("MEP-011",
                    f"Median spacing between air terminals is {median:.1f} ft "
                    f"({'tight' if median < 5 else 'sparse'} versus the usual 8-20 ft).",
                    "Worth a sanity check against the room layout and airflow schedule.",
                    None, {"median_spacing_ft": round(median, 1), "terminals": len(terminals)})

    findings.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.rule_id))
    return findings


def summarise_findings(findings: Iterable[Finding]) -> dict:
    by_sev: collections.Counter = collections.Counter()
    by_rule: collections.Counter = collections.Counter()
    for f in findings:
        if f.status == "dismissed":
            continue
        by_sev[f.severity] += 1
        by_rule[f.rule_id] += 1
    return {
        "total": sum(by_sev.values()),
        "by_severity": {s: by_sev.get(s, 0) for s in SEVERITIES},
        "by_rule": [
            {"rule_id": rid, "title": RULES_BY_ID[rid].title, "count": n,
             "severity": RULES_BY_ID[rid].severity}
            for rid, n in by_rule.most_common()
        ],
    }
