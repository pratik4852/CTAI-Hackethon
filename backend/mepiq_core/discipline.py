"""
Sheet classification: which trade is this drawing, and is it a plan we can measure?

A submitted PDF is usually a whole bid set — hundreds of pages of which a
handful are the mechanical ductwork plans we care about. Routing every page
through the full pipeline would be slow and would produce nonsense counts on
schedules, details and cover sheets. So we classify first, cheaply, from the
sheet number, the title text and the shape of the geometry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .pdfdoc import Sheet

DISCIPLINES = ("mechanical", "electrical", "plumbing", "fire_protection", "architectural", "unknown")

DISCIPLINE_LABELS = {
    "mechanical": "Mechanical / HVAC",
    "electrical": "Electrical",
    "plumbing": "Plumbing",
    "fire_protection": "Fire Protection",
    "architectural": "Architectural",
    "unknown": "Unclassified",
}

#: Sheet-number prefixes are the most reliable signal in the industry.
_SHEET_PREFIX = [
    (re.compile(r"\b(FP|SP)[- ]?\d", re.I), "fire_protection"),
    (re.compile(r"\bM[-.]?\d", re.I), "mechanical"),
    (re.compile(r"\bH[-.]?\d", re.I), "mechanical"),
    (re.compile(r"\bE[-.]?\d", re.I), "electrical"),
    (re.compile(r"\bP[-.]?\d", re.I), "plumbing"),
    (re.compile(r"\bA[-.]?\d", re.I), "architectural"),
]

_KEYWORDS: dict[str, tuple[tuple[str, float], ...]] = {
    "mechanical": (
        ("ductwork", 3.0), ("hvac", 3.0), ("mechanical", 2.5), ("diffuser", 2.0),
        ("supply air", 2.0), ("return air", 2.0), ("exhaust air", 1.5), ("vav", 2.0),
        ("air handling", 2.0), ("ahu", 1.5), ("cfm", 1.5), ("fire damper", 1.5),
        ("heat pump", 1.2), ("register", 1.0), ("grille", 1.0),
    ),
    "electrical": (
        ("electrical", 3.0), ("panelboard", 2.5), ("panel board", 2.5), ("receptacle", 2.5),
        ("lighting", 2.0), ("circuit", 2.0), ("switchgear", 2.0), ("junction box", 1.5),
        ("conduit", 1.5), ("transformer", 1.5), ("fire alarm", 1.5), ("power plan", 2.0),
    ),
    "plumbing": (
        ("plumbing", 3.0), ("sanitary", 2.5), ("domestic water", 2.5), ("waste and vent", 2.5),
        ("storm", 1.5), ("cold water", 2.0), ("hot water", 2.0), ("cleanout", 1.5),
        ("floor drain", 1.5), ("water closet", 1.5), ("lavatory", 1.2), ("riser diagram", 1.0),
    ),
    "fire_protection": (
        ("fire protection", 3.0), ("sprinkler", 3.0), ("standpipe", 2.5), ("fire pump", 2.0),
        ("nfpa 13", 2.0), ("wet pipe", 1.5), ("dry pipe", 1.5),
    ),
    "architectural": (
        ("architectural", 2.5), ("floor plan", 1.0), ("reflected ceiling", 1.5),
        ("partition", 1.2), ("finish schedule", 1.5), ("door schedule", 1.5),
    ),
}

#: Boilerplate that appears in title blocks but never in a sheet title.
_TITLE_NOISE = (
    "ACCEPTANCE", "REVIEW OF", "APPROVAL", "SHALL", "CONTRACTOR", "RESPONSIB",
    "NOT RELIEVE", "COMPLIANCE", "DOCUMENTS DOES", "CONSULTANT", "COPYRIGHT",
)

_NON_PLAN = (
    "schedule", "legend", "abbreviation", "general notes", "cover sheet", "index",
    "detail", "riser diagram", "diagram", "specification", "title sheet",
)

#: Discipline-specific line annotations, e.g. (N)2"LW or 42/20 SA
_PIPE_TAG = re.compile(r'\(?[NE]\)?\s*\d+\s*["″]\s*(?:CW|HW|HWR|SS|SV|LW|LV|NG|ST|W|V|CD|FP)\b', re.I)
_DUCT_TAG = re.compile(r"\b\d{1,3}\s*/\s*\d{1,3}\s*(?:SA|RA|EA|OA|MA)\b", re.I)
_ROUND_DUCT = re.compile(r"\b\d{1,2}\s*[ø⌀]")


@dataclass
class DisciplineResult:
    discipline: str
    confidence: float
    is_plan: bool
    evidence: str
    sheet_number: str = ""
    sheet_title: str = ""
    scores: dict[str, float] | None = None


def _sheet_number(sheet: Sheet) -> tuple[str, str]:
    """Sheet number and title usually live in the bottom-right title block."""
    w, h = sheet.info.width_pt, sheet.info.height_pt
    best_num, best_title = "", ""
    best_size = 0.0
    for t in sheet.texts:
        cx, cy = t.center
        in_block = cx > w * 0.62 and cy > h * 0.55
        if not in_block:
            continue
        txt = t.text.strip()
        # A sheet number is an uppercase discipline prefix plus a number, set
        # in the largest type in the title block. Requiring all three keeps
        # room tags and equipment marks out.
        if (
            re.fullmatch(r"(?:FP|SP|MP|PP|EP|[MEPAHCSFGTQIL])[- ]?\d{1,3}(?:\.\d{1,2})?[A-Z]?", txt)
            and t.size >= best_size
            and t.size >= 6.0
        ):
            best_num, best_size = txt, t.size
        # A sheet title is a short, all-caps noun phrase naming the drawing.
        # Title blocks are full of long all-caps boilerplate ("PLAN REVIEW
        # ACCEPTANCE OF DOCUMENTS..."), so require the drawing-type keyword and
        # reject the legal wording around it.
        upper = txt.upper()
        if (
            8 <= len(txt) <= 52
            and txt.isupper()
            and any(k in upper for k in ("PLAN", "SCHEDULE", "DIAGRAM", "DETAIL", "LEGEND", "SECTION"))
            and not any(k in upper for k in _TITLE_NOISE)
            and (not best_title or len(txt) < len(best_title))
        ):
            best_title = txt
    return best_num, best_title


def classify_discipline(sheet: Sheet, filename_hint: str = "") -> DisciplineResult:
    text = (sheet.text_blob() + "\n" + filename_hint).lower()
    scores: dict[str, float] = {d: 0.0 for d in DISCIPLINES if d != "unknown"}
    evidence: list[str] = []

    for disc, kws in _KEYWORDS.items():
        for kw, weight in kws:
            n = text.count(kw)
            if n:
                scores[disc] += weight * min(n, 6) ** 0.5
                if weight >= 2.0 and len(evidence) < 4:
                    evidence.append(f"'{kw}' x{n}")

    number, title = _sheet_number(sheet)
    hay = f"{number} {filename_hint}"
    for rx, disc in _SHEET_PREFIX:
        if rx.search(hay):
            scores[disc] += 6.0
            evidence.insert(0, f"sheet number '{number or filename_hint[:12]}'")
            break

    # Annotation grammar is a very strong tell.
    n_pipe = len(_PIPE_TAG.findall(sheet.text_blob()))
    n_duct = len(_DUCT_TAG.findall(sheet.text_blob())) + len(_ROUND_DUCT.findall(sheet.text_blob()))
    if n_pipe >= 3:
        scores["plumbing"] += 4.0 + min(n_pipe, 40) ** 0.5
        evidence.append(f"{n_pipe} pipe size tags")
    if n_duct >= 3:
        scores["mechanical"] += 4.0 + min(n_duct, 40) ** 0.5
        evidence.append(f"{n_duct} duct size tags")

    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1.0
    conf = scores[best] / total
    if scores[best] < 2.0:
        best, conf = "unknown", 0.0

    lower_title = (title or "").lower()
    is_plan = True
    for kw in _NON_PLAN:
        if kw in lower_title:
            is_plan = False
            break
    # A plan sheet is geometry-dense; schedules and notes are text-dense.
    if sheet.info.n_foreground < 400:
        is_plan = False

    return DisciplineResult(
        discipline=best,
        confidence=round(min(0.99, conf + 0.15), 3),
        is_plan=is_plan,
        evidence="; ".join(evidence[:5]) or "no strong signal",
        sheet_number=number,
        sheet_title=title,
        scores={k: round(v, 2) for k, v in scores.items()},
    )
