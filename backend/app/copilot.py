"""
Level 3 — the engineering copilot.

Two things make this useful rather than decorative:

**It never invents a number.** Every quantity comes from a tool call against the
analysis result, and each answer carries the citations — sheet, run id, rule id —
that produced it. The LLM's job is to choose tools, read what comes back and
explain it in engineering language, not to recall figures.

**It works without an LLM.** The same tools are wired to a deterministic intent
router, so the assistant still answers "how much 12-inch supply duct is on
M-3.1?" with no API key configured. Where a key is present, the LLM handles the
open-ended reasoning — *why* something was flagged, what to check next — that
rules cannot.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from .config import settings

# ---------------------------------------------------------------------------
# Tools over the analysis result
# ---------------------------------------------------------------------------


def _sheets(result: dict) -> list[dict]:
    return result.get("sheets", []) or []


def _match_sheets(result: dict, sheet: str | None) -> list[dict]:
    sheets = _sheets(result)
    if not sheet:
        return sheets
    q = str(sheet).strip().lower()
    hits = [
        s for s in sheets
        if q == str(s.get("sheet_label", "")).lower()
        or q == str(s.get("page_number"))
        or q in str(s.get("sheet_title", "")).lower()
        or q in str(s.get("discipline", "")).lower()
    ]
    return hits or sheets


def tool_project_overview(result: dict, **_) -> dict:
    t = result.get("totals", {})
    return {
        "file": result.get("file_name"),
        "pages_in_document": result.get("page_count"),
        "sheets_analysed": result.get("analysed_sheets"),
        "sheets": [
            {k: s.get(k) for k in ("sheet_label", "sheet_title", "discipline_label", "level", "scale",
                                   "detections", "runs", "length_ft", "findings")}
            for s in result.get("sheet_index", [])
        ],
        "component_total": t.get("component_total"),
        "duct_length_ft": t.get("duct_length_ft"),
        "pipe_length_ft": t.get("pipe_length_ft"),
        "run_count": t.get("run_count"),
        "finding_count": t.get("finding_count"),
        "findings_by_severity": t.get("findings_by_severity"),
        "clashes": result.get("clash_summary"),
    }


def tool_component_counts(result: dict, sheet: str | None = None, category: str | None = None, **_) -> dict:
    rows: list[dict] = []
    for s in _match_sheets(result, sheet):
        for c in s.get("counts", []):
            if category and category.lower() not in c["category"].lower():
                continue
            rows.append({
                "sheet": s.get("sheet_label"), "discipline": s.get("discipline"),
                "category": c["category"], "count": c["count"],
                "group": c.get("category_group"), "mean_confidence": c.get("mean_confidence"),
            })
    total = sum(r["count"] for r in rows)
    return {"rows": rows[:120], "row_count": len(rows), "total_count": total}


def tool_linear_quantities(result: dict, sheet: str | None = None, service: str | None = None,
                           size: str | None = None, **_) -> dict:
    by_service: dict[str, dict] = {}
    by_size: dict[str, dict] = {}
    total = 0.0
    for s in _match_sheets(result, sheet):
        lin = s.get("linear") or {}
        for row in lin.get("by_service", []):
            if service and service.lower() not in str(row.get("service", "")).lower():
                continue
            r = by_service.setdefault(row["service"], {"service": row["service"], "runs": 0, "length_ft": 0.0})
            r["runs"] += row["runs"]
            r["length_ft"] += row["length_ft"]
        for row in lin.get("by_size", []):
            if size and size.lower() not in str(row.get("size", "")).lower():
                continue
            if service and service.lower() not in str(row.get("service") or "").lower():
                continue
            r = by_size.setdefault(row["size"], {"size": row["size"], "service": row.get("service"),
                                                 "runs": 0, "length_ft": 0.0})
            r["runs"] += row["runs"]
            r["length_ft"] += row["length_ft"]
            total += row["length_ft"]
    for d in (by_service, by_size):
        for r in d.values():
            r["length_ft"] = round(r["length_ft"], 1)
    return {
        "by_service": sorted(by_service.values(), key=lambda r: -r["length_ft"])[:40],
        "by_size": sorted(by_size.values(), key=lambda r: -r["length_ft"])[:40],
        "matched_length_ft": round(total, 1),
        "project_duct_ft": result.get("totals", {}).get("duct_length_ft"),
        "project_pipe_ft": result.get("totals", {}).get("pipe_length_ft"),
    }


def tool_longest_runs(result: dict, sheet: str | None = None, limit: int = 10, **_) -> dict:
    runs: list[dict] = []
    for s in _match_sheets(result, sheet):
        lin = s.get("linear") or {}
        for r in lin.get("runs", [])[: max(200, limit * 5)]:
            runs.append({
                "sheet": s.get("sheet_label"), "run_id": r["id"], "kind": r["kind"],
                "length_ft": r["length_ft"], "length": r["length_label"],
                "size": r.get("size_label"), "service": r.get("service_name"),
                "bbox_pt": r.get("bbox_pt"),
            })
    runs.sort(key=lambda r: -r["length_ft"])
    return {"runs": runs[: min(int(limit or 10), 50)]}


def tool_findings(result: dict, severity: str | None = None, rule_id: str | None = None,
                  sheet: str | None = None, limit: int = 15, **_) -> dict:
    rows: list[dict] = []
    for s in _match_sheets(result, sheet):
        for f in s.get("findings", []):
            if severity and f["severity"] != severity.lower():
                continue
            if rule_id and f["rule_id"].lower() != rule_id.lower():
                continue
            rows.append({
                "sheet": s.get("sheet_label"), "rule_id": f["rule_id"], "title": f["title"],
                "severity": f["severity"], "message": f["message"],
                "recommendation": f.get("recommendation"), "location_pt": f.get("location_pt"),
                "status": f.get("status", "open"),
            })
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    rows.sort(key=lambda r: order.get(r["severity"], 9))
    return {"findings": rows[: min(int(limit or 15), 60)], "total": len(rows)}


def tool_clashes(result: dict, severity: str | None = None, limit: int = 15, **_) -> dict:
    rows = result.get("clashes", []) or []
    if severity:
        rows = [c for c in rows if c["severity"] == severity.lower()]
    return {
        "clashes": [
            {k: c.get(k) for k in ("id", "trade_a", "trade_b", "sheet_a", "sheet_b", "level",
                                   "severity", "message", "overlap_in", "location_pt")}
            for c in rows[: min(int(limit or 15), 60)]
        ],
        "summary": result.get("clash_summary"),
    }


def tool_sheet_detail(result: dict, sheet: str | None = None, **_) -> dict:
    hits = _match_sheets(result, sheet)
    if not hits:
        return {"error": "no matching sheet"}
    s = hits[0]
    lin = s.get("linear") or {}
    return {
        "sheet": s.get("sheet_label"), "title": s.get("sheet_title"),
        "discipline": s.get("discipline_label"), "level": s.get("level"),
        "scale": s.get("scale"), "counts": s.get("counts"),
        "linear_summary": {
            "kind": lin.get("kind"), "runs": lin.get("run_count"),
            "total_length_ft": lin.get("total_length_ft"),
            "by_service": lin.get("by_service", [])[:12], "by_size": lin.get("by_size", [])[:12],
            "layer": lin.get("layer"),
        },
        "connectivity": s.get("connectivity"),
        "findings_summary": s.get("findings_summary"),
        "unnamed_glyphs": [
            {"glyph_id": g["glyph_id"], "count": g["count"], "size_pt": [g["width_pt"], g["height_pt"]]}
            for g in s.get("glyphs", []) if g.get("source") == "mined" and g.get("count", 0) >= 4
        ][:10],
    }


def tool_bill_of_quantities(result: dict, limit: int = 40, **_) -> dict:
    from mepiq_core.exporters import bill_of_quantities

    rows = bill_of_quantities(_sheets(result))
    return {"items": rows[: min(int(limit or 40), 200)], "item_count": len(rows)}


def tool_explain_detection(result: dict, sheet: str | None = None, category: str | None = None,
                           limit: int = 5, **_) -> dict:
    out: list[dict] = []
    for s in _match_sheets(result, sheet):
        for d in s.get("detections", []):
            if category and category.lower() not in d["category"].lower():
                continue
            out.append({
                "sheet": s.get("sheet_label"), "category": d["category"],
                "confidence": d["confidence"], "detector": d["detector"],
                "why": d.get("rationale"), "attributes": d.get("attributes"),
                "bbox_pt": d.get("bbox_pt"),
            })
            if len(out) >= min(int(limit or 5), 25):
                return {"detections": out}
    return {"detections": out}


TOOLS: dict[str, Callable[..., dict]] = {
    "project_overview": tool_project_overview,
    "component_counts": tool_component_counts,
    "linear_quantities": tool_linear_quantities,
    "longest_runs": tool_longest_runs,
    "findings": tool_findings,
    "clashes": tool_clashes,
    "sheet_detail": tool_sheet_detail,
    "bill_of_quantities": tool_bill_of_quantities,
    "explain_detection": tool_explain_detection,
}


OPENAI_TOOLS = [
    {"type": "function", "function": {
        "name": "project_overview",
        "description": "Totals for the whole drawing set: sheets analysed, component count, duct and pipe lengths, findings and clashes.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "component_counts",
        "description": "Counts of detected MEP components, optionally filtered by sheet and/or category.",
        "parameters": {"type": "object", "properties": {
            "sheet": {"type": "string", "description": "Sheet number, page number, title fragment or discipline."},
            "category": {"type": "string", "description": "Component name fragment, e.g. 'diffuser', 'damper'."},
        }},
    }},
    {"type": "function", "function": {
        "name": "linear_quantities",
        "description": "Duct and pipe lengths in feet, grouped by service and by size. Filter by sheet, service or size.",
        "parameters": {"type": "object", "properties": {
            "sheet": {"type": "string"}, "service": {"type": "string"}, "size": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "longest_runs",
        "description": "The longest individual duct or pipe runs, with ids and locations.",
        "parameters": {"type": "object", "properties": {
            "sheet": {"type": "string"}, "limit": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "findings",
        "description": "Design-validation and constructability findings, filterable by severity, rule id or sheet.",
        "parameters": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
            "rule_id": {"type": "string"}, "sheet": {"type": "string"}, "limit": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "clashes",
        "description": "Cross-discipline coordination conflicts found by overlaying same-level sheets.",
        "parameters": {"type": "object", "properties": {
            "severity": {"type": "string"}, "limit": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "sheet_detail",
        "description": "Everything known about one sheet: scale, counts, linear summary, connectivity, unnamed symbols.",
        "parameters": {"type": "object", "properties": {"sheet": {"type": "string"}}, "required": ["sheet"]},
    }},
    {"type": "function", "function": {
        "name": "bill_of_quantities",
        "description": "The priceable bill of quantities rolled up across the whole set.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "explain_detection",
        "description": "Why a specific component was detected — the geometric evidence and confidence.",
        "parameters": {"type": "object", "properties": {
            "sheet": {"type": "string"}, "category": {"type": "string"}, "limit": {"type": "integer"},
        }},
    }},
]


SYSTEM_PROMPT = """You are the MEPIQ copilot, an assistant for engineers reviewing Mechanical, \
Electrical and Plumbing construction drawings.

Rules you must follow:
- Never state a quantity, count, length or finding that did not come from a tool result in this \
conversation. If a tool returns nothing, say so plainly.
- Cite where each number came from: sheet number, run id, or rule id.
- Use the units the tools return (feet for lengths, EA for counts). Round sensibly.
- Be concise and use engineering language. A superintendent should be able to act on your answer.
- When a quantity depends on the drawing scale, and the scale was not read from the sheet, say that \
the figure is provisional until the scale is confirmed.
- If asked for an opinion on risk or constructability, ground it in the findings the tools return, \
and be clear about what is a flag for review versus a definite error.
- You are not a licensed engineer and the output is a review aid, not a certified takeoff. Mention \
this only when the user asks for sign-off or code compliance."""


# ---------------------------------------------------------------------------
# Deterministic router (no API key required)
# ---------------------------------------------------------------------------


_NUM = r"[\d,]+(?:\.\d+)?"


def _fmt_ft(v: float) -> str:
    return f"{v:,.0f} ft"


def deterministic_answer(result: dict, question: str) -> dict:
    q = question.lower().strip()
    calls: list[dict] = []

    def call(name: str, **kw) -> dict:
        out = TOOLS[name](result, **kw)
        calls.append({"tool": name, "arguments": kw, "result_preview": _preview(out)})
        return out

    sheet = None
    m = re.search(r"\b(?:on|for|sheet)\s+([A-Z]{1,3}-?\d{1,3}(?:\.\d{1,2})?)\b", question, re.I)
    if m:
        sheet = m.group(1)

    # --- clashes -----------------------------------------------------------
    if any(k in q for k in ("clash", "conflict", "coordination", "collide", "interfere", "cross-discipline")):
        data = call("clashes", limit=10)
        s = data["summary"] or {}
        if not data["clashes"]:
            text = "No cross-discipline conflicts were found. That covers only sheets of different trades at the same level and scale that could be overlaid."
        else:
            lines = [f"**{s.get('total', 0)} coordination conflicts** across the set."]
            for c in data["clashes"][:6]:
                lines.append(f"- `{c['severity']}` {c['trade_a']} / {c['trade_b']} on {c['sheet_a']} vs {c['sheet_b']} — {c['message']}")
            text = "\n".join(lines)
        return {"text": text, "tool_calls": calls, "mode": "deterministic"}

    # --- findings / issues -------------------------------------------------
    if any(k in q for k in (
        "issue", "problem", "finding", "risk", "wrong", "error", "review", "flag", "validate",
        "look at first", "priority", "prioriti", "worry", "concern", "attention", "check first",
        "what should i", "biggest", "worst", "urgent", "unconnected", "orphan", "untagged",
    )):
        sev = next((s for s in ("critical", "high", "medium", "low") if s in q), None)
        data = call("findings", severity=sev, sheet=sheet, limit=10)
        if not data["findings"]:
            text = "No open findings match that filter."
        else:
            lines = [
                f"**{data['total']} findings**" + (f" at {sev} severity" if sev else "")
                + ", highest severity first:"
            ]
            for f in data["findings"][:8]:
                lines.append(f"- `{f['rule_id']}` **{f['severity']}** on {f['sheet']} — {f['message']}")
                if f.get("recommendation"):
                    lines.append(f"  - _{f['recommendation']}_")
            text = "\n".join(lines)
        return {"text": text, "tool_calls": calls, "mode": "deterministic"}

    # --- linear quantities -------------------------------------------------
    if any(k in q for k in ("length", "linear", "how much duct", "how much pipe", "footage", "lf",
                            "duct", "pipe", "ductwork", "piping")) and not any(
            k in q for k in ("how many diffuser", "how many damper", "count")):
        service = None
        for key in ("supply", "return", "exhaust", "sanitary", "vent", "cold water", "hot water",
                    "gas", "storm", "fire protection", "chilled"):
            if key in q:
                service = key
                break
        size = None
        ms = re.search(r"\b(\d{1,3})\s*(?:\"|inch|in\b|ø)", q)
        if ms:
            size = ms.group(1)
        data = call("linear_quantities", sheet=sheet, service=service, size=size)
        lines = []
        if data["project_duct_ft"]:
            lines.append(f"**Ductwork total: {_fmt_ft(data['project_duct_ft'])}**")
        if data["project_pipe_ft"]:
            lines.append(f"**Piping total: {_fmt_ft(data['project_pipe_ft'])}**")
        if data["by_service"]:
            lines.append("\nBy service:")
            for r in data["by_service"][:8]:
                lines.append(f"- {r['service']}: {_fmt_ft(r['length_ft'])} across {r['runs']} runs")
        if data["by_size"]:
            lines.append("\nBy size:")
            for r in data["by_size"][:8]:
                lines.append(f"- {r['size']}: {_fmt_ft(r['length_ft'])} ({r['runs']} runs)")
        return {"text": "\n".join(lines) or "No linear quantities were measured.",
                "tool_calls": calls, "mode": "deterministic"}

    # --- counts ------------------------------------------------------------
    if any(k in q for k in ("how many", "count", "quantity", "diffuser", "damper", "register",
                            "grille", "heat pump", "component")):
        cat = None
        for key in ("diffuser", "damper", "register", "grille", "heat pump", "flex", "benchmark"):
            if key in q:
                cat = key
                break
        data = call("component_counts", sheet=sheet, category=cat)
        if not data["rows"]:
            text = "No components match that filter."
        else:
            agg: dict[str, int] = {}
            for r in data["rows"]:
                agg[r["category"]] = agg.get(r["category"], 0) + r["count"]
            lines = [f"**{data['total_count']} components**" + (f" matching '{cat}'" if cat else "") + ":"]
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1]):
                lines.append(f"- {k}: **{v}**")
            if sheet:
                lines.append(f"\n(on sheet {sheet})")
            text = "\n".join(lines)
        return {"text": text, "tool_calls": calls, "mode": "deterministic"}

    # --- bill of quantities ------------------------------------------------
    if any(k in q for k in ("boq", "bill of quantities", "takeoff", "estimate", "price", "cost")):
        data = call("bill_of_quantities", limit=20)
        lines = [f"**Bill of quantities — {data['item_count']} line items.** Top items:"]
        for it in data["items"][:12]:
            size = f" {it['size']}" if it.get("size") else ""
            lines.append(f"- {it['section']} · {it['description']}{size}: **{it['quantity']:,} {it['unit']}**")
        return {"text": "\n".join(lines), "tool_calls": calls, "mode": "deterministic"}

    # --- sheet detail ------------------------------------------------------
    if sheet or "sheet" in q or "scale" in q:
        data = call("sheet_detail", sheet=sheet)
        if "error" in data:
            return {"text": "I could not find that sheet in the analysis.", "tool_calls": calls, "mode": "deterministic"}
        sc = data.get("scale") or {}
        lines = [
            f"**{data['sheet']}** — {data.get('title') or data['discipline']}",
            f"- Scale: **{sc.get('label')}** ({sc.get('method')}, confidence {sc.get('confidence')}) — {sc.get('evidence')}",
        ]
        ls = data.get("linear_summary") or {}
        if ls.get("runs"):
            lines.append(f"- {ls['kind'].title()}work: {ls['runs']} runs, {_fmt_ft(ls.get('total_length_ft') or 0)}")
        for c in (data.get("counts") or [])[:8]:
            lines.append(f"- {c['category']}: {c['count']}")
        fs = data.get("findings_summary") or {}
        if fs.get("total"):
            lines.append(f"- {fs['total']} findings on this sheet")
        return {"text": "\n".join(lines), "tool_calls": calls, "mode": "deterministic"}

    # --- default: overview -------------------------------------------------
    data = call("project_overview")
    lines = [
        f"**{data.get('file')}** — {data.get('sheets_analysed')} of {data.get('pages_in_document')} pages analysed.",
        f"- Components detected: **{data.get('component_total') or 0}**",
    ]
    if data.get("duct_length_ft"):
        lines.append(f"- Ductwork measured: **{_fmt_ft(data['duct_length_ft'])}**")
    if data.get("pipe_length_ft"):
        lines.append(f"- Piping measured: **{_fmt_ft(data['pipe_length_ft'])}**")
    lines.append(f"- Runs traced: {data.get('run_count') or 0}")
    lines.append(f"- Findings: {data.get('finding_count') or 0} — {data.get('findings_by_severity')}")
    cl = data.get("clashes") or {}
    if cl.get("total"):
        lines.append(f"- Cross-discipline conflicts: {cl['total']}")
    lines.append("\nAsk me about a sheet, a component, duct or pipe lengths, findings or the bill of quantities.")
    return {"text": "\n".join(lines), "tool_calls": calls, "mode": "deterministic"}


def _preview(obj: Any, limit: int = 600) -> str:
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    return s[:limit] + ("…" if len(s) > limit else "")


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def llm_answer(result: dict, question: str, history: list[dict] | None = None) -> dict:
    """OpenAI tool-calling loop. Falls back to the deterministic router on error."""
    try:
        from openai import OpenAI
    except Exception:
        return deterministic_answer(result, question)

    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    client = OpenAI(**kwargs)

    overview = _preview(tool_project_overview(result), 1800)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Analysis context for the currently open drawing set:\n{overview}"},
    ]
    for h in (history or [])[-8:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    calls: list[dict] = []
    try:
        for _ in range(settings.copilot_max_tool_calls):
            resp = client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return {
                    "text": msg.content or "",
                    "tool_calls": calls,
                    "mode": "llm",
                    "model": settings.openai_model,
                }
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                fn = TOOLS.get(name)
                out = fn(result, **args) if fn else {"error": f"unknown tool {name}"}
                calls.append({"tool": name, "arguments": args, "result_preview": _preview(out)})
                messages.append({
                    "role": "tool", "tool_call_id": tc.id, "name": name,
                    "content": json.dumps(out, default=str)[:12000],
                })
        # Ran out of tool turns — ask for a final answer with what we have.
        resp = client.chat.completions.create(
            model=settings.openai_model, messages=messages, temperature=0.2,
        )
        return {"text": resp.choices[0].message.content or "", "tool_calls": calls,
                "mode": "llm", "model": settings.openai_model}
    except Exception as exc:  # pragma: no cover - network dependent
        fallback = deterministic_answer(result, question)
        fallback["text"] = (
            fallback["text"]
            + f"\n\n_(Answered from the analysis directly — the language model was unavailable: {type(exc).__name__}.)_"
        )
        fallback["mode"] = "deterministic-fallback"
        return fallback


def answer(result: dict, question: str, history: list[dict] | None = None, prefer_llm: bool = True) -> dict:
    if prefer_llm and settings.llm_enabled:
        return llm_answer(result, question, history)
    return deterministic_answer(result, question)


SUGGESTIONS = [
    "Give me a summary of this drawing set",
    "How much supply air ductwork is there, by size?",
    "What are the highest-severity issues I should look at first?",
    "Which runs are not connected to anything?",
    "How many fire dampers are on each sheet?",
    "Show me the bill of quantities",
    "Are there any cross-discipline conflicts?",
    "How was the drawing scale determined?",
]
