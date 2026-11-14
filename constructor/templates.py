"""Answer templates: count, area, length and volume functions over a cached Drawing.

Each template takes (drawing, params) and returns an Answer, or None when the drawing
does not hold what it needs. Families and params come from mapper.py; the families were
derived from the train split's questions.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .schema import Answer, Drawing, Element

Template = Callable[[Drawing, dict], "Answer | None"]
TEMPLATES: dict[str, Template] = {}

# Question element -> Element.type values that count towards it.
ELEMENT_TYPES = {"shower_or_bathtub": {"shower", "bathtub"}, "space": {"room"}}


def template(name: str):
    def register(fn: Template) -> Template:
        TEMPLATES[name] = fn
        return fn

    return register


def round_half_up(x: float) -> int:
    # Python's round() rounds 0.5 to even, which would turn one 0.5 candidate into 0.
    return math.floor(x + 0.5)


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().casefold() == b.strip().casefold()


def _select(d: Drawing, types: set[str], params: dict) -> list[Element]:
    storey = params.get("storey")
    return [
        e
        for e in d.elements
        if e.type in types
        and e.band != "dropped"
        and (storey is None or _same(e.storey, storey))
        and ("room_type" not in params or e.room_type == params["room_type"])
        and ("label" not in params or _same(e.label, params["label"]))
        and ("name" not in params or _same(e.label, params["name"]))
        and ("number" not in params or _same(e.number, params["number"]))
        and ("apartment" not in params or _same(e.apartment, params["apartment"]))
        and (params.get("scope") != "numbered_indoor" or (e.number is not None and not e.outdoor))
    ]


def _storey_known(d: Drawing, params: dict) -> bool:
    # A storey the drawing does not have means a wrong mapping or extraction, not zero.
    storey = params.get("storey")
    return storey is None or any(_same(e.storey, storey) for e in d.elements)


# (element or room type) -> key in Drawing.counts, the vision model's whole-image counts.
COUNT_KEYS = {
    "window": "windows", "door": "doors", "wc": "wc_seats", "sink": "sinks",
    "shower_or_bathtub": "showers_and_bathtubs", "storey": "storeys", "sauna": "saunas",
    "kitchen": "kitchens", "bedroom": "bedrooms", "bathroom": "bathrooms", "wc_room": "wc_rooms",
    "balcony": "balconies",
}


def _whole_image(d: Drawing, key: str | None, params: dict, name: str, marks: list[Element] | None = None) -> Answer | None:
    """An estimate from the whole-image count. Marks of the same type, if any, are shown as
    uncertain evidence: they are not what the value was counted from, and may disagree with it."""
    if key is None or not d.counts or key not in d.counts:
        return None
    value = d.counts[key]
    lo, hi = value, value
    band = band_for(f"whole:{key}", value)
    if band:
        lo, hi = max(0, value + band["lo"]), value + band["hi"]
    if marks:  # the marks are a second opinion
        lo, hi = min(lo, len(marks)), max(hi, len(marks))
    return Answer(template=name, params=params, value=value, unit="count", exact=False,
                  range=[lo, hi] if lo < hi else None, uncertain_ids=[e.id for e in marks or []])


CALIBRATION_FILE = Path(__file__).with_name("calibration.json")


MIN_BUCKET = 15  # fewer train cases than this: use the type's overall band


def size_bucket(value: int) -> str:
    return "small" if value <= 3 else "medium" if value <= 9 else "large"


def band_for(key: str, value: int) -> dict | None:
    """The calibrated (gold - count) band for this kind of count at this size."""
    cal = calibration()
    return cal.get(f"{key}@{size_bucket(value)}") or cal.get(key)


@lru_cache(maxsize=1)
def calibration() -> dict:
    """Per type, how far a count usually is from the truth on train (gold - count, 10th and 90th
    percentile), written by scripts/calibrate.py: keyed by type for mark counts and by
    "whole:<counts key>" for whole-image counts. Empty until calibrated."""
    return json.loads(CALIBRATION_FILE.read_text()) if CALIBRATION_FILE.exists() else {}


def _estimate_range(what: str | None, value: int, lo: int, hi: int) -> list[int]:
    """Widen a mark count's range by how far marks of this type missed on train. (Not by the
    whole-image count: for the types counted from marks it is the worse estimate, e.g. windows
    right 15% of the time, and only stretched the range.)"""
    band = band_for(what or "", value)
    if band:
        lo, hi = min(lo, max(0, value + band["lo"])), max(hi, value + band["hi"])
    return [lo, hi]


def count(d: Drawing, types: set[str], params: dict, name: str) -> Answer | None:
    if not _storey_known(d, params):
        return None
    what = params.get("room_type") or params.get("element") or ("storey" if name == "count_storeys" else None)
    # covers may name element types ("window") or room types ("wc_room").
    covered = d.covers is None or (what in d.covers if params.get("room_type") else types <= set(d.covers))
    if not covered:
        return _whole_image(d, COUNT_KEYS.get(what), params, name, marks=_select(d, types, params))
    # "How many doors are in the model X?" asked of one plan: the plan shows only part of it.
    if "model" in params and d.kind != "ifc":
        return None
    elements = _select(d, types, params)
    confirmed = [e for e in elements if e.band == "confirmed"]
    uncertain = [e for e in elements if e.band == "uncertain"]
    # With nothing counted, only a structured file (covers is None) can be sure the answer is 0.
    exact = not uncertain and all(e.exact for e in confirmed) and (bool(confirmed) or d.covers is None)
    value = len(confirmed) + round_half_up(sum(e.conf for e in uncertain))
    rng = None if exact else [len(confirmed), len(confirmed) + len(uncertain)]
    # Image marks can miss things; the miss rates were measured on CubiCasa plans only, so other kinds
    # (technical sheets read in tiles) get no borrowed range.
    if rng is not None and d.covers is not None and d.kind == "raster":
        rng = _estimate_range(what, value, *rng)
    return Answer(
        template=name,
        params=params,
        value=value,
        unit="count",
        exact=exact,
        range=rng,
        evidence_ids=[e.id for e in confirmed],
        uncertain_ids=[e.id for e in uncertain],
    )


@template("count_elements")
def count_elements(d: Drawing, params: dict) -> Answer | None:
    element = params["element"]
    a = count(d, ELEMENT_TYPES.get(element, {element}), params, "count_elements")
    if a is not None and params.get("by") == "kind":
        # "How many valves by type?": the marks grouped by the kind the reader gave each one.
        marks = {e.id: e for e in d.elements}
        kinds: dict[str, int] = {}
        for i in a.evidence_ids + a.uncertain_ids:
            kind = marks[i].label or "unspecified"
            kinds[kind] = kinds.get(kind, 0) + 1
        if len(kinds) > 1 or "unspecified" not in kinds:
            a.params = {**a.params, "items": [{"label": k, "value": float(n), "unit": "count", "how": "counted"}
                                              for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])]}
    return a


@template("count_rooms")
def count_rooms(d: Drawing, params: dict) -> Answer | None:
    # A drawing whose rooms carry no room types cannot say how many bedrooms it has; 0 would be a guess.
    if "room_type" in params and not any(e.room_type for e in d.elements if e.type == "room"):
        return _whole_image(d, COUNT_KEYS.get(params["room_type"]), params, "count_rooms")
    return count(d, {"room"}, params, "count_rooms")


@template("count_storeys")
def count_storeys(d: Drawing, params: dict) -> Answer | None:
    # Extractors emit one "storey" element per storey (IFC) or per plan drawn in the image.
    if not any(e.type == "storey" for e in d.elements):
        return _whole_image(d, "storeys", params, "count_storeys")
    return count(d, {"storey"}, params, "count_storeys")


def _sum(name: str, params: dict, elements: list[Element], key: str, unit: str, read_sources: set[str]) -> Answer | None:
    """Sum a quantity over elements. Exact only if every value was read from the file."""
    values = [e.quantities.get(key) if e.quantities else None for e in elements]
    if not elements or any(v is None for v in values):
        return None
    exact = all(e.exact and (e.quantity_source or {}).get(key) in read_sources for e in elements)
    # Image plans: printed values, or pixels times an estimated scale with an error margin.
    errs = [(e.quantities or {}).get(f"{key}_err") or 0.0 for e in elements]
    total = sum(values)
    rng = [round(total - sum(errs), 2), round(total + sum(errs), 2)] if any(errs) and not exact else None
    basis = sorted({(e.quantity_source or {}).get(key) for e in elements} - {None})
    return Answer(
        template=name,
        params={**params, "basis": basis} if not exact and basis else params,
        value=round(total, 3),
        unit=unit,
        exact=exact,
        range=rng,
        evidence_ids=[e.id for e in elements if e.band == "confirmed"],
        uncertain_ids=[e.id for e in elements if e.band == "uncertain"],
    )


AREA_READ = {"quantity_set", "property", "model_geometry", "label"}


@template("room_area")
def room_area(d: Drawing, params: dict) -> Answer | None:
    rooms = _select(d, {"room"}, params)
    # One room only: two matches means the parameters were not specific enough.
    if len(rooms) != 1:
        return None
    return _sum("room_area", params, rooms, "area_m2", "m2", AREA_READ)


@template("total_area")
def total_area(d: Drawing, params: dict) -> Answer | None:
    if not _storey_known(d, params):
        return None
    return _sum("total_area", params, _select(d, {"room"}, params), "area_m2", "m2", AREA_READ)


@template("apartment_area")
def apartment_area(d: Drawing, params: dict) -> Answer | None:
    rooms = [r for r in _select(d, {"room"}, params) if not r.outdoor]
    return _sum("apartment_area", params, rooms, "area_m2", "m2", AREA_READ)


@template("wall_length")
def wall_length(d: Drawing, params: dict) -> Answer | None:
    if not _storey_known(d, params):
        return None
    return _sum("wall_length", params, _select(d, {"wall"}, params), "length_m", "m", {"quantity_set"})


@template("wall_side_area")
def wall_side_area(d: Drawing, params: dict) -> Answer | None:
    if not _storey_known(d, params):
        return None
    return _sum("wall_side_area", params, _select(d, {"wall"}, params), "side_area_m2", "m2", {"quantity_set"})


@template("element_volume")
def element_volume(d: Drawing, params: dict) -> Answer | None:
    if not _storey_known(d, params):
        return None
    return _sum("element_volume", params, _select(d, {params["element"]}, params), "volume_m3", "m3", {"quantity_set"})
