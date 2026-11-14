"""Reviewer edits, stored beside the cache and applied by the app only.

The batch runner never loads these, so human review cannot leak into the score.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .schema import Drawing, Element

REVIEWS_DIR = Path("reviews")
# Elements a reviewer adds get ids from here up, so re-extraction (which numbers from 1) never
# collides with them.
ADDED_ID_BASE = 1_000_000


def review_path(cache_file: Path) -> Path:
    return REVIEWS_DIR / cache_file.name


def load_reviews(cache_file: Path) -> list[dict]:
    path = review_path(cache_file)
    return json.loads(path.read_text()) if path.exists() else []


def next_added_id(edits: list[dict]) -> int:
    return max([e["id"] for e in edits if e["action"] == "add"], default=ADDED_ID_BASE - 1) + 1


VERDICTS = {"accept", "reject", "retype"}


def _group(edit: dict) -> str:
    """An element keeps one verdict (accept, reject or retype) and one reshape, independently."""
    return "verdict" if edit["action"] in VERDICTS else edit["action"]


def _bounds(polygon: list[list[float]]) -> list[float]:
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def save_review(cache_file: Path, edit: dict) -> None:
    edits = load_reviews(cache_file)
    added = {e["id"] for e in edits if e["action"] == "add"}
    if edit["action"] == "reject" and edit["id"] in added:
        # Rejecting something a reviewer added takes the addition back.
        edits = [e for e in edits if e["id"] != edit["id"]]
    elif edit["id"] in added and edit["action"] == "retype":
        edits = [{**e, "type": edit["type"]} if e["id"] == edit["id"] else e for e in edits]
    elif edit["id"] in added and edit["action"] == "reshape":
        shape = {k: edit[k] for k in ("bbox", "polygon") if edit.get(k) is not None}
        edits = [{**e, **shape} if e["id"] == edit["id"] else e for e in edits]
    elif edit["id"] in added:
        return  # accepting an addition changes nothing
    else:
        edits = [e for e in edits if not (e["id"] == edit["id"] and _group(e) == _group(edit))] + [edit]
    path = review_path(cache_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edits, indent=2))


def shape_area(bbox: list[float] | None, polygon: list[list[float]] | None) -> float | None:
    """Area of an outline (or box) in drawing units squared."""
    if polygon and len(polygon) >= 3:
        from shapely.geometry import Polygon

        return abs(Polygon(polygon).area)
    if bbox:
        return abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    return None


def _reshaped(el: Element, edit: dict, drawing: Drawing) -> Element:
    polygon = edit.get("polygon")
    bbox = _bounds(polygon) if polygon else edit.get("bbox", el.bbox)
    changes: dict = {"bbox": bbox, "polygon": polygon if polygon else (None if edit.get("bbox") else el.polygon), "conf": max(el.conf, 1.0)}
    if el.type in ("room", "apartment"):
        changes.update(_recalculated_area(el, bbox, changes["polygon"], drawing))
    return replace(el, **changes)


def _recalculated_area(el: Element, bbox, polygon, drawing: Drawing) -> dict:
    """A reshaped room's area follows its new outline, unless the area is printed on the plan (that
    number is the drawing's own). Image plans use their scale and keep its error margin; CAD and IFC
    areas become the reviewer's outline in metres (no longer read from the file, so not exact)."""
    q, src = dict(el.quantities or {}), dict(el.quantity_source or {})
    if src.get("area_m2") == "label":
        return {}
    px = shape_area(bbox, polygon)
    if px is None:
        return {}
    if drawing.kind == "raster" and drawing.scale:
        area = px * drawing.scale["m_per_px"] ** 2
        q.update(area_m2=round(area, 2), area_m2_err=round(area * drawing.scale["rel_err"], 2))
        src["area_m2"] = "scale"
    elif drawing.kind in ("ifc", "dxf") and drawing.units == "m":
        q["area_m2"] = round(px, 3)
        q.pop("area_m2_err", None)
        src["area_m2"] = "reviewer"
    else:
        return {}
    return {"quantities": q, "quantity_source": src}


def apply_reviews(drawing: Drawing, edits: list[dict]) -> Drawing:
    verdicts = {e["id"]: e for e in edits if e["action"] in VERDICTS}
    shapes = {e["id"]: e for e in edits if e["action"] == "reshape"}
    elements = []
    for el in drawing.elements:
        if el.id in shapes:
            el = _reshaped(el, shapes[el.id], drawing)
        edit = verdicts.get(el.id)
        if edit is None:
            elements.append(el)
        elif edit["action"] == "accept":
            elements.append(replace(el, conf=1.0))
        elif edit["action"] == "retype":
            elements.append(replace(el, conf=1.0, type=edit["type"]))
        # "reject" drops the element.
    for e in edits:
        if e["action"] == "add":
            # Counted like a confirmed mark; never exact, since it was not read from the file.
            polygon = e.get("polygon")
            elements.append(Element(id=e["id"], type=e["type"], source="added by reviewer", exact=False, conf=1.0,
                                    bbox=_bounds(polygon) if polygon else e["bbox"], polygon=polygon,
                                    room_type=e.get("room_type"), label=e.get("label"), storey=e.get("storey")))
    covers = drawing.covers
    added_types = {e["type"] for e in edits if e["action"] == "add"} | {e.get("room_type") for e in edits if e["action"] == "add"}
    if covers is not None:
        # A type the reviewer marked by hand is now counted from marks, like the types the extractor marks.
        covers = list(covers) + sorted(t for t in added_types if t and t not in covers and t != "room")
    return replace(drawing, elements=elements, covers=covers)
