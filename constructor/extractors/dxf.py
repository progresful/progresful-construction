"""DXF: rooms, apartments, doors, windows and sanitary fixtures from the Swiss Dwellings layers.

Layers: ROOM_OUTLINE + ROOM_TEXT (name, number, printed area), UNIT_OUTLINE + "App. A" /
"Whg. A" tags, DOOR (one 5-point symbol per door; arcs are per leaf), WINDOW (one closed rectangle per
window), FIXTURE (primitives, no blocks). Fixtures are classified by shape:
- bathtub: a 69-point tub outline
- shower: a 5-point tray outline
- wc / sink: a 48-point bowl; a sink has a tap (small circle) touching it, a WC does not.
Rules were fitted on the train split only.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from ..schema import Drawing, Element

VERSION = "dxf-0.8"

# $INSUNITS -> metres per drawing unit. Anything else: no real units, no quantities.
INSUNITS = {6: 1.0, 4: 0.001, 5: 0.01, 1: 0.0254, 2: 0.3048}

AREA_TEXT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*m²\s*$")
NUMBER_TEXT = re.compile(r"^[A-Z]{0,2}\d+\.\d+$")
APARTMENT_TEXT = re.compile(r"^(?:App\.|Whg\.|Appartement|Wohnung)\s*([A-Z])$")
STOREY_TEXT = re.compile(r"^(?:Grundriss|Plan|Pianta)\s+(.+)$")

# Labels of outdoor spaces and of non-floor areas, in the dataset's languages. Matched as substrings.
OUTDOOR = ("balkon", "balcon", "balcone", "loggia", "terrasse", "terrazza", "terrazzo", "veranda", "sitzplatz")
NOT_FLOOR = ("schacht", "gaine", "cavedio", "luftraum", "vide", "vuoto")

TAP_RADIUS = 0.05  # tap circles are 0.03 m; stove rings are 0.08 m
RAILING_MAX = 0.1  # metres; walls this thin are balcony railings
RAILING_TOUCH = 0.05  # metres between a room outline and a railing
MIN_RAILING = 1.0  # metres of railing along a room that make it outdoor


def _bbox(points) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _outlines(msp, layer: str):
    """Closed outlines on a layer as (entity, polygon); degenerate ones (< 3 points) are skipped."""
    from shapely.geometry import Polygon

    for e in msp.query(f"LWPOLYLINE[layer=='{layer}']"):
        pts = list(e.get_points("xy"))
        if len(pts) >= 3:
            yield e, Polygon(pts).buffer(0)


def _hatch_polygons(msp, layer: str):
    """Boundary polygons of the hatches on a layer (Swiss walls are mostly hatches)."""
    from ezdxf import path as dxfpath
    from shapely.geometry import Polygon

    for h in msp.query(f"HATCH[layer=='{layer}']"):
        for p in dxfpath.from_hatch(h):
            pts = [(v.x, v.y) for v in p.flattening(0.01)]
            if len(pts) >= 3:
                poly = Polygon(pts).buffer(0)
                if not poly.is_empty:
                    yield poly


def _wall_polygons(msp):
    """Wall outlines; Swiss walls come as hatches, sometimes duplicated as closed polylines."""
    seen = []
    for poly in [p for _, p in _outlines(msp, "WALL")] + list(_hatch_polygons(msp, "WALL")):
        if not any(poly.equals_exact(q, 1e-6) for q in seen):
            seen.append(poly)
    return seen


def _thickness(poly) -> float:
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = [((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2) ** 0.5 for i in range(2)]
    return min(sides)


def _text(e) -> str:
    return (e.dxf.text if e.dxftype() == "TEXT" else e.plain_text()).strip()


def extract(path: Path) -> Drawing:
    import ezdxf
    from shapely.geometry import Point, Polygon, box
    from shapely.ops import unary_union

    from .raster_geometry import window_facing

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    scale = INSUNITS.get(doc.header.get("$INSUNITS", 0))
    elements: list[Element] = []

    def add(**kw) -> Element:
        el = Element(id=len(elements) + 1, **kw)
        elements.append(el)
        return el

    storey = next(
        (m.group(1) for e in msp.query("TEXT MTEXT[layer=='ANNOTATION']") if (m := STOREY_TEXT.match(_text(e)))),
        None,
    )

    # Apartments: outlines, named by the tag text inside them.
    units = list(_outlines(msp, "UNIT_OUTLINE"))
    tags = [(m.group(1), Point(e.dxf.insert.x, e.dxf.insert.y)) for e in msp.query("TEXT MTEXT[layer=='ROOM_TEXT']") if (m := APARTMENT_TEXT.match(_text(e)))]
    unit_names: list[str | None] = []
    for e, poly in units:
        name = next((n for n, pt in tags if poly.buffer(0.05).contains(pt)), None)
        unit_names.append(name)
        # Untagged units (shops, offices, common areas) are not apartments.
        add(type="apartment" if name else "unit", source=e.dxf.handle, exact=True, label=name, apartment=name,
            polygon=[list(p) for p in poly.exterior.coords] if poly.geom_type == "Polygon" else None,
            bbox=list(poly.bounds), storey=storey)

    # Rooms: outlines, with the room-text stack that falls inside each.
    texts = [(_text(e), Point(e.dxf.insert.x, e.dxf.insert.y)) for e in msp.query("TEXT MTEXT[layer=='ROOM_TEXT']")]
    texts = [(t, pt) for t, pt in texts if not APARTMENT_TEXT.match(t)]
    rooms = list(_outlines(msp, "ROOM_OUTLINE"))
    owner: dict[int, list[str]] = {i: [] for i in range(len(rooms))}
    for t, pt in texts:
        inside = [i for i, (_, poly) in enumerate(rooms) if poly.contains(pt)]
        # Smallest containing outline; texts of tiny rooms may sit just outside, so fall back to nearest.
        i = min(inside, key=lambda i: rooms[i][1].area) if inside else min(range(len(rooms)), key=lambda i: rooms[i][1].distance(pt), default=None)
        if i is not None:
            owner[i].append(t)

    # Balconies and loggias are bounded by railings: walls no thicker than RAILING_MAX.
    # A room with enough railing along its outline is outdoor, even when only its number is printed.
    railings = unary_union([w for w in _wall_polygons(msp) if _thickness(w) <= RAILING_MAX])

    for i, (e, poly) in enumerate(rooms):
        if not owner[i]:
            continue  # slivers between walls carry no text and are not rooms
        label = number = None
        printed = None
        for t in owner[i]:
            if m := AREA_TEXT.match(t):
                printed = float(m.group(1).replace(",", "."))
            elif NUMBER_TEXT.match(t):
                number = number or t
            else:
                label = label or t
        quantities, source = {}, {}
        if printed is not None:
            quantities["area_m2"], source["area_m2"] = printed, "label"
        elif scale is not None:
            quantities["area_m2"], source["area_m2"] = poly.area * scale * scale, "geometry"
        lower = (label or "").casefold()
        apartment = next(
            (unit_names[j] for j, (_, upoly) in enumerate(units) if upoly.buffer(0.05).contains(poly.representative_point())),
            None,
        )
        add(type="room", source=e.dxf.handle, exact=True, label=label, number=number, apartment=apartment,
            # A printed name decides; the railing test is only for rooms with just a number.
            outdoor=any(w in lower for w in OUTDOOR) or any(w in lower for w in NOT_FLOOR)
            or (label is None and poly.exterior.intersection(railings.buffer(RAILING_TOUCH)).length >= MIN_RAILING),
            polygon=[list(p) for p in poly.exterior.coords] if poly.geom_type == "Polygon" else None,
            bbox=list(poly.bounds), quantities=quantities or None, quantity_source=source or None, storey=storey)

    # Doors: one 5-point door symbol per door (the leaf, drawn open). Swing arcs are per leaf, so a
    # double door has two; each is centred on its hinge and runs from the open leaf to the shut one.
    arcs = list(msp.query("ARC[layer=='DOOR']"))
    rooms = [(el.id, el.polygon) for el in elements if el.type == "room" and el.polygon]
    for e in msp.query("LWPOLYLINE[layer=='DOOR']"):
        pts = list(e.get_points("xy"))
        if len(pts) == 5:
            door = add(type="door", source=e.dxf.handle, exact=True, bbox=_bbox(pts), storey=storey)
            door.swing = _swing(door.bbox, arcs, rooms)

    # Windows: one closed outline each; open lines are glazing.
    footprint = unary_union([Polygon(poly) for _, poly in rooms]).convex_hull if rooms else None
    hull = [list(c) for c in footprint.exterior.coords] if footprint is not None and footprint.geom_type == "Polygon" else None
    for e in msp.query("LWPOLYLINE[layer=='WINDOW']"):
        if e.closed:
            win = add(type="window", source=e.dxf.handle, exact=True, bbox=_bbox(list(e.get_points("xy"))), storey=storey)
            facing = window_facing(win.bbox, rooms, hull, y_up=True)
            if facing:
                facing["compass"] = None  # the Swiss files give no north
                win.facing = facing

    # Fixtures by shape.
    taps = [box(c.x - r, c.y - r, c.x + r, c.y + r) for c, r in
            ((e.dxf.center, e.dxf.radius) for e in msp.query("CIRCLE[layer=='FIXTURE']")) if r <= TAP_RADIUS]
    for e in msp.query("LWPOLYLINE[layer=='FIXTURE']"):
        pts = list(e.get_points("xy"))
        kind = {69: "bathtub", 5: "shower"}.get(len(pts))
        if len(pts) == 48:
            outline = box(*_bbox(pts)).buffer(0.05)
            kind = "sink" if any(outline.intersects(t) for t in taps) else "wc"
        if kind:
            add(type=kind, source=e.dxf.handle, exact=True, bbox=_bbox(pts), storey=storey)

    return Drawing(drawing=str(path), kind="dxf", extractor_version=VERSION,
                   units="m" if scale == 1.0 else ("unknown" if scale is None else f"{scale} m"), elements=elements)


def _swing(bbox: list[float], arcs, rooms) -> dict | None:
    """The door's swing from its arc: hinge at the arc centre, which must touch the leaf; the arc end
    on the leaf is the open position, the other end the shut one."""
    from shapely.geometry import Point, box

    from .raster_geometry import point_in

    x0, y0, x1, y1 = bbox
    leaf = box(x0, y0, x1, y1)
    for a in arcs:
        c = a.dxf.center
        if leaf.buffer(0.05).contains(Point(c.x, c.y)):
            ends = []
            for ang in (a.dxf.start_angle, a.dxf.end_angle):
                rad = math.radians(ang)
                ends.append((c.x + a.dxf.radius * math.cos(rad), c.y + a.dxf.radius * math.sin(rad)))
            far = (leaf.centroid.x, leaf.centroid.y)
            ends.sort(key=lambda p: math.dist(p, far))  # the open end lies on the leaf
            (ox, oy), (sx, sy) = ends
            qx, qy = c.x + 0.45 * (ox - c.x + sx - c.x), c.y + 0.45 * (oy - c.y + sy - c.y)
            into = next((rid for rid, poly in rooms if point_in(poly, qx, qy)), None)
            r = lambda v: round(v, 3)  # noqa: E731
            return {"hinge": [r(c.x), r(c.y)], "open": [r(ox), r(oy)], "closed": [r(sx), r(sy)], "into": into, "exact": True}
    return None
