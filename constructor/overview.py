"""What a drawing can tell without being asked: its standard facts, its rooms, and short suggestions.

Facts are answered by the same answer() as typed questions, from the same cached file, so the
overview and the chat never disagree. No model calls: only the rule-based mapper.
"""

from __future__ import annotations

import re
from pathlib import Path

from .answer import answer
from .schema import Answer, Drawing

# (key, label, question, short suggestion). Questions use phrasings the rule-based mapper handles.
RASTER_FACTS = [
    ("window", "Windows", "How many windows are shown on this floor plan?", "How many windows?"),
    ("door", "Doors", "How many doors are shown on this floor plan?", "How many doors?"),
    ("bedroom", "Bedrooms", "How many bedrooms are on this floor plan?", "How many bedrooms?"),
    ("bathroom", "Bathrooms", "How many bathrooms or washrooms are on this floor plan, not counting separate WC rooms?", "How many bathrooms?"),
    ("wc_room", "WC rooms", "How many separate WC rooms are on this floor plan?", None),
    ("kitchen", "Kitchens", "How many kitchens are on this floor plan?", None),
    ("sauna", "Saunas", "How many saunas are on this floor plan?", "How many saunas?"),
    ("balcony", "Balconies", "How many balconies are on this floor plan?", None),
    ("wc", "WC seats", "How many toilet bowls (WC seats) are drawn on this floor plan?", "How many toilets?"),
    ("sink", "Sinks", "How many sinks and wash basins are drawn on this floor plan?", None),
    ("shower_or_bathtub", "Showers and bathtubs", "How many showers and bathtubs are drawn on this floor plan in total?", None),
    ("storey", "Floors shown", "How many floors (storeys) does this floor plan show?", None),
]
DXF_FACTS = [
    ("apartment", "Apartments", "How many apartments (residential units) are shown on this floor plan?", "How many apartments?"),
    ("indoor_area", "Net indoor area", "What is the total net floor area in m² of all numbered indoor rooms on this floor?", "Total net indoor area?"),
    ("door", "Doors", "How many doors are drawn on this floor plan?", "How many doors?"),
    ("window", "Windows", "How many windows are drawn on this floor plan?", "How many windows?"),
    ("wc", "Toilets", "How many toilets (WC) are drawn on this floor plan?", None),
    ("sink", "Washbasins", "How many washbasins are drawn on this floor plan?", None),
    ("bathtub", "Bathtubs", "How many bathtubs are drawn on this floor plan?", None),
    ("shower", "Showers", "How many showers are drawn on this floor plan?", None),
]
IFC_FACTS = [
    ("storey", "Storeys", "How many storeys are there?", "How many storeys?"),
    ("space", "Rooms (spaces)", "How many rooms (spaces) are there?", "How many rooms?"),
    ("door", "Doors", "How many doors are there?", "How many doors?"),
    ("window", "Windows", "How many windows are there?", "How many windows?"),
    ("wall", "Walls", "How many walls are there?", None),
    ("column", "Columns", "How many columns are there?", None),
    ("beam", "Beams", "How many beams are there?", None),
    ("stair", "Stairs", "How many stairs are there?", None),
]
FACTS = {"raster": RASTER_FACTS, "dxf": DXF_FACTS, "ifc": IFC_FACTS, "pdf": []}


def _fact(d: Drawing, key: str, label: str, question: str, answer_text) -> dict | None:
    a = answer(d, question)
    if a.value is None:
        return None
    return {"key": key, "label": label, "question": question, "answer": {**a.to_dict(), "text": answer_text(a)}}


def facts(d: Drawing, answer_text) -> list[dict]:
    out = []
    for key, label, question, _ in FACTS.get(d.kind, []):
        if f := _fact(d, key, label, question, answer_text):
            out.append(f)
    if d.kind == "dxf":
        for letter in sorted({e.apartment for e in d.elements if e.type == "apartment" and e.apartment}):
            q = f"What is the net floor area of apartment {letter} in m², summing all its rooms except balconies?"
            if f := _fact(d, f"apartment_area:{letter}", f"Apartment {letter} area", q, answer_text):
                out.append(f)
    # Zero counts last: on a busy grid they are the least informative facts.
    out.sort(key=lambda f: f["answer"]["value"] == 0)
    if d.kind == "ifc":
        for storey in [e.label for e in d.elements if e.type == "storey" and e.label]:
            q = f"What is the total net floor area of all rooms (spaces) on '{storey}', in m²?"
            if f := _fact(d, f"storey_area:{storey}", f"Net area, {storey}", q, answer_text):
                out.append(f)
    return out


def rooms(d: Drawing) -> list[dict]:
    out = []
    for e in d.elements:
        if e.type != "room" or e.band == "dropped":
            continue
        area = (e.quantities or {}).get("area_m2")
        out.append({
            "id": e.id, "type": "room", "label": e.label, "number": e.number, "room_type": e.room_type,
            "area_m2": round(area, 2) if area is not None else None, "storey": e.storey, "apartment": e.apartment,
            "exact": bool(e.exact and (e.quantity_source or {}).get("area_m2") in ("quantity_set", "property", "model_geometry", "label")),
            "has_area": e.polygon is not None,
        })
    return out


def suggestions(d: Drawing, limit: int = 6) -> list[str]:
    """Short questions this drawing can answer, those with marks first."""
    scored = []
    for key, label, question, short in FACTS.get(d.kind, []):
        if not short:
            continue
        a: Answer = answer(d, short)
        if a.value is None:
            continue
        scored.append((0 if a.exact else 1 if a.evidence_ids else 2, short))
    out = [q for _, q in sorted(scored, key=lambda t: t[0])]
    if d.kind == "dxf":
        letters = sorted({e.apartment for e in d.elements if e.type == "apartment" and e.apartment})
        if letters:
            out.insert(1, f"Net area of apartment {letters[0]}?")
    if d.kind == "ifc":
        named = [e for e in d.elements if e.type == "room" and e.label and e.storey and (e.quantities or {}).get("area_m2")]
        if named:
            out.insert(1, f"Area of '{named[0].label}'?")
    return out[:limit]


# --- titles ----------------------------------------------------------------------------

SOURCE_NAMES = {
    "challenge": "Challenge sheets",
    "cubicasa5k": "CubiCasa5K", "swiss_dwellings": "Swiss Dwellings", "ifc_models": "IFC models",
    "ifc_bench": "IFC-Bench", "opening_design": "Opening Design",
}
TIERS = {"colorful": "colour", "high_quality": "high quality", "high_quality_architectural": "architectural"}


def title(path: str, table_title: str | None) -> str:
    p = Path(path)
    source = p.parts[1] if len(p.parts) > 2 else ""
    if source == "cubicasa5k":
        tier, _, number = p.stem.rpartition("-")
        return f"Finnish plan {number} ({TIERS.get(tier, tier)})"
    if source == "swiss_dwellings":
        m = re.match(r"site(\d+)_bldg(\d+)_floor(\d+)", p.stem)
        return f"Swiss apartment floor · site {m.group(1)}, building {m.group(2)}" if m else p.stem
    if table_title:
        return table_title
    return p.stem.replace("_", " ")


def subtitle(source: str, read_from: str, path: str = "") -> str:
    kind = {"ifc": "IFC model", "dxf": "CAD (DXF)", "pdf": "PDF", "raster": "image", "sheet": "technical sheet"}.get(read_from, read_from)
    if read_from == "ifc" and path.endswith(".pdf"):
        kind = "plan sheet, answered from its IFC model"
    elif read_from == "dxf" and path.endswith(".pdf"):
        kind = "plan, answered from its CAD file"
    exactness = "exact" if read_from in ("ifc", "dxf") else "estimate"
    return f"{SOURCE_NAMES.get(source, source)} · {kind} · {exactness}"
