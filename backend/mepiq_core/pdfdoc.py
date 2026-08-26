"""
Vector primitive extraction from construction PDFs.

Everything downstream (symbol detection, linear measurement, validation) reads
from the flattened primitive stream produced here. Two ideas make the rest of
the engine work:

1. **Screened vs. foreground linework.** CAD publishers screen the background
   reference drawing (architectural underlay, grid, room outlines) to a light
   grey while the discipline's own systems stay full-intensity. Splitting on
   luminance therefore separates "the sheet I am responsible for" from "context"
   with near-perfect reliability, on every publisher we tested.

2. **Line weight is semantic.** Within the foreground, duct/pipe run linework is
   drawn at a heavier, consistent weight than tags, leaders and hatching. So the
   weight histogram is effectively a layer table we can recover without layers.
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

import pymupdf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Ground-truth COCO boxes in the supplied dataset are expressed at this DPI.
GT_DPI = 150.0
PT_PER_INCH = 72.0

#: Strokes lighter than this relative luminance are treated as a screened
#: background underlay rather than active discipline linework.
SCREEN_LUMINANCE = 0.35

#: A stroke is "coloured" (and therefore meaningful even if light) when the
#: spread between its RGB channels exceeds this.
COLOUR_SATURATION = 0.12


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Primitive:
    """A single straight stroke segment in PDF user space (points, origin top-left)."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    color: tuple[float, float, float]
    dashed: bool = False
    fill: bool = False
    kind: str = "l"  # l = line, re = rectangle edge, c = curve chord, qu = quad

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def angle(self) -> float:
        """Undirected angle in radians, normalised to [0, pi)."""
        a = math.atan2(self.y1 - self.y0, self.x1 - self.x0)
        if a < 0:
            a += math.pi
        if a >= math.pi:
            a -= math.pi
        return a

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def luminance(self) -> float:
        r, g, b = self.color
        return 0.299 * r + 0.587 * g + 0.114 * b

    @property
    def saturation(self) -> float:
        return max(self.color) - min(self.color)

    @property
    def is_foreground(self) -> bool:
        """True when this stroke belongs to the discipline, not the underlay."""
        return self.luminance <= SCREEN_LUMINANCE or self.saturation >= COLOUR_SATURATION

    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(self.x0, self.x1),
            min(self.y0, self.y1),
            max(self.x0, self.x1),
            max(self.y0, self.y1),
        )


@dataclass(slots=True)
class TextItem:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)


@dataclass(slots=True)
class SheetInfo:
    index: int
    width_pt: float
    height_pt: float
    rotation: int
    label: str = ""
    title: str = ""
    discipline: str = "unknown"
    n_primitives: int = 0
    n_foreground: int = 0

    @property
    def width_px(self) -> int:
        return int(round(self.width_pt * GT_DPI / PT_PER_INCH))

    @property
    def height_px(self) -> int:
        return int(round(self.height_pt * GT_DPI / PT_PER_INCH))


@dataclass
class Sheet:
    info: SheetInfo
    primitives: list[Primitive] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)

    # -- convenience views --------------------------------------------------

    def foreground(self) -> list[Primitive]:
        return [p for p in self.primitives if p.is_foreground and p.length > 1e-6]

    def weight_histogram(self, foreground_only: bool = True) -> dict[float, float]:
        """Total inked length per rounded stroke weight. This is our layer table."""
        hist: dict[float, float] = {}
        src = self.foreground() if foreground_only else self.primitives
        for p in src:
            key = round(p.width, 2)
            hist[key] = hist.get(key, 0.0) + p.length
        return dict(sorted(hist.items(), key=lambda kv: -kv[1]))

    def color_histogram(self) -> dict[tuple[float, float, float], float]:
        hist: dict[tuple[float, float, float], float] = {}
        for p in self.foreground():
            key = tuple(round(c, 3) for c in p.color)  # type: ignore[assignment]
            hist[key] = hist.get(key, 0.0) + p.length  # type: ignore[index]
        return dict(sorted(hist.items(), key=lambda kv: -kv[1]))

    def text_blob(self) -> str:
        return "\n".join(t.text for t in self.texts)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _flatten_items(items: Sequence, width: float, color, dashed: bool, filled: bool) -> Iterator[Primitive]:
    col = tuple(float(c) for c in (color or (0.0, 0.0, 0.0)))[:3]
    if len(col) < 3:
        col = (col + (0.0, 0.0, 0.0))[:3]  # type: ignore[operator]
    for it in items:
        op = it[0]
        try:
            if op == "l":
                a, b = it[1], it[2]
                yield Primitive(a.x, a.y, b.x, b.y, width, col, dashed, filled, "l")  # type: ignore[arg-type]
            elif op == "re":
                r = it[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for i in range(4):
                    (ax, ay), (bx, by) = pts[i], pts[(i + 1) % 4]
                    yield Primitive(ax, ay, bx, by, width, col, dashed, filled, "re")  # type: ignore[arg-type]
            elif op == "c":
                # Approximate the cubic by its three control chords: enough for
                # length/topology while staying cheap on 100k-primitive sheets.
                p0, p1, p2, p3 = it[1], it[2], it[3], it[4]
                chain = [p0, p1, p2, p3]
                for i in range(3):
                    a, b = chain[i], chain[i + 1]
                    yield Primitive(a.x, a.y, b.x, b.y, width, col, dashed, filled, "c")  # type: ignore[arg-type]
            elif op == "qu":
                q = it[1]
                pts = [q.ul, q.ur, q.lr, q.ll]
                for i in range(4):
                    a, b = pts[i], pts[(i + 1) % 4]
                    yield Primitive(a.x, a.y, b.x, b.y, width, col, dashed, filled, "qu")  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - defensive against odd content streams
            continue


class DrawingDocument:
    """Lazily-parsed view over a construction drawing PDF."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = str(path)
        self._doc = pymupdf.open(self.path)
        self._sheets: dict[int, Sheet] = {}

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        try:
            self._doc.close()
        except Exception:
            pass

    def __enter__(self) -> "DrawingDocument":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- basics -------------------------------------------------------------

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def checksum(self) -> str:
        h = hashlib.sha256()
        with open(self.path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    # -- sheets -------------------------------------------------------------

    def sheet(self, index: int) -> Sheet:
        if index in self._sheets:
            return self._sheets[index]

        page = self._doc[index]
        rect = page.rect
        prims: list[Primitive] = []

        for dr in page.get_drawings():
            stroke = dr.get("color")
            fill = dr.get("fill")
            width = float(dr.get("width") or 0.0)
            dashes = dr.get("dashes") or ""
            dashed = bool(dashes and dashes not in ("[] 0", "[]0", "[ ] 0"))
            items = dr.get("items") or []
            if stroke is not None:
                prims.extend(_flatten_items(items, width, stroke, dashed, False))
            elif fill is not None:
                # Filled-only shapes (solid symbols, poché) still carry outline
                # geometry we want for clustering.
                prims.extend(_flatten_items(items, max(width, 0.24), fill, dashed, True))

        texts: list[TextItem] = []
        try:
            for blk in page.get_text("dict").get("blocks", []):
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        raw = (span.get("text") or "").strip()
                        if not raw:
                            continue
                        bx = span.get("bbox", (0, 0, 0, 0))
                        texts.append(
                            TextItem(raw, float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]), float(span.get("size") or 0.0))
                        )
        except Exception:  # pragma: no cover
            pass

        info = SheetInfo(
            index=index,
            width_pt=float(rect.width),
            height_pt=float(rect.height),
            rotation=int(page.rotation or 0),
            n_primitives=len(prims),
            n_foreground=sum(1 for p in prims if p.is_foreground),
        )
        sheet = Sheet(info=info, primitives=prims, texts=texts)
        self._sheets[index] = sheet
        return sheet

    def iter_sheets(self, indices: Iterable[int] | None = None) -> Iterator[Sheet]:
        for i in indices if indices is not None else range(self.page_count):
            yield self.sheet(i)

    def release(self, index: int) -> None:
        """Drop a parsed sheet from the cache. Bid sets do not fit in memory."""
        self._sheets.pop(index, None)

    def quick_sheet(self, index: int) -> Sheet:
        """
        A text-only view of a page, with geometry density estimated rather than
        parsed.

        Fully parsing a 100,000-primitive sheet costs a second or more, and a
        submitted bid set can be several hundred pages. Triage — which trade is
        this, and is it a plan? — needs the text and a sense of how much drawing
        is on the page, both of which are cheap.
        """
        if index in self._sheets:
            return self._sheets[index]

        page = self._doc[index]
        rect = page.rect
        texts: list[TextItem] = []
        try:
            for blk in page.get_text("dict").get("blocks", []):
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        raw = (span.get("text") or "").strip()
                        if not raw:
                            continue
                        bx = span.get("bbox", (0, 0, 0, 0))
                        texts.append(
                            TextItem(raw, float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]), float(span.get("size") or 0.0))
                        )
        except Exception:  # pragma: no cover
            pass

        # Content-stream size is a good, very cheap proxy for drawing density.
        try:
            nbytes = sum(len(self._doc.xref_stream(x)) for x in page.get_contents())
        except Exception:
            nbytes = 0
        density = int(nbytes / 24)

        info = SheetInfo(
            index=index,
            width_pt=float(rect.width),
            height_pt=float(rect.height),
            rotation=int(page.rotation or 0),
            n_primitives=density,
            n_foreground=density,
        )
        return Sheet(info=info, primitives=[], texts=texts)

    # -- rendering ----------------------------------------------------------

    def render(self, index: int, dpi: float = GT_DPI, clip: tuple[float, float, float, float] | None = None):
        """Render a page (or a clip of it) to a PyMuPDF Pixmap."""
        page = self._doc[index]
        mat = pymupdf.Matrix(dpi / PT_PER_INCH, dpi / PT_PER_INCH)
        rect = pymupdf.Rect(*clip) if clip else None
        return page.get_pixmap(matrix=mat, clip=rect, alpha=False)

    def render_png(self, index: int, dpi: float = GT_DPI, clip=None) -> bytes:
        return self.render(index, dpi, clip).tobytes("png")

    def render_gray_array(self, index: int, dpi: float = GT_DPI, clip=None):
        """Render to a float32 numpy array in [0,1], 1 = ink."""
        import numpy as np

        pix = self.render(index, dpi, clip)
        buf = np.frombuffer(pix.samples, dtype=np.uint8)
        arr = buf.reshape(pix.height, pix.width, pix.n)
        if pix.n >= 3:
            g = arr[:, :, :3].mean(axis=2)
        else:
            g = arr[:, :, 0]
        return (255.0 - g.astype("float32")) / 255.0


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def pt_to_px(v: float, dpi: float = GT_DPI) -> float:
    return v * dpi / PT_PER_INCH


def px_to_pt(v: float, dpi: float = GT_DPI) -> float:
    return v * PT_PER_INCH / dpi


def bbox_pt_to_px(b: Sequence[float], dpi: float = GT_DPI) -> list[float]:
    """[x0,y0,x1,y1] points -> COCO [x,y,w,h] pixels."""
    x0, y0, x1, y1 = b
    s = dpi / PT_PER_INCH
    return [x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s]


def bbox_px_to_pt(b: Sequence[float], dpi: float = GT_DPI) -> list[float]:
    """COCO [x,y,w,h] pixels -> [x0,y0,x1,y1] points."""
    x, y, w, h = b
    s = PT_PER_INCH / dpi
    return [x * s, y * s, (x + w) * s, (y + h) * s]
