"""
API contract tests.

A tiny synthetic drawing is generated with PyMuPDF so the whole pipeline —
upload, analysis job, results, review, exports, copilot — is exercised end to
end without depending on the dataset being present.
"""

from __future__ import annotations

import io
import os
import tempfile
import time

import pytest

os.environ.setdefault("MEPIQ_DATA_DIR", tempfile.mkdtemp(prefix="mepiq-test-"))

import pymupdf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def synthetic_drawing() -> bytes:
    """A one-sheet mechanical plan: two duct runs and four fire dampers."""
    doc = pymupdf.open()
    page = doc.new_page(width=1224, height=792)

    black = (0, 0, 0)
    grey = (0.78, 0.78, 0.78)

    # Screened architectural underlay — must be ignored by the engine.
    for i in range(12):
        page.draw_line((60, 60 + i * 55), (1160, 60 + i * 55), color=grey, width=0.24)

    # Two duct runs, drawn as parallel wall pairs at a heavier pen.
    for y in (200, 420):
        page.draw_line((150, y), (900, y), color=black, width=1.32)
        page.draw_line((150, y + 24), (900, y + 24), color=black, width=1.32)

    # Fire dampers: 18 pt squares with an internal X.
    for cx, cy in ((300, 190), (520, 190), (300, 410), (700, 410)):
        page.draw_rect(pymupdf.Rect(cx, cy, cx + 18, cy + 18), color=black, width=1.32)
        page.draw_line((cx, cy), (cx + 18, cy + 18), color=black, width=1.32)
        page.draw_line((cx, cy + 18), (cx + 18, cy), color=black, width=1.32)

    page.insert_text((160, 190), "24/12 SA", fontsize=7)
    page.insert_text((160, 410), "18/10 RA", fontsize=7)
    page.insert_text((1000, 720), 'MECHANICAL DUCTWORK PLAN', fontsize=9)
    page.insert_text((1000, 740), 'SCALE: 1/4" = 1\'-0"', fontsize=8)
    page.insert_text((1050, 760), "M-101", fontsize=14)

    buf = doc.tobytes()
    doc.close()
    return buf


@pytest.fixture(scope="module")
def analysed():
    project = client.post("/api/projects", json={"name": "Test Tower"}).json()
    pid = project["id"]

    files = {"files": ("test-mech.pdf", io.BytesIO(synthetic_drawing()), "application/pdf")}
    up = client.post(f"/api/projects/{pid}/documents", files=files)
    assert up.status_code == 201, up.text
    did = up.json()["documents"][0]["id"]

    job = client.post(f"/api/projects/{pid}/analyse", json={"document_id": did, "max_sheets": 1})
    assert job.status_code == 202
    jid = job.json()["job"]["id"]

    deadline = time.time() + 180
    status = {}
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{jid}").json()
        if status["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert status["status"] == "succeeded", status.get("error", status)
    return pid, did


def test_health_and_catalogue():
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    cat = client.get("/api/catalogue").json()
    assert len(cat["symbols"]) >= 8
    assert len(cat["rules"]) >= 10
    assert any(s["label"].startswith('1/4"') for s in cat["standard_scales"])


def test_rejects_non_pdf():
    project = client.post("/api/projects", json={"name": "Bad upload"}).json()
    files = {"files": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    r = client.post(f"/api/projects/{project['id']}/documents", files=files)
    assert r.status_code == 400


def test_analysis_finds_ducts_and_dampers(analysed):
    _pid, did = analysed
    result = client.get(f"/api/documents/{did}/result/full").json()
    assert result["analysed_sheets"] == 1
    sheet = result["sheets"][0]

    assert sheet["discipline"] == "mechanical"
    assert sheet["scale"]["label"].startswith('1/4"'), sheet["scale"]
    assert sheet["scale"]["method"] == "title_block"

    names = {c["category"]: c["count"] for c in sheet["counts"]}
    assert names.get("Fire Damper (FD)", 0) >= 4, names

    linear = sheet["linear"]
    assert linear["kind"] == "duct"
    assert linear["run_count"] >= 2

    # Each duct is drawn 750 pt long. At 1/4" = 1'-0" one paper inch is 4 ft, so
    # 750 pt = 750/72 in = 41.7 ft, and two runs total ~83 ft.
    #
    # The number that matters here is that it is ~83 and not ~167: the two walls
    # of each duct were collapsed to a single centreline instead of being
    # measured twice, which is the classic error when taking ductwork off a PDF.
    assert 78 <= linear["total_length_ft"] <= 90, linear["total_length_ft"]


def test_detections_carry_an_explanation(analysed):
    _pid, did = analysed
    sheet = client.get(f"/api/documents/{did}/result/full").json()["sheets"][0]
    det = next(d for d in sheet["detections"] if d["category"] == "Fire Damper (FD)")
    assert det["rationale"], "every detection must be able to explain itself"
    assert 0 < det["confidence"] <= 1


def test_visual_search_counts_identical_stamps(analysed):
    _pid, did = analysed
    sheet = client.get(f"/api/documents/{did}/result/full").json()["sheets"][0]
    det = next(d for d in sheet["detections"] if d["category"] == "Fire Damper (FD)")
    r = client.post("/api/visual-search", json={
        "document_id": did, "page_number": sheet["page_number"], "bbox_pt": det["bbox_pt"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 4


def test_review_removes_a_detection_from_the_count(analysed):
    pid, did = analysed
    before = client.get(f"/api/documents/{did}/result/full").json()["sheets"][0]
    det = before["detections"][0]
    n_before = sum(c["count"] for c in before["counts"])

    r = client.post(f"/api/projects/{pid}/review", json={
        "document_id": did, "page_number": before["page_number"],
        "target_type": "detection", "target_id": str(det["id"]), "action": "rejected",
    })
    assert r.status_code == 200

    after = client.get(f"/api/documents/{did}/result/full").json()["sheets"][0]
    assert sum(c["count"] for c in after["counts"]) == n_before - 1


@pytest.mark.parametrize("kind", ["coco", "counts", "detections", "runs", "boq", "findings", "ifc", "issues"])
def test_exports(analysed, kind):
    _pid, did = analysed
    r = client.get(f"/api/documents/{did}/export/{kind}")
    assert r.status_code == 200
    assert len(r.content) > 40
    if kind == "coco":
        data = r.json()
        assert data["images"] and data["categories"]
    if kind == "ifc":
        assert r.text.startswith("ISO-10303-21;")
        assert "IFCPROJECT" in r.text and r.text.rstrip().endswith("END-ISO-10303-21;")


def test_page_render(analysed):
    _pid, did = analysed
    r = client.get(f"/api/documents/{did}/page/1/image?dpi=72")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_copilot_answers_from_the_analysis(analysed):
    pid, did = analysed
    r = client.post(f"/api/projects/{pid}/chat", json={
        "message": "How much ductwork is there?", "document_id": did, "use_llm": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "deterministic"
    assert "ft" in body["reply"].lower()
    assert body["tool_calls"], "answers must be grounded in a tool call"


def test_copilot_counts(analysed):
    pid, did = analysed
    r = client.post(f"/api/projects/{pid}/chat", json={
        "message": "how many fire dampers are there?", "document_id": did, "use_llm": False,
    }).json()
    assert "damper" in r["reply"].lower()


def test_library_learns_and_forgets(analysed):
    _pid, did = analysed
    sheet = client.get(f"/api/documents/{did}/result/full").json()["sheets"][0]
    det = next(d for d in sheet["detections"] if d["category"] == "Fire Damper (FD)")
    vs = client.post("/api/visual-search", json={
        "document_id": did, "page_number": sheet["page_number"], "bbox_pt": det["bbox_pt"],
    }).json()

    r = client.post("/api/library", json={"glyph_id": vs["glyph_id"], "label": "Custom Damper", "trade": "HVAC"})
    assert r.status_code == 200
    assert any(g["label"] == "Custom Damper" for g in client.get("/api/library").json()["glyphs"])

    assert client.delete(f"/api/library/{vs['glyph_id']}").status_code == 204
    assert not any(g["label"] == "Custom Damper" for g in client.get("/api/library").json()["glyphs"])
