"""Visualization helpers: draw detections and a per-class count legend."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np

# A fixed palette (BGR-agnostic; we use RGB with PIL).
_PALETTE = [
    (230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60),
    (250, 190, 190), (0, 128, 128), (170, 110, 40), (128, 0, 0),
    (170, 255, 195), (128, 128, 0), (255, 215, 180), (0, 0, 128),
    (128, 128, 128), (255, 225, 25), (0, 200, 200), (100, 100, 255),
    (200, 100, 0), (0, 160, 90),
]


def color_for(class_id: int) -> Tuple[int, int, int]:
    return _PALETTE[class_id % len(_PALETTE)]


def draw_detections(img: np.ndarray,
                    boxes_xyxy: Sequence[Sequence[float]],
                    labels: Sequence[int],
                    class_names: List[str],
                    scores: Sequence[float] = None,
                    counts: Dict[str, int] = None,
                    line_width: int = 3) -> np.ndarray:
    """
    Return a copy of `img` with boxes, class colors, and a count legend drawn.
    Uses PIL so it works without OpenCV.
    """
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.fromarray(np.ascontiguousarray(img)).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
        legend_font = ImageFont.truetype("arial.ttf", 26)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
        legend_font = font

    for i, (box, lab) in enumerate(zip(boxes_xyxy, labels)):
        x1, y1, x2, y2 = [float(v) for v in box]
        col = color_for(int(lab))
        draw.rectangle([x1, y1, x2, y2], outline=col, width=line_width)
        tag = class_names[int(lab)] if 0 <= int(lab) < len(class_names) else str(lab)
        if scores is not None:
            tag = f"{tag} {float(scores[i]):.2f}"
        draw.text((x1, max(0, y1 - 22)), tag, fill=col, font=font)

    if counts:
        _draw_legend(draw, counts, class_names, legend_font)
    return np.asarray(canvas)


def _draw_legend(draw, counts: Dict[str, int], class_names: List[str], font) -> None:
    from PIL import ImageDraw  # noqa: F401
    lines = [f"{name}: {counts.get(name, 0)}" for name in class_names if counts.get(name, 0)]
    if not lines:
        return
    total = sum(counts.values())
    lines.append(f"TOTAL: {total}")
    pad = 12
    line_h = 32
    box_w = 460
    box_h = pad * 2 + line_h * len(lines)
    draw.rectangle([10, 10, 10 + box_w, 10 + box_h], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    y = 10 + pad
    for j, line in enumerate(lines):
        col = (0, 0, 0)
        for cid, name in enumerate(class_names):
            if line.startswith(name + ":"):
                col = color_for(cid)
                break
        draw.text((10 + pad, y), line, fill=col, font=font)
        y += line_h
