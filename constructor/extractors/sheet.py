"""Large technical sheets (structural, architectural, piping): read in high-resolution tiles.

A 10,000-pixel sheet shrunk to one model image loses its dimension strings and tags, so the sheet is
cut into overlapping tiles and Gemini lists what is printed on each (dimensions, notes, tags, slab
callouts) and the symbols it sees (doors, windows, valves, pumps, ...), each with a box. Duplicates
from the overlaps are merged. A reduced view of the whole sheet gives the title block: sheet id,
title, discipline, printed scale and units.

Questions are then answered from this list: counts from the symbol marks, and anything else by the
analyst, which can also calculate from printed numbers (the app does the arithmetic and boxes the
numbers it used).
"""

from __future__ import annotations

from pathlib import Path

from ..schema import Drawing, Element

VERSION = "sheet-0.5"
PAID = True

TEXT_TILE = 1800  # pixels per tile side for reading text (before overlap)
SYMBOL_TILE = 1300  # smaller for symbols: a valve is a few dozen pixels on a 10,000-pixel sheet
OVERLAP = 0.15  # share of a tile repeated on each side
OVERVIEW_SIDE = 3072
PLANS_DIR = Path("cache/plans")

SYMBOLS = ["door", "window", "valve", "pump", "tank", "equipment", "stair", "column", "fitting", "drain", "instrument", "fixture"]

# What to look for, per discipline: (element type, kind as asked, what it looks like). Subtypes are kept
# in the element's label, so "valve" counts every valve and the breakdown is by kind.
VOCAB = {
    "piping": [
        ("pump", "pump", "a pump: circle or casing with suction and discharge, often tagged P-, FP-, JP-"),
        ("valve", "check valve", "check valve, often a large circle on the line or a valve with an arrow, tagged CV-"),
        ("valve", "control valve", "control valve with an actuator on top, tagged FCV-, FSCV-, PCV-, BPCV-"),
        ("valve", "gate valve", "gate valve: two triangles point to point (bow tie) across the line"),
        ("valve", "ball valve", "ball valve: bow tie with a filled circle in the middle"),
        ("valve", "butterfly valve", "butterfly valve: bow tie with a line or disc through the middle"),
        ("valve", "relief valve", "relief or pressure valve, often at a right angle to the line"),
        ("valve", "other valve", "any other valve symbol on a pipe, including air vents (MAV) and drain valves"),
        ("fitting", "strainer", "strainer or basket strainer on the line"),
        ("equipment", "filter separator", "filter separator or filter vessel, often a large tank-like body tagged FS-, FSI-"),
        ("instrument", "gauge", "pressure or temperature gauge, a small circle tagged PG, TG, PI"),
        ("instrument", "switch or transmitter", "pressure switch, transmitter or sensor, small circle tagged PS, PT, FS, DPT"),
        ("instrument", "flow meter", "flow meter or venturi"),
        ("fitting", "reducer", "reducer or increaser (cone between two pipe sizes)"),
        ("fitting", "blind flange", "blind flange or cap at a pipe end"),
        ("tank", "tank", "storage tank or vessel"),
    ],
    "architectural": [
        ("door", "door", "a door leaf with a swing arc, or a sliding door"),
        ("window", "window", "a window: opening in an exterior wall drawn with glazing lines"),
        ("stair", "stair", "a stair (treads)"),
        ("fixture", "toilet", "toilet / WC"),
        ("fixture", "sink", "sink or wash basin"),
        ("fixture", "shower or bath", "shower or bathtub"),
        ("column", "column", "a structural column"),
    ],
    "structural": [
        ("column", "column", "a column or pier"),
        ("equipment", "footing or pad", "a footing, pad or equipment base"),
        ("stair", "stair", "a stair"),
        ("fitting", "trench or pit", "a trench, pit or sump"),
    ],
}
VOCAB["mechanical"] = VOCAB["piping"]

TEXT_PROMPT = (
    "This is one tile of a large construction drawing sheet. List every piece of printed text on it: dimension "
    "strings (e.g. 3900, 12'-6\"), room and area labels, notes, tags and marks (e.g. PS-1, CV-2, D13 @ 300), callouts, "
    "slab and section notes, legend and table entries. Copy the text exactly; one item per separate label or table "
    "row. Return a JSON list of objects: \"text\" and \"box_2d\" [ymin, xmin, ymax, xmax] normalised to 0-1000 "
    "within this tile. Skip text cut off at the tile edge."
)
TEXT_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"text": {"type": "string"}, "box_2d": {"type": "array", "items": {"type": "number"}}},
              "required": ["text", "box_2d"]},
}

SYMBOL_PROMPT = (
    "This is one tile of a {discipline} drawing. Find every symbol of these kinds:\n{kinds}\n"
    "List every instance separately, including identical repeated ones (five identical pump legs are five of each "
    "symbol). Small symbols matter. If a tag is printed next to a symbol (e.g. CV-1, FP-3), give it. Do not list "
    "text, dimension lines or symbols cut off at the tile edge. Return a JSON list of objects: \"kind\" (one of the "
    "kinds above, exactly), \"tag\" (or \"\"), \"box_2d\" [ymin, xmin, ymax, xmax] normalised to 0-1000 within "
    "this tile."
)
SYMBOL_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"kind": {"type": "string"}, "tag": {"type": "string"},
                                               "box_2d": {"type": "array", "items": {"type": "number"}}},
              "required": ["kind", "box_2d"]},
}

SHEET_PROMPT = (
    "This is a whole construction drawing sheet. From its title block and drawing titles, give: sheet_id (e.g. "
    "S-100F), title, discipline (architectural, structural, mechanical, piping, electrical or other), "
    "scale (as printed, e.g. \"1:50\" or \"1\\\" = 40'-0\\\"\"), units of its dimensions (mm, m or ft-in), and a "
    "one-sentence summary of what the sheet shows."
)
SHEET_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ("sheet_id", "title", "discipline", "scale", "units", "summary")},
    "required": ["title", "discipline", "units", "summary"],
}


def _tiles(w: int, h: int, size: int) -> list[tuple[int, int, int, int]]:
    cols, rows = max(1, round(w / size)), max(1, round(h / size))
    tw, th = w / cols, h / rows
    ox, oy = int(tw * OVERLAP), int(th * OVERLAP)
    out = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0, int(c * tw) - ox), max(0, int(r * th) - oy)
            x1, y1 = min(w, int((c + 1) * tw) + ox), min(h, int((r + 1) * th) + oy)
            out.append((x0, y0, x1, y1))
    return out


def _centre_in(a: list[float], b: list[float]) -> bool:
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def _merge(items: list[dict]) -> list[dict]:
    """Drop the copies that tile overlaps produce: same text (or symbol kind) at the same place."""
    out: list[dict] = []
    for it in items:
        key = it.get("text", "").strip().lower() if it["kind"] == "text" else it["sub"]
        dup = next((o for o in out if o["kind"] == it["kind"]
                    and (o.get("text", "").strip().lower() if o["kind"] == "text" else o["sub"]) == key
                    and (_centre_in(it["bbox"], o["bbox"]) or _centre_in(o["bbox"], it["bbox"]))), None)
        if dup is None:
            out.append(it)
        elif it.get("tag") and not dup.get("tag"):
            dup["tag"] = it["tag"]
    return out


def _read_tiles(image, path: Path, size: int, prompt: str, schema: dict, max_tokens: int):
    """Each tile's reply items, with boxes in sheet pixels. Tiles are read in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    import cv2

    from .. import gemini

    h, w = image.shape[:2]
    tiles = _tiles(w, h, size)

    def read(i_tile):
        i, (x0, y0, x1, y1) = i_tile
        tile = PLANS_DIR / f"{path.stem}-{size}-tile{i}.png"
        cv2.imwrite(str(tile), image[y0:y1, x0:x1])
        try:
            reply = gemini.generate([gemini.image(tile), prompt], schema=schema, max_tokens=max_tokens)
            found = reply.json()
            cost = reply.cost_usd
        except Exception as e:  # one unreadable tile should not lose the sheet
            print(f"sheet tile {i} ({size}px) of {path.name} failed: {type(e).__name__}: {e}")
            found, cost = [], 0.0
        finally:
            tile.unlink(missing_ok=True)
        out = []
        tw, th = x1 - x0, y1 - y0
        for it in found if isinstance(found, list) else []:
            b = it.get("box_2d") if isinstance(it, dict) else None
            if isinstance(b, list) and len(b) == 4:
                by0, bx0, by1, bx1 = (float(v) for v in b)
                out.append({**it, "bbox": [x0 + bx0 / 1000 * tw, y0 + by0 / 1000 * th, x0 + bx1 / 1000 * tw, y0 + by1 / 1000 * th]})
        return out, cost

    items, cost = [], 0.0
    with ThreadPoolExecutor(8) as pool:
        for found, c in pool.map(read, enumerate(tiles)):
            items += found
            cost += c
    return items, cost, len(tiles)


FOOT = 0.3048


def scale_from_bar(elements: list[Element], units: str | None) -> dict | None:
    """Metres per pixel from the printed scale bar: a row of numbers on one line ("0' 20' 40' 80'" or
    "0 500 1000 2000") whose positions grow in proportion to their values. Dimension rows do not fit
    a straight line through their values, so they are ignored."""
    import re

    import numpy as np

    marks = []
    for e in elements:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*('|ft|m|mm)?\s*", e.label or "") if e.type == "text" and e.bbox else None
        if m:
            x = (e.bbox[0] + e.bbox[2]) / 2
            y = (e.bbox[1] + e.bbox[3]) / 2
            marks.append((float(m.group(1)), x, y, m.group(2) or ""))
    best = None
    for value, x, y, unit in marks:
        row = sorted({(v, xx, u) for v, xx, yy, u in marks if abs(yy - y) < 25}, key=lambda r: r[1])
        if len(row) < 3 or len({v for v, _, _ in row}) < len(row):
            continue
        vals, xs = np.array([r[0] for r in row]), np.array([r[1] for r in row])
        if not (np.all(np.diff(vals) > 0) and np.all(np.diff(xs) > 0)):
            continue
        if np.all(np.diff(vals) == 1) and vals.max() <= 30:
            continue  # the sheet border's grid labels (1 2 3 ...), not a scale bar
        marked = any(u for _, _, u in row)
        if (units or "").startswith("ft") and not marked:
            continue  # a feet drawing's scale bar carries foot marks (20' 40' 80')
        slope, intercept = np.polyfit(vals, xs, 1)
        resid = np.abs(xs - (slope * vals + intercept)).max() / (xs[-1] - xs[0])
        if resid < 0.02 and (best is None or len(row) > best[0]):
            feet = any(u == "'" or u == "ft" for _, _, u in row) or (units or "").startswith("ft")
            per_unit = FOOT if feet else 0.001 if (units or "mm") == "mm" else 1.0
            best = (len(row), per_unit / slope, resid, "ft" if feet else units)
    if best is None:
        return None
    return {"m_per_px": round(best[1], 6), "source": f"scale bar ({best[3]})", "n": best[0], "rel_err": round(max(0.03, best[2] * 2), 3)}


def find_rooms(image, elements: list[Element], scale: dict, next_id: int) -> list[Element]:
    """Rooms without labels: enclosed areas of free floor, with the detected doors and windows shut,
    that touch a door (which rules out table cells, the title block and legends). Areas from the
    sheet's scale bar."""
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    s = min(1.0, 3500 / max(w, h))
    sw, sh = int(w * s), int(h * s)
    ink = (image.min(axis=2) < 140).astype(np.uint8)
    ink = cv2.dilate(ink, np.ones((3, 3), np.uint8))
    walls = (cv2.resize(ink.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA) > 0.15).astype(np.uint8)
    door_mask = np.zeros_like(walls)
    for e in elements:
        if not e.bbox:
            continue
        x0, y0, x1, y1 = (int(v * s) for v in e.bbox)
        if e.type == "door":
            cv2.rectangle(walls, (x0, y0), (x1, y1), 1, 1)  # shut: the swing's box closes the opening
            cv2.rectangle(door_mask, (x0, y0), (x1, y1), 1, -1)
        elif e.type == "window":
            cv2.rectangle(walls, (x0, y0), (x1, y1), 1, -1)
    walls = cv2.morphologyEx(walls, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    free = (1 - walls).astype(np.uint8)
    n, comp, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    m2_per_work_px = (scale["m_per_px"] / s) ** 2
    door_near = cv2.dilate(door_mask, np.ones((5, 5), np.uint8))
    texts = [e for e in elements if e.type == "text" and e.bbox]
    # Furniture lines split a room into pieces: each piece's convex outline, then pieces whose outlines
    # overlap are one room. Pieces that touch no door (table cells, legends, shafts) are dropped first.
    from shapely.geometry import Polygon as P
    from shapely.ops import unary_union

    pieces = []
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if x == 0 or y == 0 or x + cw >= sw or y + ch >= sh:
            continue  # the outside
        if area * m2_per_work_px < 0.3 or area * m2_per_work_px > 400:
            continue
        mask = (comp[y : y + ch, x : x + cw] == i).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(c).reshape(-1, 2) + [x, y]
        real = cv2.approxPolyDP(c, 0.002 * (sw + sh), True).reshape(-1, 2) + [x, y]
        if len(hull) >= 3:
            pieces.append((P(hull).buffer(0), bool((cv2.dilate(mask, np.ones((5, 5), np.uint8)) & door_near[y : y + ch, x : x + cw]).any()),
                           P(real).buffer(0) if len(real) >= 3 else None))
    # Union-find: two pieces are one room when their outlines overlap by a third of the smaller one
    # (furniture inside a room); walls only make outlines touch, which does not merge them.
    parent = list(range(len(pieces)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            a, b = pieces[i][0], pieces[j][0]
            if a.intersects(b) and a.intersection(b).area > 0.33 * min(a.area, b.area):
                parent[root(i)] = root(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(pieces)):
        groups.setdefault(root(i), []).append(i)
    rooms = []
    for members in groups.values():
        has_door = any(pieces[i][1] for i in members)
        g = unary_union([pieces[i][0] for i in members]).convex_hull
        reals = [pieces[i][2] for i in members if pieces[i][2] is not None]
        real = unary_union(reals).buffer(2).buffer(-2) if reals else None
        if real is not None and real.geom_type == "MultiPolygon":
            real = max(real.geoms, key=lambda r: r.area)
        # A large L- or T-shaped space (corridor, common area) is not convex: keep its real outline.
        if real is not None and real.geom_type == "Polygon" and real.area < 0.75 * g.area and g.area * m2_per_work_px > 40:
            g = real.simplify(0.002 * (sw + sh))
        m2 = g.area * m2_per_work_px
        if not has_door or not (1.5 <= m2 <= 1500):
            continue
        poly = np.array(g.exterior.coords)[:-1]
        poly_full = [[round(px / s, 1), round(py / s, 1)] for px, py in poly]
        xs, ys = [q[0] for q in poly_full], [q[1] for q in poly_full]
        inside = [t.label for t in texts if g.contains(P([(t.bbox[0] * s, t.bbox[1] * s), (t.bbox[2] * s, t.bbox[1] * s), (t.bbox[2] * s, t.bbox[3] * s)]).centroid)]
        rooms.append(Element(id=next_id + len(rooms), type="room", source="sheet geometry", exact=False, conf=0.8,
                             bbox=[min(xs), min(ys), max(xs), max(ys)], polygon=poly_full,
                             label=" / ".join(inside[:2]) or None,
                             quantities={"area_m2": round(float(m2), 2), "area_m2_err": round(float(m2) * scale["rel_err"] + 0.3, 2),
                                         "perimeter_m": round(float(g.length) * scale["m_per_px"] / s, 2)},
                             quantity_source={"area_m2": "scale"}))
    return rooms


def extract(path: Path) -> Drawing:
    import cv2

    from .. import gemini

    if not gemini.available():
        raise RuntimeError("Reading technical sheets needs GEMINI_API_KEY")
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Cannot read image {path}")
    h, w = image.shape[:2]
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    cost = 0.0

    # The whole sheet, reduced: title block and what the sheet is.
    s = min(1.0, OVERVIEW_SIDE / max(w, h))
    overview = PLANS_DIR / f"{path.stem}-overview.jpg"
    cv2.imwrite(str(overview), cv2.resize(image, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 90])
    reply = gemini.generate([gemini.image(overview), SHEET_PROMPT], schema=SHEET_SCHEMA, max_tokens=600)
    cost += reply.cost_usd
    try:
        info = reply.json()
    except ValueError:
        info = {}

    # Text, in tiles at full resolution.
    found, c, n_text = _read_tiles(image, path, TEXT_TILE, TEXT_PROMPT, TEXT_SCHEMA, 16000)
    cost += c
    items: list[dict] = [{"kind": "text", "text": it["text"].strip(), "bbox": it["bbox"]}
                         for it in found if (it.get("text") or "").strip()]

    # Symbols, in smaller tiles, with the vocabulary of the sheet's discipline.
    discipline = (info.get("discipline") or "").lower()
    vocab = VOCAB.get(discipline) or VOCAB["architectural"] + VOCAB["structural"][1:]
    kinds = {k: t for t, k, _ in vocab}
    prompt = SYMBOL_PROMPT.format(discipline=discipline or "construction",
                                  kinds="\n".join(f"- {k}: {hint}" for _, k, hint in vocab))
    found, c, n_sym = _read_tiles(image, path, SYMBOL_TILE, prompt, SYMBOL_SCHEMA, 8000)
    cost += c
    for it in found:
        sub = str(it.get("kind") or "").strip().lower()
        if sub in kinds:
            items.append({"kind": "symbol", "type": kinds[sub], "sub": sub, "tag": (it.get("tag") or "").strip(), "bbox": it["bbox"]})

    elements: list[Element] = []
    for it in _merge(items):
        bbox = [round(v, 1) for v in it["bbox"]]
        if it["kind"] == "text":
            elements.append(Element(id=len(elements) + 1, type="text", source="gemini tile", exact=False, conf=0.9,
                                    bbox=bbox, label=it["text"]))
        else:
            # The kind ("check valve") is the label, the printed tag ("CV-1") the number.
            elements.append(Element(id=len(elements) + 1, type=it["type"], source="gemini tile", exact=False,
                                    conf=0.85, bbox=bbox, label=it["sub"], number=it.get("tag") or None))
    elements.append(Element(id=len(elements) + 1, type="sheet", source="gemini overview", exact=False, conf=0.9,
                            label=info.get("title"), number=info.get("sheet_id")))
    # Plans with doors: find the rooms even where none is labelled, measured with the scale bar.
    bar = scale_from_bar(elements, info.get("units"))
    if bar and any(e.type == "door" for e in elements):
        rooms = find_rooms(image, elements, bar, len(elements) + 1)
        elements += rooms
        print(f"{path.name}: scale {bar}, {len(rooms)} rooms")
    found_types = sorted({e.type for e in elements if e.type in SYMBOLS} | ({"room"} if any(e.type == "room" for e in elements) else set()))
    print(f"{path.name}: {n_text} text tiles, {n_sym} symbol tiles, {len(elements)} elements")
    return Drawing(drawing=str(path), kind="sheet", extractor_version=VERSION, units="px", elements=elements,
                   covers=found_types or [], extraction_cost_usd=cost,
                   scale={**(bar or {}), "printed": info.get("scale"), "units": info.get("units"), "discipline": info.get("discipline"),
                          "summary": info.get("summary"), "sheet_id": info.get("sheet_id"), "title": info.get("title")})
