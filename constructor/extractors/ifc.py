"""IFC: storeys, spaces, doors, windows, walls, columns, beams, stairs, slabs and their quantities.

Quantities come from IFC quantity sets where the model has them (exact), else from the
geometry (not exact). One geometry pass also gives every element a plan footprint
(bbox, and a polygon for spaces) in metres, y up, for the plan renderer and the overlay.
"""

from __future__ import annotations

import multiprocessing
import re
from pathlib import Path

from ..schema import Drawing, Element

VERSION = "ifc-0.6"

# IFC class -> Element.type. by_type() includes subtypes (IfcWallStandardCase is an IfcWall).
TYPES = {
    "IfcSpace": "room",
    "IfcWindow": "window",
    "IfcDoor": "door",
    "IfcWall": "wall",
    "IfcColumn": "column",
    "IfcBeam": "beam",
    "IfcStair": "stair",
    "IfcSlab": "slab",
}

# Quantity names, in order of preference, per Element.quantities key.
QUANTITY_NAMES = {
    "area_m2": ["NetFloorArea", "GrossFloorArea"],
    "length_m": ["Length"],
    "side_area_m2": ["NetSideArea", "GrossSideArea"],
    "volume_m3": ["NetVolume", "GrossVolume"],
}
QUANTITY_KIND = {"area_m2": "AREAUNIT", "length_m": "LENGTHUNIT", "side_area_m2": "AREAUNIT", "volume_m3": "VOLUMEUNIT"}
QUANTITY_VALUE = {"AREAUNIT": "AreaValue", "LENGTHUNIT": "LengthValue", "VOLUMEUNIT": "VolumeValue"}


def _unit_scales(model) -> dict[str, float]:
    """SI factor for the project's length, area and volume units (mm -> 0.001, mm² -> 1e-6, ...)."""
    import ifcopenshell.util.unit as uu

    scales = {}
    for kind in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT"):
        unit = uu.get_project_unit(model, kind)
        # A model may omit a unit (no VOLUMEUNIT); IFC then means SI, which _scale returns for None.
        scales[kind] = _scale(unit, kind)
    return scales


def _scale(unit, kind: str) -> float:
    if unit is None:
        return 1.0
    if unit.is_a("IfcConversionBasedUnit"):
        factor = unit.ConversionFactor
        return float(factor.ValueComponent.wrappedValue) * _scale(factor.UnitComponent, kind)
    prefix = {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, "KILO": 1e3}.get(getattr(unit, "Prefix", None), 1.0)
    power = {"LENGTHUNIT": 1, "AREAUNIT": 2, "VOLUMEUNIT": 3}[kind]
    return prefix**power


def _quantities(element, scales: dict[str, float]) -> dict[str, float]:
    """Read quantity-set values, in SI units. Prefers BaseQuantities / Qto_* sets."""
    found: dict[str, dict[str, float]] = {}
    for rel in getattr(element, "IsDefinedBy", None) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        qset = rel.RelatingPropertyDefinition
        if not qset.is_a("IfcElementQuantity"):
            continue
        for q in qset.Quantities:
            for key, names in QUANTITY_NAMES.items():
                kind = QUANTITY_KIND[key]
                if q.Name in names and q.is_a(f"IfcQuantity{kind[:-4].capitalize()}"):
                    value = getattr(q, QUANTITY_VALUE[kind])
                    scale = _scale(q.Unit, kind) if q.Unit else scales[kind]
                    found.setdefault(key, {}).setdefault(q.Name, float(value) * scale)
    return {key: next(vals[n] for n in QUANTITY_NAMES[key] if n in vals) for key, vals in found.items()}


# Area written as a plain property by the authoring tool (Esplanades: AR_Ruum.120_Pindala = "63,8").
AREA_PROPERTY = re.compile(r"(^|_)(net)?(floor)?area$|pindala|nettoareal|^areal$|fläche|surface", re.I)


def _area_property(element) -> tuple[float, int] | None:
    """(value in m², decimals as written) of an area property, if the space has one."""
    import ifcopenshell.util.element as ue

    for props in ue.get_psets(element, psets_only=True).values():
        for name, value in props.items():
            if name == "id" or not AREA_PROPERTY.search(name):
                continue
            text = str(value).strip().replace(",", ".")
            if re.fullmatch(r"\d+(\.\d+)?", text):
                decimals = len(text.split(".")[1]) if "." in text else 0
                return float(text), decimals
    return None


def _storey(element) -> str | None:
    import ifcopenshell.util.element as ue

    node = element
    for _ in range(10):
        parent = ue.get_container(node) or ue.get_aggregate(node)
        if parent is None:
            return None
        if parent.is_a("IfcBuildingStorey"):
            return parent.Name
        node = parent
    return None


def _is_part(element) -> bool:
    """True when the element is a part of another counted element (a stair flight inside a stair)."""
    import ifcopenshell.util.element as ue

    parent = ue.get_aggregate(element)
    return parent is not None and any(parent.is_a(t) for t in TYPES)


def _footprints(model, ids: set[int]) -> dict[int, dict]:
    """Plan footprint per element id, in metres, world coordinates, y up."""
    import ifcopenshell.geom
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    out: dict[int, dict] = {}
    iterator = ifcopenshell.geom.iterator(settings, model, max(1, multiprocessing.cpu_count() - 1))
    if not iterator.initialize():
        return out
    while True:
        shape = iterator.get()
        if shape.id in ids:
            verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
            if len(verts):
                x0, y0 = verts[:, :2].min(axis=0)
                x1, y1 = verts[:, :2].max(axis=0)
                rec = {"bbox": [float(x0), float(y0), float(x1), float(y1)], "z": [float(verts[:, 2].min()), float(verts[:, 2].max())]}
                faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
                tris = [Polygon(verts[f, :2]) for f in faces]
                footprint = _footprint([t for t in tris if t.area > 1e-9])
                if footprint is None:
                    out[shape.id] = rec  # the outline could not be built; the box still places it
                    if not iterator.next():
                        break
                    continue
                if footprint.geom_type == "MultiPolygon":
                    footprint = max(footprint.geoms, key=lambda g: g.area)
                if not footprint.is_empty and footprint.geom_type == "Polygon":
                    # The space area must stay exact; other outlines are only drawn, so simplify them.
                    is_space = model.by_id(shape.id).is_a("IfcSpace")
                    outline = footprint if is_space else footprint.simplify(0.01)
                    rec["polygon"] = [[round(x, 4), round(y, 4)] for x, y in outline.exterior.coords]
                    if is_space:
                        rec["area_m2"] = footprint.area
                out[shape.id] = rec
        if not iterator.next():
            break
    return out


def _label(space) -> str | None:
    # Questions name rooms "LongName (Name)": 'TUALETTRUUM (43-3)', 'Kontor (Rum nr. 405)'.
    if space.LongName and space.Name:
        return f"{space.LongName} ({space.Name})"
    return space.LongName or space.Name


def extract(path: Path, geometry: bool = True) -> Drawing:
    import ifcopenshell

    model = ifcopenshell.open(str(path))
    scales = _unit_scales(model)
    elements: list[Element] = []

    for storey in model.by_type("IfcBuildingStorey"):
        elements.append(Element(id=len(elements) + 1, type="storey", source=storey.GlobalId, exact=True, label=storey.Name, storey=storey.Name))

    ifc_elements = [
        (e, kind)
        for ifc_class, kind in TYPES.items()
        for e in model.by_type(ifc_class)
        if not _is_part(e)
    ]
    shapes = _footprints(model, {e.id() for e, _ in ifc_elements}) if geometry else {}

    for e, kind in ifc_elements:
        quantities = _quantities(e, scales)
        source = {k: "quantity_set" for k in quantities}
        shape = shapes.get(e.id(), {})
        if kind == "room" and "area_m2" not in quantities:
            recorded = _area_property(e)
            computed = shape.get("area_m2")
            # The space's own geometry first: across the full set it matches the expected areas in every
            # model (clinic 266/266, Esplanades 568/570), while recorded area properties often differ
            # (clinic 5/266: Revit's "Area" is measured differently). The property only stands in when
            # there is no geometry.
            if computed is not None:
                quantities["area_m2"] = computed
                source["area_m2"] = "model_geometry"
            elif recorded is not None:
                quantities["area_m2"] = recorded[0]
                source["area_m2"] = "property"
            if recorded is not None:
                quantities["area_m2_recorded"] = recorded[0]
        elements.append(
            Element(
                id=len(elements) + 1,
                type=kind,
                source=e.GlobalId,
                exact=True,
                bbox=[round(v, 4) for v in shape["bbox"]] if "bbox" in shape else None,
                polygon=shape.get("polygon"),
                label=_label(e) if kind == "room" else (e.Name or None),
                number=e.Name if kind == "room" else None,
                quantities={k: round(v, 6) for k, v in quantities.items()} or None,
                quantity_source=source or None,
                storey=_storey(e),
            )
        )

    return Drawing(drawing=str(path), kind="ifc", extractor_version=VERSION, units="m", elements=elements)


def _footprint(tris):
    """Union of a shape's triangles seen from above. Some models have degenerate triangles that make
    GEOS fail; those are repaired one by one first. None if it still cannot be built."""
    from shapely.errors import GEOSException
    from shapely.ops import unary_union

    try:
        return unary_union(tris).buffer(0)
    except GEOSException:
        try:
            return unary_union([t.buffer(0) for t in tris]).buffer(0)
        except GEOSException:
            return None
