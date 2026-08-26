"""
End-to-end analysis of a submitted drawing set.

One call takes a PDF and returns everything the product shows: classified
sheets, detected components with counts, traced and measured runs, validation
findings, and the cross-discipline clash screen. Progress is reported as it goes
so the UI can show real work rather than a spinner.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .clash import SheetSystems, detect_clashes, infer_level, summarise_clashes
from .discipline import DISCIPLINE_LABELS, classify_discipline
from .linear import LinearResult, build_connectivity, measure_linear, weight_classes
from .pdfdoc import DrawingDocument, Sheet
from .scale import ScaleInfo, detect_scale, manual_scale
from .symbols import Detection, SymbolLibrary, detect_symbols, summarise_counts
from .validate import Finding, run_validation, summarise_findings

ProgressFn = Callable[[str, float, str], None]

#: Which measurement a discipline calls for.
LINEAR_KIND = {
    "mechanical": "duct",
    "plumbing": "pipe",
    "fire_protection": "pipe",
}


@dataclass
class SheetOptions:
    scale_inches_per_pt: float | None = None
    scale_label: str | None = None
    layer_weights: list[float] | None = None
    discipline: str | None = None
    enabled: bool = True


@dataclass
class AnalysisOptions:
    max_sheets: int = 40
    detect_symbols: bool = True
    measure_linear: bool = True
    validate: bool = True
    clash: bool = True
    only_plans: bool = True
    max_runs_returned: int = 4000
    per_sheet: dict[int, SheetOptions] = field(default_factory=dict)


def _sheet_payload(
    sheet: Sheet,
    page_number: int,
    disc,
    scale: ScaleInfo,
    detections: Sequence[Detection],
    glyphs: Sequence,
    linear: LinearResult | None,
    connectivity: dict,
    findings: Sequence[Finding],
    elapsed: float,
    file_name: str,
) -> dict:
    return {
        "page_number": page_number,
        "file_name": file_name,
        "sheet_label": disc.sheet_number or f"Page {page_number}",
        "sheet_title": disc.sheet_title,
        "discipline": disc.discipline,
        "discipline_label": DISCIPLINE_LABELS.get(disc.discipline, disc.discipline),
        "discipline_confidence": disc.confidence,
        "discipline_evidence": disc.evidence,
        "is_plan": disc.is_plan,
        "level": infer_level(disc.sheet_number, disc.sheet_title, file_name),
        "width_pt": round(sheet.info.width_pt, 2),
        "height_pt": round(sheet.info.height_pt, 2),
        "rotation": sheet.info.rotation,
        "primitive_count": sheet.info.n_primitives,
        "foreground_count": sheet.info.n_foreground,
        "scale": scale.as_dict(),
        "weight_classes": weight_classes(sheet)[:8],
        "detections": [d.as_dict() for d in detections],
        "counts": summarise_counts(detections),
        "glyphs": [g.as_dict(max_instances=400) for g in glyphs[:60]],
        "linear": linear.as_dict() if linear else None,
        "connectivity": {
            "networks": connectivity.get("networks", [])[:200],
            "isolated_runs": connectivity.get("isolated_runs", [])[:400],
            "edge_count": len(connectivity.get("edges", [])),
        } if connectivity else None,
        "findings": [f.as_dict() for f in findings],
        "findings_summary": summarise_findings(findings),
        "elapsed_s": round(elapsed, 2),
    }


def analyse_document(
    path: str,
    options: AnalysisOptions | None = None,
    library: SymbolLibrary | None = None,
    progress: ProgressFn | None = None,
) -> dict:
    """Analyse every relevant sheet in a drawing set."""
    opts = options or AnalysisOptions()
    started = time.time()
    file_name = os.path.basename(path)

    def report(stage: str, pct: float, message: str) -> None:
        if progress:
            try:
                progress(stage, max(0.0, min(1.0, pct)), message)
            except Exception:
                pass

    doc = DrawingDocument(path)
    try:
        total_pages = doc.page_count
        report("open", 0.02, f"Opened {file_name} — {total_pages} page(s)")

        # --- Pass 1: classify every page cheaply, pick the ones worth analysing.
        candidates: list[tuple[int, object]] = []
        cap = min(total_pages, 400)
        for i in range(cap):
            disc = classify_discipline(doc.quick_sheet(i), file_name)
            candidates.append((i, disc))
            if i % 5 == 0 or i == cap - 1:
                report("classify", 0.02 + 0.13 * (i + 1) / max(1, cap),
                       f"Triaged page {i + 1}/{cap} — {DISCIPLINE_LABELS.get(disc.discipline, disc.discipline)}")

        def worth_it(idx: int, disc) -> bool:
            per = opts.per_sheet.get(idx)
            if per and not per.enabled:
                return False
            if per and per.discipline:
                return True
            if opts.only_plans and not disc.is_plan:
                return False
            return disc.discipline in ("mechanical", "plumbing", "electrical", "fire_protection")

        selected = [(i, d) for i, d in candidates if worth_it(i, d)]
        if not selected:
            # Never return nothing: fall back to the densest pages.
            selected = sorted(candidates, key=lambda t: -doc.quick_sheet(t[0]).info.n_foreground)[:3]
        selected = selected[: opts.max_sheets]

        report("plan", 0.16, f"Analysing {len(selected)} sheet(s) of {total_pages}")

        sheets_out: list[dict] = []
        systems: list[SheetSystems] = []

        for n, (idx, disc) in enumerate(selected):
            t0 = time.time()
            sheet = doc.sheet(idx)
            per = opts.per_sheet.get(idx) or SheetOptions()
            if per.discipline:
                disc.discipline = per.discipline

            base = 0.16 + 0.74 * n / max(1, len(selected))
            span = 0.74 / max(1, len(selected))
            label = disc.sheet_number or f"page {idx + 1}"

            report("detect", base + span * 0.1, f"Detecting components on {label}")
            detections: list[Detection] = []
            glyphs: list = []
            if opts.detect_symbols:
                detections, glyphs = detect_symbols(sheet, library=library, discipline=disc.discipline)

            report("scale", base + span * 0.4, f"Establishing drawing scale for {label}")
            if per.scale_inches_per_pt:
                scale = manual_scale(per.scale_inches_per_pt, per.scale_label)
            else:
                scale = detect_scale(sheet, [d.as_dict() for d in detections])

            kind = LINEAR_KIND.get(disc.discipline)
            linear: LinearResult | None = None
            connectivity: dict = {}
            if opts.measure_linear and kind:
                report("measure", base + span * 0.55, f"Tracing and measuring {kind}work on {label}")
                linear = measure_linear(
                    sheet, scale, kind,
                    exclude_boxes=[d.bbox_pt for d in detections],
                    override_weights=per.layer_weights,
                )
                connectivity = build_connectivity(linear.runs)

            findings: list[Finding] = []
            if opts.validate:
                report("validate", base + span * 0.85, f"Running design validation on {label}")
                findings = run_validation(
                    detections, linear.runs if linear else [], connectivity, scale,
                    disc.discipline, idx, disc.sheet_number or f"Page {idx + 1}", glyphs,
                )

            payload = _sheet_payload(
                sheet, idx + 1, disc, scale, detections, glyphs, linear, connectivity,
                findings, time.time() - t0, file_name,
            )
            sheets_out.append(payload)

            if linear:
                systems.append(SheetSystems(
                    sheet_key=f"{file_name}#{idx}",
                    sheet_label=payload["sheet_label"],
                    discipline=disc.discipline,
                    level=payload["level"],
                    scale=scale,
                    runs=linear.runs,
                    equipment=[d for d in detections if d.category_key in ("water_source_heat_pump",)],
                    width_pt=sheet.info.width_pt,
                    height_pt=sheet.info.height_pt,
                ))

            # Release page geometry we no longer need — bid sets get large.
            doc.release(idx)

        clashes: list = []
        if opts.clash and len(systems) > 1:
            report("clash", 0.93, "Screening for cross-discipline conflicts")
            clashes = detect_clashes(systems)

        report("summarise", 0.98, "Building project summary")
        result = {
            "file_name": file_name,
            "page_count": total_pages,
            "analysed_sheets": len(sheets_out),
            "sheets": sheets_out,
            "sheet_index": [
                {
                    "page_number": s["page_number"], "sheet_label": s["sheet_label"],
                    "sheet_title": s["sheet_title"], "discipline": s["discipline"],
                    "discipline_label": s["discipline_label"], "level": s["level"],
                    "detections": len(s["detections"]),
                    "runs": (s["linear"] or {}).get("run_count", 0),
                    "length_ft": (s["linear"] or {}).get("total_length_ft", 0),
                    "findings": s["findings_summary"]["total"],
                    "scale": s["scale"]["label"],
                }
                for s in sheets_out
            ],
            "clashes": [c.as_dict() for c in clashes],
            "clash_summary": summarise_clashes(clashes),
            "totals": project_totals(sheets_out),
            "elapsed_s": round(time.time() - started, 2),
        }
        report("done", 1.0, f"Finished in {result['elapsed_s']:.1f}s")
        return result
    finally:
        doc.close()


def project_totals(sheets: Sequence[dict]) -> dict:
    """Roll every sheet up into the numbers a project manager actually wants."""
    counts: dict[str, dict] = {}
    duct_ft = 0.0
    pipe_ft = 0.0
    runs = 0
    findings = 0
    by_severity: dict[str, int] = {}

    for sh in sheets:
        for c in sh.get("counts", []):
            row = counts.setdefault(c["category"], {
                "category": c["category"], "category_key": c.get("category_key"),
                "category_group": c.get("category_group"),
                "trade": c.get("trade"), "unit": c.get("unit", "EA"), "count": 0, "sheets": 0,
            })
            row["count"] += c["count"]
            row["sheets"] += 1
        lin = sh.get("linear") or {}
        if lin:
            runs += lin.get("run_count", 0)
            if lin.get("kind") == "duct":
                duct_ft += lin.get("total_length_ft", 0.0)
            else:
                pipe_ft += lin.get("total_length_ft", 0.0)
        fs = sh.get("findings_summary") or {}
        findings += fs.get("total", 0)
        for sev, n in (fs.get("by_severity") or {}).items():
            by_severity[sev] = by_severity.get(sev, 0) + n

    return {
        "components": sorted(counts.values(), key=lambda r: -r["count"]),
        "component_total": sum(r["count"] for r in counts.values()),
        "duct_length_ft": round(duct_ft, 1),
        "pipe_length_ft": round(pipe_ft, 1),
        "run_count": runs,
        "finding_count": findings,
        "findings_by_severity": by_severity,
    }
