"""
Unit tests for the geometry engine.

These build synthetic drawings rather than depending on the dataset, so CI stays
fast and the tests document exactly what each stage is supposed to do.
"""

from __future__ import annotations

import math

import pytest

from mepiq_core.geometry import bbox_iou, douglas_peucker, nms
from mepiq_core.linear import (
    LineTag,
    _chain_runs,
    extract_centrelines,
    parse_line_tags,
)
from mepiq_core.matching import (
    SheetGeometryIndex,
    build_template,
    clean_selection,
    find_instances,
)
from mepiq_core.pdfdoc import PT_PER_INCH, Primitive, TextItem, bbox_px_to_pt, bbox_pt_to_px
from mepiq_core.scale import (
    STANDARD_SCALES,
    manual_scale,
    scale_from_two_points,
    snap_to_standard,
)
from mepiq_core.shapes import classify_blob


def line(x0, y0, x1, y1, w=1.0, kind="l", fill=False):
    return Primitive(x0, y0, x1, y1, w, (0.0, 0.0, 0.0), False, fill, kind)


# ---------------------------------------------------------------------------
# Primitives and coordinates
# ---------------------------------------------------------------------------


def test_primitive_geometry():
    p = line(0, 0, 3, 4)
    assert p.length == pytest.approx(5.0)
    assert p.midpoint == (1.5, 2.0)
    assert p.bbox() == (0, 0, 3, 4)


def test_foreground_split_on_luminance():
    black = Primitive(0, 0, 10, 0, 1.0, (0.0, 0.0, 0.0))
    screened = Primitive(0, 0, 10, 0, 1.0, (0.8, 0.8, 0.8))
    coloured = Primitive(0, 0, 10, 0, 1.0, (0.9, 0.1, 0.1))
    assert black.is_foreground
    assert not screened.is_foreground
    assert coloured.is_foreground, "saturated colour is meaningful even when light"


def test_pixel_point_roundtrip():
    box_pt = [10.0, 20.0, 40.0, 50.0]
    px = bbox_pt_to_px(box_pt)
    back = bbox_px_to_pt(px)
    assert back == pytest.approx(box_pt)


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------


def test_quarter_inch_scale_is_48_inches_per_paper_inch():
    ipt = STANDARD_SCALES['1/4" = 1\'-0"']
    # One paper inch spans 4 feet, so 72 pt spans 48 inches.
    assert ipt * PT_PER_INCH == pytest.approx(48.0)


def test_snap_prefers_imperial_unless_metric_is_allowed():
    metric = STANDARD_SCALES["1:75"]
    assert snap_to_standard(metric, allow_metric=True)[0] == "1:75"
    imperial = snap_to_standard(metric, allow_metric=False)
    assert imperial is None or not imperial[0].startswith("1:")


def test_two_point_calibration():
    info = scale_from_two_points([0, 0], [72, 0], 48.0)
    assert info.inches_per_pt == pytest.approx(48 / 72)
    assert info.to_feet(72) == pytest.approx(4.0)
    assert info.manual and info.confidence == 1.0


def test_length_formatting():
    info = manual_scale(48 / 72)
    assert info.format_length(72).startswith("4'")


# ---------------------------------------------------------------------------
# Level 1 — shape classification
# ---------------------------------------------------------------------------


def square_with_x(size=18.0, circle=False):
    a, b = 0.0, size
    prims = [
        line(a, a, b, a), line(b, a, b, b), line(b, b, a, b), line(a, b, a, a),
        line(a, a, b, b), line(a, b, b, a),
    ]
    if circle:
        cx = cy = size / 2
        r = size * 0.16
        n = 12
        for i in range(n):
            t0 = 2 * math.pi * i / n
            t1 = 2 * math.pi * (i + 1) / n
            prims.append(
                line(cx + r * math.cos(t0), cy + r * math.sin(t0),
                     cx + r * math.cos(t1), cy + r * math.sin(t1), kind="c")
            )
    return prims


def test_square_with_x_is_a_fire_damper():
    prims = square_with_x()
    m = classify_blob(prims, list(range(len(prims))))
    assert m is not None and m.key == "fire_damper"


def test_square_with_x_and_neck_circle_is_a_supply_diffuser():
    prims = square_with_x(circle=True)
    m = classify_blob(prims, list(range(len(prims))))
    assert m is not None and m.key == "square_supply_diffuser_4way"


def test_square_with_one_diagonal_is_a_return_register():
    prims = square_with_x()[:4] + [line(0, 18, 18, 0)]
    m = classify_blob(prims, list(range(len(prims))))
    assert m is not None and m.key == "square_return_exhaust_register"


def test_bare_square_is_not_a_component():
    prims = square_with_x()[:4]
    assert classify_blob(prims, list(range(len(prims)))) is None


def test_classification_is_rotation_invariant():
    """The same symbol drawn at 90 degrees must classify identically."""
    prims = square_with_x(circle=True)
    rotated = [line(-p.y0, p.x0, -p.y1, p.x1, p.width, p.kind) for p in prims]
    a = classify_blob(prims, list(range(len(prims))))
    b = classify_blob(rotated, list(range(len(rotated))))
    assert a and b and a.key == b.key


# ---------------------------------------------------------------------------
# Geometric matching
# ---------------------------------------------------------------------------


def test_find_instances_recovers_every_stamped_copy():
    sheet = []
    offsets = [(0, 0), (100, 0), (0, 100), (250, 180), (400, 60)]
    for ox, oy in offsets:
        for p in square_with_x():
            sheet.append(line(p.x0 + ox, p.y0 + oy, p.x1 + ox, p.y1 + oy, p.width))
    # Add unrelated linework that must not match.
    sheet += [line(0, 400, 600, 400, 1.0), line(300, 0, 300, 400, 1.0)]

    template = build_template(sheet, list(range(6)), "t", 1)
    index = SheetGeometryIndex(sheet)
    found = find_instances(template, sheet, index, min_score=0.9)
    assert len(found) == len(offsets)


def test_clean_selection_drops_unconnected_strays():
    prims = square_with_x()
    prims.append(line(60, 60, 90, 60))          # a stray far from the symbol
    keep = clean_selection(prims, list(range(len(prims))))
    assert len(keep) == 6


# ---------------------------------------------------------------------------
# Level 2 — measurement
# ---------------------------------------------------------------------------


def test_duct_walls_collapse_to_one_centreline_with_a_width():
    prims = [line(0, 0, 100, 0, 1.32), line(0, 12, 100, 12, 1.32)]
    lines, used = extract_centrelines(prims)
    assert len(lines) == 1
    c = lines[0]
    assert c.width_pt == pytest.approx(12.0)
    assert c.length == pytest.approx(100.0)
    assert c.y0 == pytest.approx(6.0), "centreline sits between the walls"
    assert used == {0, 1}


def test_measured_duct_is_not_double_counted():
    """Two walls of one duct must measure L, not 2L."""
    prims = [line(0, 0, 100, 0, 1.32), line(0, 12, 100, 12, 1.32)]
    raw = sum(p.length for p in prims)
    lines, _ = extract_centrelines(prims)
    assert raw == pytest.approx(200.0)
    assert sum(c.length for c in lines) == pytest.approx(100.0)


def test_runs_chain_across_an_elbow():
    segs = [
        (0, 0, 50, 0, 0.0, [0]),
        (50, 0, 50, 40, 0.0, [1]),
        (50, 40, 90, 40, 0.0, [2]),
    ]
    chains = _chain_runs(segs)
    assert len(chains) == 1 and len(chains[0]) == 3


def test_disconnected_runs_stay_separate():
    segs = [(0, 0, 50, 0, 0.0, [0]), (200, 200, 260, 200, 0.0, [1])]
    assert len(_chain_runs(segs)) == 2


def test_duct_and_pipe_tags_are_parsed():
    texts = [
        TextItem("42/20 SA", 0, 0, 20, 5, 6),
        TextItem("12ø EA", 0, 10, 20, 15, 6),
        TextItem('(N)2"LW', 0, 20, 20, 25, 6),
        TextItem('(E)4"SS', 0, 30, 20, 35, 6),
        TextItem("ROOM 101", 0, 40, 30, 45, 6),
    ]
    tags = parse_line_tags(texts)
    kinds = {t.kind for t in tags}
    assert kinds == {"duct_rect", "duct_round", "pipe"}
    rect = next(t for t in tags if t.kind == "duct_rect")
    assert rect.width_in == 42 and rect.service == "SA" and rect.service_name == "Supply Air"
    new_pipe = next(t for t in tags if t.raw == '(N)2"LW')
    assert new_pipe.status == "new" and new_pipe.diameter_in == 2
    existing = next(t for t in tags if t.raw == '(E)4"SS')
    assert existing.status == "existing" and existing.service_name == "Sanitary Sewer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_bbox_iou_and_nms():
    a = [0, 0, 10, 10]
    b = [0, 0, 10, 10]
    c = [100, 100, 110, 110]
    assert bbox_iou(a, b) == pytest.approx(1.0)
    assert bbox_iou(a, c) == 0.0
    assert sorted(nms([a, b, c], [0.9, 0.5, 0.8], 0.3)) == [0, 2]


def test_douglas_peucker_removes_collinear_points():
    pts = [(0, 0), (5, 0), (10, 0), (10, 10)]
    simplified = douglas_peucker(pts, 0.1)
    assert simplified == [(0, 0), (10, 0), (10, 10)]
