"""
Sheet tiling utilities.

MEP sheets are very large (~6300x4500 px at 150 DPI) and the symbols are tiny,
so we slice each sheet into overlapping tiles for both training and inference.

Coordinate convention:
- COCO boxes are [x, y, w, h] in absolute pixels (top-left origin).
- YOLO boxes are [x_center, y_center, w, h] normalized to [0, 1].
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

Tile = Tuple[int, int, int, int]  # (x0, y0, x1, y1) absolute pixel bounds


def tile_grid(width: int, height: int, tile_size: int = 1280,
              overlap: float = 0.2) -> List[Tile]:
    """
    Cover (width, height) with square tiles of `tile_size`, overlapping by
    `overlap` fraction. Edge tiles are snapped inward so the whole sheet is
    covered without going out of bounds.
    """
    if tile_size >= width and tile_size >= height:
        return [(0, 0, width, height)]

    step = max(1, int(round(tile_size * (1.0 - overlap))))
    xs = list(range(0, max(1, width - tile_size + 1), step))
    ys = list(range(0, max(1, height - tile_size + 1), step))
    if not xs or xs[-1] != width - tile_size:
        xs.append(max(0, width - tile_size))
    if not ys or ys[-1] != height - tile_size:
        ys.append(max(0, height - tile_size))

    tiles: List[Tile] = []
    for y0 in ys:
        for x0 in xs:
            x1 = min(x0 + tile_size, width)
            y1 = min(y0 + tile_size, height)
            tiles.append((x0, y0, x1, y1))
    # De-duplicate (small sheets can produce repeats).
    return sorted(set(tiles))


def clip_box_to_tile(box_xywh: Sequence[float], tile: Tile,
                     min_visibility: float = 0.3
                     ) -> Optional[Tuple[float, float, float, float]]:
    """
    Given an absolute [x, y, w, h] box and a tile, return the box in
    TILE-LOCAL coords [x, y, w, h] if enough of it is inside the tile, else None.

    `min_visibility`: minimum fraction of the box area that must fall inside
    the tile for it to be kept (avoids sliver boxes at tile seams).
    """
    x, y, w, h = box_xywh
    bx0, by0, bx1, by1 = x, y, x + w, y + h
    tx0, ty0, tx1, ty1 = tile

    ix0, iy0 = max(bx0, tx0), max(by0, ty0)
    ix1, iy1 = min(bx1, tx1), min(by1, ty1)
    iw, ih = ix1 - ix0, iy1 - iy0
    if iw <= 0 or ih <= 0:
        return None

    box_area = max(1e-6, w * h)
    if (iw * ih) / box_area < min_visibility:
        return None

    return (ix0 - tx0, iy0 - ty0, iw, ih)


def xywh_to_yolo(box_xywh: Sequence[float], tile_w: int, tile_h: int
                 ) -> Tuple[float, float, float, float]:
    """Absolute tile-local [x, y, w, h] -> normalized YOLO [xc, yc, w, h]."""
    x, y, w, h = box_xywh
    xc = (x + w / 2.0) / tile_w
    yc = (y + h / 2.0) / tile_h
    return (xc, yc, w / tile_w, h / tile_h)


def yolo_to_abs(box_yolo: Sequence[float], tile: Tile
                ) -> Tuple[float, float, float, float]:
    """Normalized YOLO [xc, yc, w, h] in a tile -> absolute sheet [x1,y1,x2,y2]."""
    xc, yc, w, h = box_yolo
    tx0, ty0, tx1, ty1 = tile
    tw, th = tx1 - tx0, ty1 - ty0
    axc, ayc = tx0 + xc * tw, ty0 + yc * th
    aw, ah = w * tw, h * th
    return (axc - aw / 2.0, ayc - ah / 2.0, axc + aw / 2.0, ayc + ah / 2.0)


def nms(boxes_xyxy: np.ndarray, scores: np.ndarray,
        iou_threshold: float = 0.5) -> List[int]:
    """Standard single-class NMS. Returns kept indices (highest score first)."""
    if len(boxes_xyxy) == 0:
        return []
    x1, y1, x2, y2 = boxes_xyxy[:, 0], boxes_xyxy[:, 1], boxes_xyxy[:, 2], boxes_xyxy[:, 3]
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = scores.argsort()[::-1]

    keep: List[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        union = areas[i] + areas[order[1:]] - inter
        iou = inter / np.clip(union, 1e-6, None)
        order = order[1:][iou <= iou_threshold]
    return keep


def class_aware_nms(boxes_xyxy: np.ndarray, scores: np.ndarray,
                    labels: np.ndarray, iou_threshold: float = 0.5) -> List[int]:
    """Run NMS independently per class label; used to merge tile-seam duplicates."""
    keep_all: List[int] = []
    for cls in np.unique(labels):
        idx = np.where(labels == cls)[0]
        sub_keep = nms(boxes_xyxy[idx], scores[idx], iou_threshold)
        keep_all.extend(idx[k] for k in sub_keep)
    return keep_all
