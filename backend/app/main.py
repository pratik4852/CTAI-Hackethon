"""
MEPIQ API.

A small, explicit FastAPI application: upload drawings, run the analysis as a
background job with live progress, read results, review and correct them, teach
the symbol library, export structured data, and talk to the copilot.
"""

from __future__ import annotations

import io
import json
import shutil
import math
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from mepiq_core import __version__ as core_version
from mepiq_core.exporters import (
    boq_csv, clashes_csv, counts_csv, detections_csv, findings_csv,
    issues_json, runs_csv, to_coco, to_ifc,
)
from mepiq_core.pdfdoc import DrawingDocument, px_to_pt
from mepiq_core.pipeline import AnalysisOptions, SheetOptions, analyse_document, project_totals
from mepiq_core.scale import STANDARD_SCALES, manual_scale, scale_from_two_points
from mepiq_core.symbols import CATALOGUE, SymbolLibrary
from mepiq_core.validate import RULES

from . import copilot, store
from .config import settings

app = FastAPI(
    title="MEPIQ API",
    version=settings.version,
    description="Design management for MEP drawings — detection, measurement, validation and copilot.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=max(1, settings.workers), thread_name_prefix="mepiq")
_library = SymbolLibrary(settings.library_path)
_library_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    notes: str = ""


class SheetOverride(BaseModel):
    page_number: int
    scale_inches_per_pt: float | None = None
    scale_label: str | None = None
    layer_weights: list[float] | None = None
    discipline: str | None = None
    enabled: bool = True


class AnalyseRequest(BaseModel):
    document_id: str | None = None
    max_sheets: int | None = None
    only_plans: bool = True
    detect_symbols: bool = True
    measure_linear: bool = True
    validate_design: bool = True
    clash: bool = True
    overrides: list[SheetOverride] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    document_id: str
    page_number: int
    target_type: str
    target_id: str
    action: str
    payload: dict = Field(default_factory=dict)
    author: str = ""


class LearnGlyphRequest(BaseModel):
    glyph_id: str
    label: str
    trade: str = ""
    category: str = ""
    note: str = ""
    size_pt: list[float] | None = None


class CalibrateRequest(BaseModel):
    document_id: str
    page_number: int
    p1: list[float]
    p2: list[float]
    real_feet: float = 0.0
    real_inches: float = 0.0


class ChatRequest(BaseModel):
    message: str
    document_id: str | None = None
    use_llm: bool = True


class VisualSearchRequest(BaseModel):
    document_id: str
    page_number: int
    bbox_pt: list[float]
    min_score: float = 0.85
    allow_mirror: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_or_404(pid: str) -> dict:
    p = store.get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _document_or_404(did: str) -> dict:
    d = store.get_document(did)
    if not d:
        raise HTTPException(404, "Document not found")
    return d


def _primary_document(project: dict, document_id: str | None = None) -> dict:
    docs = project.get("documents") or []
    if not docs:
        raise HTTPException(400, "This project has no drawings yet")
    if document_id:
        for d in docs:
            if d["id"] == document_id:
                return d
        raise HTTPException(404, "Document not found in this project")
    with_result = [d for d in docs if d.get("has_result")]
    return (with_result or docs)[0]


def _result_or_404(document_id: str) -> dict:
    r = store.load_result(document_id)
    if not r:
        raise HTTPException(409, "This drawing has not been analysed yet")
    return r


def _apply_reviews(result: dict, document_id: str) -> dict:
    """Overlay the reviewer's decisions onto a stored analysis."""
    rmap = store.review_map(document_id)
    if not rmap:
        return result
    for sheet in result.get("sheets", []):
        page = sheet["page_number"]
        for det in sheet.get("detections", []):
            r = rmap.get((page, "detection", str(det["id"])))
            if not r:
                continue
            det["review"] = r["action"]
            newcat = (r.get("payload") or {}).get("category")
            if r["action"] == "corrected" and newcat:
                det["category"] = newcat
                det["confidence"] = 1.0
                det["detector"] = "manual"
                det["rationale"] = "Corrected by reviewer"
        for det in list(sheet.get("detections", [])):
            pass
        # Manually added detections
        for key, r in rmap.items():
            if key[0] != page or key[1] != "detection" or r["action"] != "added":
                continue
            p = r.get("payload") or {}
            if not p.get("bbox_pt"):
                continue
            sheet.setdefault("detections", []).append({
                "id": int(key[2]) if str(key[2]).isdigit() else 900000 + r["id"],
                "category": p.get("category", "Manual component"),
                "category_key": p.get("category_key", "manual"),
                "trade": p.get("trade", ""), "bbox_pt": p["bbox_pt"], "confidence": 1.0,
                "detector": "manual", "rationale": "Added by reviewer", "attributes": {},
                "glyph_id": None, "review": "confirmed",
                "center_pt": [(p["bbox_pt"][0] + p["bbox_pt"][2]) / 2, (p["bbox_pt"][1] + p["bbox_pt"][3]) / 2],
            })
        sheet["detections"] = [d for d in sheet.get("detections", []) if d.get("review") != "rejected"]

        from mepiq_core.symbols import Detection, summarise_counts

        sheet["counts"] = summarise_counts([
            Detection(d["category"], d.get("category_key", ""), d.get("trade", ""), d["bbox_pt"],
                      d.get("confidence", 0.0), d.get("detector", ""), review=d.get("review", "unreviewed"))
            for d in sheet["detections"]
        ])
        for f in sheet.get("findings", []):
            r = rmap.get((page, "finding", f["rule_id"] + "@" + str(f.get("location_pt"))))
            if r:
                f["status"] = r["action"]
    for c in result.get("clashes", []):
        r = rmap.get((0, "clash", str(c["id"])))
        if r:
            c["status"] = r["action"]
    result["totals"] = project_totals(result.get("sheets", []))
    return result


def _load_and_apply(document_id: str) -> dict:
    return _apply_reviews(_result_or_404(document_id), document_id)


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": settings.version,
        "core_version": core_version,
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.openai_model if settings.llm_enabled else None,
        "time": time.time(),
    }


@app.get("/api/catalogue")
def catalogue() -> dict:
    return {
        "symbols": [
            {"key": s.key, "name": s.name, "trade": s.trade, "category": s.category,
             "description": s.description, "unit": s.unit}
            for s in CATALOGUE.values()
        ],
        "rules": [r.as_dict() for r in RULES],
        "standard_scales": [
            {"label": k, "inches_per_pt": v, "feet_per_pt": v / 12.0}
            for k, v in STANDARD_SCALES.items()
        ],
        "copilot_suggestions": copilot.SUGGESTIONS,
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects")
def list_projects() -> dict:
    return {"projects": store.list_projects()}


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectCreate) -> dict:
    return store.create_project(body.name.strip(), body.notes)


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    return _project_or_404(pid)


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str) -> Response:
    _project_or_404(pid)
    store.delete_project(pid)
    return Response(status_code=204)


@app.post("/api/projects/{pid}/documents", status_code=201)
async def upload_documents(pid: str, files: list[UploadFile] = File(...)) -> dict:
    project = _project_or_404(pid)
    limit = settings.max_upload_mb * 1024 * 1024
    added: list[dict] = []

    for f in files:
        name = os.path.basename(f.filename or "drawing.pdf")
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, f"{name}: only PDF drawings are supported")
        did = store.new_id("doc_")
        dest = settings.uploads / f"{did}.pdf"
        size = 0
        with open(dest, "wb") as out:
            while chunk := await f.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"{name} exceeds the {settings.max_upload_mb} MB limit")
                out.write(chunk)
        try:
            with DrawingDocument(dest) as doc:
                pages = doc.page_count
        except Exception:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"{name}: could not be read as a PDF")
        rec = store.add_document(pid, name, dest, size, pages)
        added.append(rec)

    store.touch_project(pid, "uploaded")
    return {"documents": added, "project": store.get_project(pid)}


@app.delete("/api/documents/{did}", status_code=204)
def delete_document(did: str) -> Response:
    d = _document_or_404(did)
    with store.tx() as c:
        c.execute("DELETE FROM documents WHERE id=?", (did,))
    Path(d["stored_path"]).unlink(missing_ok=True)
    store.result_path(did).unlink(missing_ok=True)
    shutil.rmtree(settings.data_dir / "renders" / did, ignore_errors=True)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _run_analysis(job_id: str, project_id: str, document: dict, opts: AnalysisOptions) -> None:
    def progress(stage: str, pct: float, message: str) -> None:
        store.update_job(job_id, status="running", stage=stage, progress=round(pct, 4), message=message)

    try:
        store.update_job(job_id, status="running", stage="starting", progress=0.01,
                         message=f"Analysing {document['file_name']}")
        with _library_lock:
            lib = SymbolLibrary(settings.library_path)
        result = analyse_document(document["stored_path"], opts, library=lib, progress=progress)
        result["file_name"] = document["file_name"]
        for _s in result.get("sheets", []):
            _s["file_name"] = document["file_name"]
        result["document_id"] = document["id"]
        result["project_id"] = project_id
        store.save_result(document["id"], result)
        store.set_page_count(document["id"], result.get("page_count", 0))
        store.update_job(job_id, status="succeeded", stage="done", progress=1.0,
                         message=f"Analysed {result.get('analysed_sheets')} sheet(s) in {result.get('elapsed_s')}s",
                         finished_at=time.time())
        store.touch_project(project_id, "analysed")
    except Exception as exc:  # pragma: no cover
        store.update_job(job_id, status="failed", stage="error", message=str(exc),
                         error=traceback.format_exc()[-4000:], finished_at=time.time())
        store.touch_project(project_id, "failed")


@app.post("/api/projects/{pid}/analyse", status_code=202)
def analyse(pid: str, body: AnalyseRequest = Body(default=AnalyseRequest())) -> dict:
    project = _project_or_404(pid)
    doc = _primary_document(project, body.document_id)

    per: dict[int, SheetOptions] = {}
    for o in body.overrides:
        per[o.page_number - 1] = SheetOptions(
            scale_inches_per_pt=o.scale_inches_per_pt,
            scale_label=o.scale_label,
            layer_weights=o.layer_weights,
            discipline=o.discipline,
            enabled=o.enabled,
        )

    opts = AnalysisOptions(
        max_sheets=min(body.max_sheets or settings.max_sheets, 200),
        detect_symbols=body.detect_symbols,
        measure_linear=body.measure_linear,
        validate=body.validate_design,
        clash=body.clash,
        only_plans=body.only_plans,
        per_sheet=per,
    )

    job = store.create_job(pid, doc["id"])
    _executor.submit(_run_analysis, job["id"], pid, doc, opts)
    return {"job": job, "document_id": doc["id"]}


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    j = store.get_job(jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@app.get("/api/jobs/{jid}/stream")
def stream_job(jid: str) -> StreamingResponse:
    """Server-sent progress so the UI shows real work rather than a spinner."""
    def gen():
        last = None
        deadline = time.time() + 900
        while time.time() < deadline:
            j = store.get_job(jid)
            if not j:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                return
            snapshot = (j["status"], round(j["progress"] or 0, 4), j["message"])
            if snapshot != last:
                last = snapshot
                yield f"data: {json.dumps(j)}\n\n"
            if j["status"] in ("succeeded", "failed"):
                return
            time.sleep(0.4)
        yield f"data: {json.dumps({'status': 'timeout'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/projects/{pid}/jobs")
def project_jobs(pid: str) -> dict:
    _project_or_404(pid)
    return {"jobs": store.list_jobs(pid)}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@app.get("/api/documents/{did}/result")
def get_result(did: str, sheet: int | None = Query(None, description="1-based page number")) -> dict:
    _document_or_404(did)
    result = _load_and_apply(did)
    if sheet is None:
        light = {k: v for k, v in result.items() if k != "sheets"}
        light["sheets"] = [
            {k: v for k, v in s.items() if k not in ("detections", "linear", "glyphs", "findings")}
            for s in result.get("sheets", [])
        ]
        return light
    for s in result.get("sheets", []):
        if s["page_number"] == sheet:
            return s
    raise HTTPException(404, "Sheet not found in the analysis")


@app.get("/api/documents/{did}/result/full")
def get_result_full(did: str) -> dict:
    _document_or_404(did)
    return _load_and_apply(did)


@app.get("/api/documents/{did}/page/{page}/image")
def page_image(did: str, page: int, dpi: int = Query(110, ge=40, le=300)) -> Response:
    """
    Render one sheet, cached on disk.

    A large sheet is a multi-megabyte render that takes a second or two, and
    while an analysis job is running it competes for CPU with pure-Python
    geometry work — so an uncached re-render on every pan or page switch is the
    difference between the viewer feeling instant and appearing broken. Sheets
    never change once uploaded, so the cache never needs invalidating.
    """
    d = _document_or_404(did)
    cache_dir = settings.data_dir / "renders" / did
    cache_file = cache_dir / f"p{page}_{dpi}.png"

    if cache_file.exists():
        return FileResponse(
            cache_file, media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400", "X-MEPIQ-Cache": "hit"},
        )

    try:
        with DrawingDocument(d["stored_path"]) as doc:
            if page < 1 or page > doc.page_count:
                raise HTTPException(404, "Page out of range")
            png = doc.render_png(page - 1, dpi=dpi)
    except HTTPException:
        raise
    except MemoryError:
        raise HTTPException(507, "Not enough memory to render this sheet — try a lower dpi")
    except Exception as exc:
        raise HTTPException(500, f"Could not render page: {exc}")

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_bytes(png)
        os.replace(tmp, cache_file)
    except Exception:
        pass  # a cache miss is slow, not broken

    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400", "X-MEPIQ-Cache": "miss"})


@app.get("/api/documents/{did}/page/{page}/crop")
def page_crop(did: str, page: int, x0: float, y0: float, x1: float, y1: float,
              dpi: int = Query(300, ge=72, le=900)) -> Response:
    """A zoomed crop in PDF points — used for the detection inspector."""
    d = _document_or_404(did)
    pad = max(2.0, (x1 - x0) * 0.35, (y1 - y0) * 0.35)
    with DrawingDocument(d["stored_path"]) as doc:
        if page < 1 or page > doc.page_count:
            raise HTTPException(404, "Page out of range")
        png = doc.render_png(page - 1, dpi=dpi, clip=(x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# Scale calibration
# ---------------------------------------------------------------------------


@app.post("/api/projects/{pid}/calibrate")
def calibrate(pid: str, body: CalibrateRequest) -> dict:
    _project_or_404(pid)
    _document_or_404(body.document_id)
    real_in = body.real_feet * 12.0 + body.real_inches
    if real_in <= 0:
        raise HTTPException(400, "Give a real-world distance greater than zero")
    info = scale_from_two_points(body.p1, body.p2, real_in)

    result = store.load_result(body.document_id)
    if result:
        for s in result.get("sheets", []):
            if s["page_number"] == body.page_number:
                old = s["scale"]["inches_per_pt"]
                s["scale"] = info.as_dict()
                factor = info.inches_per_pt / old if old else 1.0
                lin = s.get("linear")
                if lin:
                    for r in lin.get("runs", []):
                        r["length_ft"] = round(r["length_ft"] * factor, 2)
                        if r.get("width_in") and (r.get("size_label") or "").startswith("~"):
                            r["width_in"] = round(r["width_in"] * factor, 1)
                            r["size_label"] = f"~{r['width_in']:g}\" (measured)"
                    lin["total_length_ft"] = round(lin.get("total_length_ft", 0) * factor, 2)
                    for grp in ("by_service", "by_size"):
                        for row in lin.get(grp, []):
                            row["length_ft"] = round(row["length_ft"] * factor, 1)
                break
        result["totals"] = project_totals(result.get("sheets", []))
        store.save_result(body.document_id, result)
    return {"scale": info.as_dict()}


class SetScaleRequest(BaseModel):
    document_id: str
    page_number: int
    inches_per_pt: float
    label: str | None = None


@app.post("/api/projects/{pid}/scale")
def set_scale(pid: str, body: SetScaleRequest) -> dict:
    _project_or_404(pid)
    info = manual_scale(body.inches_per_pt, body.label)
    return calibrate(pid, CalibrateRequest(
        document_id=body.document_id, page_number=body.page_number,
        p1=[0, 0], p2=[1, 0], real_inches=body.inches_per_pt,
    )) | {"scale": info.as_dict()}


# ---------------------------------------------------------------------------
# Visual search — "find everything that looks like this"
# ---------------------------------------------------------------------------


@app.post("/api/visual-search")
def visual_search(body: VisualSearchRequest) -> dict:
    """
    Count every occurrence of a symbol the reviewer selects on the drawing.

    This is the workflow estimators already use, made exact: because CAD symbols
    are stamped from blocks, matching is a rigid-transform geometry match rather
    than a similarity score, so the count is not an estimate.
    """
    d = _document_or_404(body.document_id)
    x0, y0, x1, y1 = body.bbox_pt
    if x1 - x0 < 0.5 or y1 - y0 < 0.5:
        raise HTTPException(400, "Selection is too small — drag a box around one symbol")
    # The real cost control is the primitive count below; this bound only rules
    # out a selection so large it cannot be one component. It is generous
    # because a box drawn at a zoomed-out view covers a lot of drawing space.
    if (x1 - x0) > 400 or (y1 - y0) > 400:
        raise HTTPException(
            400,
            "Selection covers too much of the drawing — zoom in further and drag a tighter box "
            "around a single symbol",
        )

    from mepiq_core.matching import SheetGeometryIndex, build_template, find_instances

    with DrawingDocument(d["stored_path"]) as doc:
        if body.page_number < 1 or body.page_number > doc.page_count:
            raise HTTPException(404, "Page out of range")
        sheet = doc.sheet(body.page_number - 1)
        prims = sheet.foreground()
        ids = [
            i for i, p in enumerate(prims)
            if p.bbox()[0] >= x0 - 0.3 and p.bbox()[2] <= x1 + 0.3
            and p.bbox()[1] >= y0 - 0.3 and p.bbox()[3] <= y1 + 0.3
        ]
        if len(ids) < 2:
            raise HTTPException(400, "No drawing geometry inside that selection")
        if len(ids) > 400:
            raise HTTPException(
                400,
                f"That selection contains {len(ids)} pieces of geometry — too many for one symbol. "
                "Zoom in further and drag a tighter box.",
            )

        from mepiq_core.symbols import _canonical_signature
        glyph_id, _box = _canonical_signature(prims, ids)
        template = build_template(prims, ids, glyph_id, 1)
        index = SheetGeometryIndex(prims)
        t0 = time.time()
        matches = find_instances(template, prims, index, min_score=body.min_score,
                                 allow_mirror=body.allow_mirror)

    known = _library.lookup(glyph_id)
    return {
        "glyph_id": glyph_id,
        "template": {"n_segments": template.n_segments, "width_pt": round(template.width_pt, 2),
                     "height_pt": round(template.height_pt, 2), "svg_path": template.svg_path()},
        "known_label": (known or {}).get("label"),
        "count": len(matches),
        "elapsed_s": round(time.time() - t0, 3),
        "instances": [
            {"bbox_pt": [round(v, 2) for v in m.bbox], "score": round(m.score, 3),
             "rotation": m.rotation, "mirror": m.mirror}
            for m in matches[:5000]
        ],
    }


# ---------------------------------------------------------------------------
# Review & feedback learning
# ---------------------------------------------------------------------------


@app.post("/api/projects/{pid}/review")
def review(pid: str, body: ReviewRequest) -> dict:
    _project_or_404(pid)
    _document_or_404(body.document_id)
    if body.action not in ("confirmed", "rejected", "corrected", "dismissed", "accepted", "added"):
        raise HTTPException(400, "Unknown review action")
    rec = store.add_review(pid, body.document_id, body.page_number, body.target_type,
                           body.target_id, body.action, body.payload, body.author)
    return {"review": rec}


@app.get("/api/documents/{did}/reviews")
def list_reviews(did: str) -> dict:
    _document_or_404(did)
    return {"reviews": store.reviews_for(did)}


@app.get("/api/library")
def get_library() -> dict:
    with _library_lock:
        lib = SymbolLibrary(settings.library_path)
        return {"glyphs": lib.as_list(), "count": len(lib.entries)}


@app.post("/api/library")
def learn_glyph(body: LearnGlyphRequest) -> dict:
    """
    Teach the library a symbol.

    Naming a glyph once makes every occurrence of it countable — on this sheet,
    on the rest of the set, and on every drawing analysed afterwards. This is
    what turns the tool from a fixed detector into one that fits the drawing
    conventions of whoever is using it.
    """
    with _library_lock:
        lib = SymbolLibrary(settings.library_path)
        entry = lib.learn(body.glyph_id, body.label.strip(), body.trade, body.category,
                          body.note, body.size_pt)
        _library.entries = lib.entries
    return {"glyph_id": body.glyph_id, "entry": entry}


@app.delete("/api/library/{glyph_id}", status_code=204)
def forget_glyph(glyph_id: str) -> Response:
    with _library_lock:
        lib = SymbolLibrary(settings.library_path)
        lib.forget(glyph_id)
        _library.entries = lib.entries
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


_EXPORTS = {
    "coco": ("application/json", "detections_coco.json"),
    "detections": ("text/csv", "detections.csv"),
    "counts": ("text/csv", "counts.csv"),
    "runs": ("text/csv", "linear_runs.csv"),
    "boq": ("text/csv", "bill_of_quantities.csv"),
    "findings": ("text/csv", "findings.csv"),
    "clashes": ("text/csv", "clashes.csv"),
    "issues": ("application/json", "issues_bcf.json"),
    "ifc": ("application/x-step", "model.ifc"),
    "result": ("application/json", "analysis.json"),
}


@app.get("/api/documents/{did}/export/{kind}")
def export(did: str, kind: str) -> Response:
    if kind not in _EXPORTS:
        raise HTTPException(404, f"Unknown export '{kind}'")
    d = _document_or_404(did)
    result = _load_and_apply(did)
    sheets = result.get("sheets", [])
    media, filename = _EXPORTS[kind]

    if kind == "coco":
        body: Any = json.dumps(to_coco(sheets), indent=2)
    elif kind == "detections":
        body = detections_csv(sheets)
    elif kind == "counts":
        body = counts_csv(sheets)
    elif kind == "runs":
        body = runs_csv(sheets)
    elif kind == "boq":
        body = boq_csv(sheets)
    elif kind == "findings":
        body = findings_csv([f for s in sheets for f in s.get("findings", [])])
    elif kind == "clashes":
        body = clashes_csv(result.get("clashes", []))
    elif kind == "issues":
        body = json.dumps(issues_json([f for s in sheets for f in s.get("findings", [])],
                                      result.get("clashes", [])), indent=2)
    elif kind == "ifc":
        body = to_ifc(sheets, project_name=Path(d["file_name"]).stem)
    else:
        body = json.dumps(result, indent=2)

    stem = Path(d["file_name"]).stem[:60].replace(" ", "_")
    return Response(
        body, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{stem}_{filename}"'},
    )


@app.get("/api/documents/{did}/exports")
def list_exports(did: str) -> dict:
    _document_or_404(did)
    return {"exports": [
        {"kind": k, "filename": v[1], "media_type": v[0], "url": f"/api/documents/{did}/export/{k}"}
        for k, v in _EXPORTS.items()
    ]}


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


@app.post("/api/projects/{pid}/chat")
def chat(pid: str, body: ChatRequest) -> dict:
    project = _project_or_404(pid)
    doc = _primary_document(project, body.document_id)
    result = _load_and_apply(doc["id"])

    question = body.message.strip()
    if not question:
        raise HTTPException(400, "Ask a question")

    store.add_chat(pid, "user", question)
    history = store.chat_history(pid, 12)
    reply = copilot.answer(result, question, history, prefer_llm=body.use_llm)
    store.add_chat(pid, "assistant", reply["text"],
                   {"mode": reply.get("mode"), "tool_calls": reply.get("tool_calls", [])})
    return {
        "reply": reply["text"],
        "mode": reply.get("mode"),
        "model": reply.get("model"),
        "tool_calls": reply.get("tool_calls", []),
        "llm_enabled": settings.llm_enabled,
    }


@app.get("/api/projects/{pid}/chat")
def chat_history(pid: str) -> dict:
    _project_or_404(pid)
    return {"messages": store.chat_history(pid, 100), "llm_enabled": settings.llm_enabled,
            "suggestions": copilot.SUGGESTIONS}


@app.delete("/api/projects/{pid}/chat", status_code=204)
def clear_chat(pid: str) -> Response:
    _project_or_404(pid)
    store.clear_chat(pid)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Static frontend (single-container deployment)
# ---------------------------------------------------------------------------


if settings.static_dir and Path(settings.static_dir).is_dir():
    from fastapi.staticfiles import StaticFiles

    static_root = Path(settings.static_dir)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = static_root / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = static_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(404, "Frontend bundle not found")

    app.mount("/assets", StaticFiles(directory=static_root / "assets", check_dir=False), name="assets")
