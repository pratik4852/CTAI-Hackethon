"""
Structured output: COCO, CSV, bill of quantities, IFC and BCF.

The deliverable of a takeoff is not a screenshot — it is data that flows into
the next tool. Every artefact here is written so it can be opened directly by
the thing that needs it: COCO for ML pipelines, CSV for estimating, IFC for
Revit/Navisworks, BCF-style issues for coordination meetings.
"""

from __future__ import annotations

import csv
import io
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Iterable, Sequence

from .pdfdoc import GT_DPI, bbox_pt_to_px
from .symbols import CATALOGUE_BY_NAME, Detection

ISO = "%Y-%m-%dT%H:%M:%S"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(ISO)


# ---------------------------------------------------------------------------
# COCO
# ---------------------------------------------------------------------------


def to_coco(sheets: Sequence[dict], dpi: float = GT_DPI) -> dict:
    """
    COCO instance annotations, matching the format the dataset ships in.

    Boxes are emitted in the dataset's own 150-DPI pixel space so results drop
    straight into an existing evaluation harness.
    """
    categories: dict[str, int] = {}
    images: list[dict] = []
    annotations: list[dict] = []
    ann_id = 0

    for image_id, sh in enumerate(sheets, start=1):
        images.append({
            "id": image_id,
            "file_name": sh.get("file_name") or f"{sh.get('sheet_label') or 'sheet'}_{image_id}.png",
            "width": int(round(sh["width_pt"] * dpi / 72.0)),
            "height": int(round(sh["height_pt"] * dpi / 72.0)),
            "page": sh.get("page_number", image_id),
            "sheet_label": sh.get("sheet_label", ""),
            "discipline": sh.get("discipline", "unknown"),
            "scale": sh.get("scale", {}).get("label"),
        })
        for det in sh.get("detections", []):
            name = det["category"]
            if name not in categories:
                categories[name] = len(categories) + 1
            x, y, w, h = bbox_pt_to_px(det["bbox_pt"], dpi)
            ann_id += 1
            annotations.append({
                "id": ann_id,
                "image_id": image_id,
                "category_id": categories[name],
                "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "area": round(w * h, 2),
                "iscrowd": 0,
                "score": det.get("confidence"),
                "trade": det.get("trade"),
                "detector": det.get("detector"),
                "rationale": det.get("rationale"),
                "review": det.get("review", "unreviewed"),
            })

    return {
        "info": {
            "description": "MEPIQ — quantifiable object detection on MEP construction drawings",
            "version": "1.0",
            "date_created": _now(),
            "dpi": dpi,
        },
        "licenses": [],
        "images": images,
        "categories": [
            {"id": cid, "name": name,
             "supercategory": (CATALOGUE_BY_NAME[name].category if name in CATALOGUE_BY_NAME else "Discovered")}
            for name, cid in sorted(categories.items(), key=lambda kv: kv[1])
        ],
        "annotations": annotations,
    }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _csv(rows: Sequence[dict], columns: Sequence[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def detections_csv(sheets: Sequence[dict]) -> str:
    rows = []
    for sh in sheets:
        for d in sh.get("detections", []):
            b = d["bbox_pt"]
            rows.append({
                "sheet": sh.get("sheet_label") or sh.get("page_number"),
                "discipline": sh.get("discipline"),
                "category": d["category"],
                "trade": d.get("trade"),
                "confidence": d.get("confidence"),
                "detector": d.get("detector"),
                "x0_pt": round(b[0], 2), "y0_pt": round(b[1], 2),
                "x1_pt": round(b[2], 2), "y1_pt": round(b[3], 2),
                "width_pt": round(b[2] - b[0], 2), "height_pt": round(b[3] - b[1], 2),
                "review": d.get("review", "unreviewed"),
                "rationale": d.get("rationale", ""),
            })
    return _csv(rows, ["sheet", "discipline", "category", "trade", "confidence", "detector",
                       "x0_pt", "y0_pt", "x1_pt", "y1_pt", "width_pt", "height_pt", "review", "rationale"])


def counts_csv(sheets: Sequence[dict]) -> str:
    rows = []
    n = 0
    for sh in sheets:
        for c in sh.get("counts", []):
            n += 1
            rows.append({
                "sr_no": n,
                "sheet": sh.get("sheet_label") or sh.get("page_number"),
                "discipline": sh.get("discipline"),
                "category": c["category"],
                "category_group": c.get("category_group"),
                "trade": c.get("trade"),
                "instance_count": c["count"],
                "unit": c.get("unit", "EA"),
                "mean_confidence": c.get("mean_confidence"),
            })
    return _csv(rows, ["sr_no", "sheet", "discipline", "category", "category_group",
                       "trade", "instance_count", "unit", "mean_confidence"])


def runs_csv(sheets: Sequence[dict]) -> str:
    rows = []
    for sh in sheets:
        for kind in ("duct", "pipe"):
            lin = sh.get("linear") or {}
            if lin.get("kind") != kind:
                continue
            for r in lin.get("runs", []):
                rows.append({
                    "sheet": sh.get("sheet_label") or sh.get("page_number"),
                    "discipline": sh.get("discipline"),
                    "run_id": r["id"],
                    "kind": r["kind"],
                    "service": r.get("service_name"),
                    "size": r.get("size_label"),
                    "status": r.get("status"),
                    "length_ft": r["length_ft"],
                    "length_label": r["length_label"],
                    "width_in": r.get("width_in"),
                    "segments": r["n_segments"],
                    "x0_pt": r["bbox_pt"][0], "y0_pt": r["bbox_pt"][1],
                    "x1_pt": r["bbox_pt"][2], "y1_pt": r["bbox_pt"][3],
                })
    return _csv(rows, ["sheet", "discipline", "run_id", "kind", "service", "size", "status",
                       "length_ft", "length_label", "width_in", "segments",
                       "x0_pt", "y0_pt", "x1_pt", "y1_pt"])


# ---------------------------------------------------------------------------
# Bill of quantities
# ---------------------------------------------------------------------------


def bill_of_quantities(sheets: Sequence[dict]) -> list[dict]:
    """Aggregate the whole project into priceable line items."""
    items: dict[tuple, dict] = {}

    for sh in sheets:
        disc = sh.get("discipline", "unknown")
        for c in sh.get("counts", []):
            key = ("count", disc, c["category"], c.get("unit", "EA"), "")
            row = items.setdefault(key, {
                "section": c.get("category_group", "Components"),
                "discipline": disc,
                "description": c["category"],
                "unit": c.get("unit", "EA"),
                "size": "",
                "quantity": 0.0,
                "sheets": set(),
            })
            row["quantity"] += c["count"]
            row["sheets"].add(sh.get("sheet_label") or str(sh.get("page_number")))

        lin = sh.get("linear") or {}
        for s in lin.get("by_size", []):
            if not s.get("length_ft"):
                continue
            label = "Ductwork" if lin.get("kind") == "duct" else "Piping"
            key = ("linear", disc, label, "LF", s["size"])
            row = items.setdefault(key, {
                "section": label,
                "discipline": disc,
                "description": f"{label} — {s.get('service') or 'unassigned service'}",
                "unit": "LF",
                "size": s["size"],
                "quantity": 0.0,
                "sheets": set(),
            })
            row["quantity"] += s["length_ft"]
            row["sheets"].add(sh.get("sheet_label") or str(sh.get("page_number")))

    out = []
    for i, (_key, row) in enumerate(sorted(items.items(), key=lambda kv: (kv[1]["section"], -kv[1]["quantity"])), 1):
        row = dict(row)
        row["item"] = i
        row["quantity"] = round(row["quantity"], 2)
        row["sheets"] = ", ".join(sorted(row["sheets"])[:12])
        out.append(row)
    return out


def boq_csv(sheets: Sequence[dict]) -> str:
    return _csv(bill_of_quantities(sheets),
                ["item", "section", "discipline", "description", "size", "unit", "quantity", "sheets"])


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------


_IFC_CLASS = {
    "square_supply_diffuser_4way": "IfcAirTerminal",
    "square_return_exhaust_register": "IfcAirTerminal",
    "round_supply_diffuser": "IfcAirTerminal",
    "linear_bar_grille": "IfcAirTerminal",
    "fire_damper": "IfcDamper",
    "water_source_heat_pump": "IfcUnitaryEquipment",
    "flexible_duct": "IfcDuctSegment",
    "elevation_benchmark": "IfcAnnotation",
}


def _ifc_guid(n: int) -> str:
    """A stable, syntactically valid IFC GlobalId."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    v = uuid.uuid5(uuid.NAMESPACE_OID, f"mepiq-{n}").int
    out = []
    for _ in range(22):
        out.append(chars[v % 64])
        v //= 64
    return "".join(reversed(out))


def to_ifc(sheets: Sequence[dict], project_name: str = "MEPIQ Takeoff") -> str:
    """
    An IFC4 SPF file placing every detected component and traced run in plan.

    Elevations are unknown from a 2-D sheet, so every element is placed at the
    storey datum and flagged as 2-D-derived. That is honest and still useful:
    the file opens in Revit, Navisworks or Solibri as a coordination underlay
    with real quantities attached.
    """
    lines: list[str] = []
    eid = 0

    def nxt() -> int:
        nonlocal eid
        eid += 1
        return eid

    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace("'", "\\'")

    header = f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]','2D-derived MEP takeoff'),'2;1');
FILE_NAME('{esc(project_name)}.ifc','{_now()}',('MEPIQ'),('MEPIQ'),'MEPIQ 1.0','MEPIQ','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;"""
    lines.append(header)

    person = nxt(); lines.append(f"#{person}=IFCPERSON($,'MEPIQ',$,$,$,$,$,$);")
    org = nxt(); lines.append(f"#{org}=IFCORGANIZATION($,'MEPIQ',$,$,$);")
    pao = nxt(); lines.append(f"#{pao}=IFCPERSONANDORGANIZATION(#{person},#{org},$);")
    app = nxt(); lines.append(f"#{app}=IFCAPPLICATION(#{org},'1.0','MEPIQ','MEPIQ');")
    owner = nxt(); lines.append(f"#{owner}=IFCOWNERHISTORY(#{pao},#{app},$,.ADDED.,$,$,$,0);")

    dim = nxt(); lines.append(f"#{dim}=IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0);")
    unit_l = nxt(); lines.append(f"#{unit_l}=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);")
    unit_a = nxt(); lines.append(f"#{unit_a}=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);")
    units = nxt(); lines.append(f"#{units}=IFCUNITASSIGNMENT((#{unit_l},#{unit_a}));")

    origin = nxt(); lines.append(f"#{origin}=IFCCARTESIANPOINT((0.,0.,0.));")
    axis = nxt(); lines.append(f"#{axis}=IFCAXIS2PLACEMENT3D(#{origin},$,$);")
    ctx = nxt(); lines.append(f"#{ctx}=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{axis},$);")
    project = nxt()
    lines.append(f"#{project}=IFCPROJECT('{_ifc_guid(project)}',#{owner},'{esc(project_name)}',$,$,$,$,(#{ctx}),#{units});")

    site_pl = nxt(); lines.append(f"#{site_pl}=IFCLOCALPLACEMENT($,#{axis});")
    site = nxt(); lines.append(f"#{site}=IFCSITE('{_ifc_guid(site)}',#{owner},'Site',$,$,#{site_pl},$,$,.ELEMENT.,$,$,$,$,$);")
    building = nxt()
    lines.append(f"#{building}=IFCBUILDING('{_ifc_guid(building)}',#{owner},'Building',$,$,#{site_pl},$,$,.ELEMENT.,$,$,$);")

    rel = nxt(); lines.append(f"#{rel}=IFCRELAGGREGATES('{_ifc_guid(rel)}',#{owner},$,$,#{project},(#{site}));")
    rel2 = nxt(); lines.append(f"#{rel2}=IFCRELAGGREGATES('{_ifc_guid(rel2)}',#{owner},$,$,#{site},(#{building}));")

    PT_TO_M = 0.0254 / 72.0  # placeholder replaced per-sheet using the real scale

    for si, sh in enumerate(sheets):
        scale = sh.get("scale") or {}
        in_per_pt = float(scale.get("inches_per_pt") or 1.0)
        to_m = in_per_pt * 0.0254

        storey_pl = nxt(); lines.append(f"#{storey_pl}=IFCLOCALPLACEMENT(#{site_pl},#{axis});")
        storey = nxt()
        label = esc(sh.get("sheet_label") or f"Sheet {si + 1}")
        lines.append(
            f"#{storey}=IFCBUILDINGSTOREY('{_ifc_guid(storey)}',#{owner},'{label}',"
            f"'{esc(sh.get('discipline', ''))}',$,#{storey_pl},$,$,.ELEMENT.,0.);"
        )
        agg = nxt(); lines.append(f"#{agg}=IFCRELAGGREGATES('{_ifc_guid(agg)}',#{owner},$,$,#{building},(#{storey}));")

        contained: list[int] = []

        for det in sh.get("detections", []):
            b = det["bbox_pt"]
            cx = (b[0] + b[2]) / 2.0 * to_m
            cy = -(b[1] + b[3]) / 2.0 * to_m   # PDF y grows downward
            key = det.get("category_key", "")
            cls = _IFC_CLASS.get(key, "IfcBuildingElementProxy")
            p = nxt(); lines.append(f"#{p}=IFCCARTESIANPOINT(({cx:.6f},{cy:.6f},0.));")
            a3 = nxt(); lines.append(f"#{a3}=IFCAXIS2PLACEMENT3D(#{p},$,$);")
            pl = nxt(); lines.append(f"#{pl}=IFCLOCALPLACEMENT(#{storey_pl},#{a3});")
            e = nxt()
            name = esc(det["category"])
            tag = esc(f"conf={det.get('confidence')}")
            if cls == "IfcAirTerminal":
                lines.append(f"#{e}={cls}('{_ifc_guid(e)}',#{owner},'{name}',$,$,#{pl},$,'{tag}',$);")
            elif cls == "IfcDamper":
                lines.append(f"#{e}={cls}('{_ifc_guid(e)}',#{owner},'{name}',$,$,#{pl},$,'{tag}',.FIREDAMPER.);")
            else:
                lines.append(f"#{e}={cls}('{_ifc_guid(e)}',#{owner},'{name}',$,$,#{pl},$,'{tag}');")
            contained.append(e)

        lin = sh.get("linear") or {}
        seg_cls = "IFCDUCTSEGMENT" if lin.get("kind") == "duct" else "IFCPIPESEGMENT"
        for r in lin.get("runs", [])[:4000]:
            pts = r.get("points") or []
            if len(pts) < 2:
                continue
            ids = []
            for (x, y) in pts:
                q = nxt()
                lines.append(f"#{q}=IFCCARTESIANPOINT(({x * to_m:.6f},{-y * to_m:.6f},0.));")
                ids.append(q)
            poly = nxt()
            lines.append(f"#{poly}=IFCPOLYLINE(({','.join(f'#{i}' for i in ids)}));")
            shape = nxt()
            lines.append(f"#{shape}=IFCSHAPEREPRESENTATION(#{ctx},'Axis','Curve2D',(#{poly}));")
            prod = nxt()
            lines.append(f"#{prod}=IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}));")
            pl = nxt(); lines.append(f"#{pl}=IFCLOCALPLACEMENT(#{storey_pl},#{axis});")
            e = nxt()
            desc = esc(f"{r.get('size_label') or ''} {r.get('service_name') or ''}".strip())
            lines.append(
                f"#{e}={seg_cls}('{_ifc_guid(e)}',#{owner},'Run {r['id']}','{desc}',$,#{pl},#{prod},"
                f"'{r.get('length_ft')} LF',$);"
            )
            contained.append(e)

        if contained:
            for chunk_start in range(0, len(contained), 500):
                chunk = contained[chunk_start:chunk_start + 500]
                rc = nxt()
                lines.append(
                    f"#{rc}=IFCRELCONTAINEDINSPATIALSTRUCTURE('{_ifc_guid(rc)}',#{owner},$,$,"
                    f"({','.join(f'#{i}' for i in chunk)}),#{storey});"
                )

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BCF-style issue export
# ---------------------------------------------------------------------------


def issues_json(findings: Sequence[dict], clashes: Sequence[dict] = ()) -> dict:
    """A BCF-shaped issue list that coordination tools and spreadsheets can read."""
    topics = []
    for i, f in enumerate(findings, 1):
        topics.append({
            "guid": _ifc_guid(10_000 + i),
            "topic_type": "Issue",
            "topic_status": f.get("status", "open").title(),
            "title": f"{f['rule_id']} — {f['title']}",
            "priority": f["severity"],
            "labels": [f.get("discipline", ""), "design-validation"],
            "description": f["message"],
            "recommendation": f.get("recommendation", ""),
            "sheet": f.get("sheet_label"),
            "location_pt": f.get("location_pt"),
            "creation_date": _now(),
            "created_author": "MEPIQ",
        })
    for i, c in enumerate(clashes, 1):
        topics.append({
            "guid": _ifc_guid(20_000 + i),
            "topic_type": "Clash",
            "topic_status": c.get("status", "open").title(),
            "title": f"{c['trade_a'].title()} / {c['trade_b'].title()} coordination",
            "priority": c["severity"],
            "labels": [c["trade_a"], c["trade_b"], "clash", c.get("level") or ""],
            "description": c["message"],
            "recommendation": "Resolve in coordination; confirm elevations before routing.",
            "sheet": f"{c['sheet_a']} / {c['sheet_b']}",
            "location_pt": c.get("location_pt"),
            "creation_date": _now(),
            "created_author": "MEPIQ",
        })
    return {"version": "2.1", "generated": _now(), "generator": "MEPIQ", "topics": topics}


def findings_csv(findings: Sequence[dict]) -> str:
    rows = [{
        "rule_id": f["rule_id"], "title": f["title"], "severity": f["severity"],
        "sheet": f.get("sheet_label"), "message": f["message"],
        "recommendation": f.get("recommendation", ""), "status": f.get("status", "open"),
        "x_pt": (f.get("location_pt") or [None])[0],
        "y_pt": (f.get("location_pt") or [None, None])[1],
    } for f in findings]
    return _csv(rows, ["rule_id", "title", "severity", "sheet", "message", "recommendation", "status", "x_pt", "y_pt"])


def clashes_csv(clashes: Sequence[dict]) -> str:
    rows = [{
        "id": c["id"], "trade_a": c["trade_a"], "trade_b": c["trade_b"],
        "sheet_a": c["sheet_a"], "sheet_b": c["sheet_b"], "level": c.get("level"),
        "kind": c["kind"], "ref_a": c["ref_a"], "ref_b": c["ref_b"],
        "overlap_in": c["overlap_in"], "clearance_required_in": c["clearance_required_in"],
        "severity": c["severity"], "message": c["message"], "status": c.get("status", "open"),
    } for c in clashes]
    return _csv(rows, ["id", "trade_a", "trade_b", "sheet_a", "sheet_b", "level", "kind",
                       "ref_a", "ref_b", "overlap_in", "clearance_required_in", "severity", "message", "status"])
