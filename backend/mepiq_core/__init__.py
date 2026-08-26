"""
MEPIQ Core — vector-native MEP drawing intelligence engine.

The engine treats construction PDFs as what they actually are: vector CAD
exports. Instead of rasterising and hoping a CNN finds a 20-pixel symbol, we
read the drawing's own geometry (lines, curves, rectangles, stroke colour and
line weight) and reason over it. That gives sub-pixel measurement accuracy,
deterministic counts and full explainability — every number the product shows
can be traced back to a specific primitive on the page.
"""

__version__ = "1.0.0"

from .pdfdoc import DrawingDocument, Primitive, SheetInfo  # noqa: F401
from .scale import ScaleInfo, detect_scale  # noqa: F401
from .discipline import classify_discipline  # noqa: F401

__all__ = [
    "DrawingDocument",
    "Primitive",
    "SheetInfo",
    "ScaleInfo",
    "detect_scale",
    "classify_discipline",
    "__version__",
]
