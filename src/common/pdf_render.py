"""
Render PDF drawing pages to raster images at a fixed DPI.

The dataset annotations are aligned to images rendered at 150 DPI. We render
with PyMuPDF (fitz). If the rendered size does not exactly match the width/height
recorded in the COCO image entry (can happen with odd page boxes / rotation),
we resize the raster to the recorded size so the ground-truth boxes stay aligned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

DEFAULT_DPI = 150


def _lazy_fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "PyMuPDF is required. Install with: pip install pymupdf"
        ) from exc
    return fitz


def render_page(pdf_path: Path,
                page_number: int = 1,
                dpi: int = DEFAULT_DPI,
                target_size: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """
    Render one page (1-indexed) to an RGB numpy array (H, W, 3), uint8.

    target_size: optional (width, height). If given and the render differs,
    the image is resized to exactly that size to keep annotations aligned.
    """
    fitz = _lazy_fitz()
    doc = fitz.open(str(pdf_path))
    try:
        idx = page_number - 1
        if idx < 0 or idx >= doc.page_count:
            raise IndexError(
                f"{pdf_path.name}: page {page_number} out of range "
                f"(has {doc.page_count} pages)"
            )
        page = doc.load_page(idx)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:  # RGBA -> RGB
            img = img[:, :, :3]
        elif pix.n == 1:  # gray -> RGB
            img = np.repeat(img, 3, axis=2)
        img = np.ascontiguousarray(img)
    finally:
        doc.close()

    if target_size is not None:
        tw, th = int(target_size[0]), int(target_size[1])
        if (img.shape[1], img.shape[0]) != (tw, th):
            from PIL import Image
            img = np.asarray(
                Image.fromarray(img).resize((tw, th), Image.BILINEAR)
            )
    return img


def page_count(pdf_path: Path) -> int:
    fitz = _lazy_fitz()
    doc = fitz.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


def save_image(img: np.ndarray, out_path: Path) -> None:
    from PIL import Image
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(str(out_path))
