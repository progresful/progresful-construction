"""Raster plans (CubiCasa): marks on the plan for rooms, windows and doors, plus whole-image counts.

Per image, three model calls and some free geometry:
1. Room labels with positions (one call; Gemini, or Nemotron without a Gemini key). Each label maps to a room type through the Finnish
   abbreviation dictionary; its room is marked by flood-filling the free space around the label
   (`raster_geometry`), or by a box around the label when the fill leaks.
2. Windows, doors and fixtures as boxes from Gemini (one call), when GEMINI_API_KEY is set.
3. Whole-image counts (one call, the step 6 baseline), for every type marks do not yet beat.
`covers` lists the types answered from marks; it is set from train-split results only.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from ..schema import Drawing, Element
from . import raster_geometry as geo

VERSION = "raster-0.30"
PAID = True

# Types answered from marks, because marks beat the whole-image count on train (scripts/raster_marks_eval.py).
# Types counted from marks, because marks beat the whole-image count on all 201 train images
# (scripts/raster_marks_eval.py, scripts/gemini_detect_eval.py):
# - rooms (Gemini labels + areas): WC rooms 89.2% vs 57.0%, balconies 85.5% vs 80.0%, bedrooms
#   77.3% vs 74.2%. Kitchens, bathrooms and saunas lose; their areas are shown as evidence only.
# - elements (Gemini boxes): windows 30.3% vs 14.9%, doors 41.9% vs 16.2%, WC seats 80.5% vs
#   57.5%, sinks 62.8% vs 50.3%. Showers and bathtubs lose (27.0% vs 70.9%); evidence only.
ROOM_MARKED_TYPES = ["wc_room", "balcony", "bedroom"]
ELEMENT_MARKED_TYPES = ["window", "door", "wc", "sink"]

# Whole-image count prompt. Keys match templates.COUNT_KEYS; wording follows the dataset's definitions.
COUNT_FIELDS = {
    "windows": "windows shown on the plan",
    "doors": "doorways fitted with a door (door leaf drawn); open doorways without a door leaf do not count",
    "wc_seats": "toilet bowls (WC seats) drawn",
    "sinks": "sinks and wash basins, kitchen and bathroom combined; a double-bowl sink counts as one",
    "showers_and_bathtubs": "showers and bathtubs drawn, in total",
    "storeys": "floors (storeys) the image shows; separate floor plans of different floors count separately",
    "saunas": "saunas (labelled S or SAUNA)",
    "kitchens": "kitchens, including kitchenettes (KK, KT), open kitchens and utility kitchens (K, TK, AVOK)",
    "bedrooms": "bedrooms (makuuhuone, usually labelled MH)",
    "bathrooms": "bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH), not counting separate WC rooms",
    "wc_rooms": "separate WC rooms (toilet rooms labelled WC)",
    "balconies": "balconies (parveke, including glazed balconies)",
}
COUNT_PROMPT = (
    "This is a Finnish real-estate floor plan. Count the following and answer as JSON with one "
    "integer per key. Count only what is drawn or printed on the plan; ignore handwritten notes.\n"
    + "\n".join(f"- {k}: {v}" for k, v in COUNT_FIELDS.items())
)
COUNT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "integer", "minimum": 0} for k in COUNT_FIELDS},
    "required": list(COUNT_FIELDS),
}

# Plan label -> room type. Finnish real-estate abbreviations; longer words match by prefix.
ROOM_LABELS: dict[str, str] = {
    "MH": "bedroom", "KH": "bathroom", "KPH": "bathroom", "PH": "bathroom", "PESUH": "bathroom", "SH": "bathroom",
    "WC": "wc_room", "S": "sauna", "LS": "sauna",
    "K": "kitchen", "KK": "kitchen", "KT": "kitchen", "AVOK": "kitchen",
    "PARV": "balcony", "OH": "living_room", "ET": "hall", "VH": "closet", "VAR": "storage",
}
ROOM_PREFIXES: list[tuple[str, str]] = [
    ("MAKUU", "bedroom"), ("KYLPY", "bathroom"), ("PESUH", "bathroom"), ("SAUNA", "sauna"),
    ("KEITTO", "kitchen"), ("KEITTI", "kitchen"), ("TUPAK", "kitchen"), ("AVOKEIT", "kitchen"),
    ("PARVEKE", "balcony"), ("LASITETTU PARV", "balcony"), ("OLOH", "living_room"), ("ETEI", "hall"),
    # Swedish-language plans
    ("SOVRUM", "bedroom"), ("SÖVRUM", "bedroom"), ("BADRUM", "bathroom"), ("DUSCH", "bathroom"),
    ("TVÄTT", "bathroom"), ("KÖK", "kitchen"), ("KOK", "kitchen"), ("BASTU", "sauna"),
    ("BALKONG", "balcony"), ("VARDAGSRUM", "living_room"), ("HALL", "hall"),
]

# No example labels in the prompt: with them the model lists the examples whether printed or not.
LABEL_PROMPT = (
    "Read the room names and room abbreviations printed inside the rooms of this floor plan. "
    "Copy each one exactly as printed, once per room where it appears. Do not list text that is not "
    "printed on the plan. Skip handwriting, dimensions, areas and notes outside the plan. Output one "
    "line per label: text,x,y where x,y is the centre of the label on a 0-1000 grid over this image "
    "(0,0 top-left). No other text."
)
LABEL_LINE = re.compile(r"^\s*([^,\n]+?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*$", re.M)
MAX_LABELS = 60  # more is a generation loop
MAX_REPEATS = 6  # a label text seen more often than this is a loop (six bedrooms is already rare)


# Element detection with Gemini: boxes on a 0-1000 grid, [ymin, xmin, ymax, xmax].
DETECT_TYPES = {"window": "window", "door": "door", "toilet": "wc", "sink": "sink", "shower": "shower", "bathtub": "bathtub"}
DETECT_PROMPT = (
    "Detect every window, door, toilet, sink, shower and bathtub drawn on this floor plan.\n"
    "- window: an opening in a wall drawn with thin glazing lines.\n"
    "- door: a door leaf, usually with a swing arc. An open doorway without a leaf is not a door.\n"
    "- toilet: a WC bowl. sink: a wash basin or kitchen sink; a double-bowl sink is one sink.\n"
    "- shower: a shower tray or cubicle. bathtub: a bath.\n"
    "Do not include stairs, counters, decking, furniture, text or handwriting. Return a JSON list of "
    "objects with \"label\" (one of window, door, toilet, sink, shower, bathtub) and \"box_2d\" "
    "[ymin, xmin, ymax, xmax] normalised to 0-1000."
)


def detect_elements(path: Path, model: str | None = None):
    """[(element type, [x0, y0, x1, y1] pixels)], reply. One Gemini call."""
    import cv2

    from .. import gemini

    h, w = cv2.imread(str(path)).shape[:2]
    reply = gemini.generate([gemini.image(path), DETECT_PROMPT], max_tokens=8000, **({"model": model} if model else {}))
    try:
        items = reply.json()
    except ValueError:
        return [], reply
    boxes = []
    for it in items if isinstance(items, list) else []:
        kind = DETECT_TYPES.get(str(it.get("label", "")).lower())
        box = it.get("box_2d")
        if kind and isinstance(box, list) and len(box) == 4:
            y0, x0, y1, x1 = (float(v) for v in box)
            boxes.append((kind, [x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h]))
    return boxes, reply


SECOND_LOOK_PROMPT = (
    "This floor plan has red boxes around the doors and blue boxes around the windows found so far. "
    "Look for doors and windows that are NOT inside any box and were missed: for example double doors, "
    "sliding or folding doors, doors drawn with thick leaves, balcony doors, narrow windows and windows in "
    "corners. Do not repeat anything already boxed; do not include doorways without a leaf, stairs, "
    "cupboards or furniture. Return a JSON list of objects with \"label\" (door or window) and \"box_2d\" "
    "[ymin, xmin, ymax, xmax] normalised to 0-1000; return [] if nothing was missed."
)


# Ask for every room's extent during extraction (one more call per plan) and keep each fill inside
# it: stops fills running through missed doors (11397's bathroom took the stair hall and a kitchen
# corner) and splits open-plan spaces straight instead of on a diagonal.
ROOM_BOXES = True

SECOND_LOOK_CONF = 0.75  # second-look finds are uncertain marks: shown dashed, counted by confidence


def _inside(box, other) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return other[0] <= cx <= other[2] and other[1] <= cy <= other[3]


def second_look(path: Path, boxes: list, model: str | None = None):
    """Doors and windows the first detection missed: the plan is shown again with what was found
    boxed, and only unboxed ones are asked for. Returns ([(type, box)], reply)."""
    import cv2

    from .. import gemini

    image = cv2.imread(str(path))
    h, w = image.shape[:2]
    t = max(2, round(max(h, w) / 500))
    for kind, (x0, y0, x1, y1) in boxes:
        if kind in ("door", "window"):
            colour = (0, 0, 255) if kind == "door" else (255, 0, 0)
            cv2.rectangle(image, (int(x0), int(y0)), (int(x1), int(y1)), colour, t)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    probe = PLANS_DIR / f"look-{path.name}"
    cv2.imwrite(str(probe), image)
    try:
        reply = gemini.generate([gemini.image(probe), SECOND_LOOK_PROMPT], max_tokens=3000, **({"model": model} if model else {}))
    finally:
        probe.unlink(missing_ok=True)
    try:
        items = reply.json()
    except ValueError:
        return [], reply
    found = []
    for it in items if isinstance(items, list) else []:
        kind = {"door": "door", "window": "window"}.get(str(it.get("label", "")).lower())
        box = it.get("box_2d")
        if not kind or not isinstance(box, list) or len(box) != 4:
            continue
        y0, x0, y1, x1 = (float(v) for v in box)
        px = [x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h]
        # Already found after all: its centre falls in an existing box of the same kind.
        if any(k == kind and (_inside(px, b) or _inside(b, px)) for k, b in boxes + found):
            continue
        found.append((kind, px))
    return found, reply


NORTH_PROMPT = (
    "Is there a north arrow or compass rose drawn on this floor plan? If there is, give the direction "
    "its north points as a bearing on the image in degrees: 0 = towards the top of the image, 90 = towards "
    "the right, 180 = down, 270 = left. Only answer has_north true if a north symbol is actually drawn."
)
NORTH_SCHEMA = {
    "type": "object",
    "properties": {"has_north": {"type": "boolean"}, "bearing": {"type": "number"}},
    "required": ["has_north"],
}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def north_arrow(path: Path) -> tuple[float | None, object]:
    """The image bearing of north (0 = up, clockwise), if the plan draws a north arrow."""
    from .. import gemini

    try:
        reply = gemini.generate([gemini.image(path), NORTH_PROMPT], schema=NORTH_SCHEMA, max_tokens=100)
        out = reply.json()
    except Exception:
        return None, None
    if not out.get("has_north") or not isinstance(out.get("bearing"), (int, float)):
        return None, reply
    return float(out["bearing"]) % 360, reply


DOOR_LEAF_M = 0.85  # a Finnish interior door leaf is 0.8-0.9 m wide
DOOR_SCALE_ERR = 0.30
MIN_ROOM_M2 = 1.0  # smaller measured outlines are failed fills; such rooms get no area  # relative error of an area scaled from door widths (about 15% on lengths)


def _px_area(poly: list) -> float:
    from shapely.geometry import Polygon

    return Polygon(poly).area if poly and len(poly) >= 3 else 0.0


def plan_scale(rooms: list[Element], printed: list, doors: list[Element]) -> dict | None:
    """Metres per pixel. First from rooms whose area is printed (their printed m² over their outline's
    pixels; the median, after dropping rooms that disagree by more than 40%); otherwise from the
    typical door, taken as 0.85 m wide. None if neither is available."""
    import statistics

    ratios = [a / px for e, a in zip(rooms, printed) if a and (px := _px_area(e.polygon)) > 0]
    if ratios:
        mid = statistics.median(ratios)
        kept = [r for r in ratios if abs(r / mid - 1) <= 0.4] or [mid]
        m2_per_px2 = statistics.median(kept)
        spread = statistics.median([abs(r / m2_per_px2 - 1) for r in kept]) if len(kept) > 1 else 0.2
        return {"m_per_px": round(m2_per_px2 ** 0.5, 6), "source": "printed areas", "n": len(kept),
                "rel_err": round(max(0.05, spread * 1.5), 3)}
    # The leaf length is the swing radius (hinge to shut position) where the symbol was read; a box
    # also holds the frame and is drawn generously, so it is only the fallback.
    leaves = [math.dist(e.swing["hinge"], e.swing["closed"]) for e in doors if e.swing]
    def leaf(b):
        # A box around a swing is about leaf x leaf; a door drawn as a bare opening is a thin box whose
        # long side is the door width.
        w, h = b[2] - b[0], b[3] - b[1]
        return max(w, h) if max(w, h) > 2.5 * min(w, h) else min(w, h)

    sizes = sorted(leaves) if len(leaves) >= 2 else sorted(leaf(e.bbox) for e in doors if e.bbox)
    if len(sizes) >= 2:
        return {"m_per_px": round(DOOR_LEAF_M / statistics.median(sizes), 6), "source": "door width",
                "n": len(sizes), "rel_err": DOOR_SCALE_ERR}
    return None


def room_areas(rooms: list[Element], printed: list, scale: dict | None) -> None:
    """Printed areas as read; other outlined rooms from their pixels and the scale, with an error."""
    for e, a in zip(rooms, printed):
        if a:
            e.quantities = {"area_m2": round(a, 2)}
            e.quantity_source = {"area_m2": "label"}
        elif scale and e.polygon:
            area = _px_area(e.polygon) * scale["m_per_px"] ** 2
            if area < MIN_ROOM_M2:
                continue  # an outline this small means the room fill failed, not a tiny room
            e.quantities = {"area_m2": round(area, 2), "area_m2_err": round(area * scale["rel_err"], 2)}
            e.quantity_source = {"area_m2": "scale"}


def compass(normal: list[float], north: float) -> str:
    """Compass point of an image direction, given north's image bearing."""
    import math

    bearing = (math.degrees(math.atan2(normal[0], -normal[1])) - north) % 360
    return COMPASS[round(bearing / 45) % 8]


def orient_openings(image, elements: list[Element], north: float | None) -> None:
    """Door swings and window facing, from the symbols and the room regions already found."""
    from shapely.geometry import MultiPoint

    ink = geo.ink_mask(image)
    rooms = [(e.id, e.polygon) for e in elements if e.type == "room" and e.polygon]
    points = [pt for _, poly in rooms for pt in poly]
    footprint = [list(c) for c in MultiPoint(points).convex_hull.exterior.coords] if len(points) >= 3 else None
    for e in elements:
        if e.type == "door" and e.bbox:
            swing = geo.door_swing(ink, e.bbox)
            if swing:
                (hx, hy), (ox, oy), (cx, cy) = swing["hinge"], swing["open"], swing["closed"]
                qx, qy = hx + 0.45 * (ox - hx + cx - hx), hy + 0.45 * (oy - hy + cy - hy)
                swing["into"] = next((rid for rid, poly in rooms if geo.point_in(poly, qx, qy)), None)
                e.swing = swing
        elif e.type == "window" and e.bbox:
            facing = geo.window_facing(e.bbox, rooms, footprint)
            if facing:
                facing["compass"] = compass(facing["normal"], north) if north is not None else None
                e.facing = facing


def room_type(text: str) -> str | None:
    t = re.sub(r"[^A-ZÄÖÅ ]", "", text.upper()).strip()
    if t in ROOM_LABELS:
        return ROOM_LABELS[t]
    return next((rt for prefix, rt in ROOM_PREFIXES if t.startswith(prefix)), None)


GEMINI_LABEL_PROMPT = (
    "Read the room names and room abbreviations printed inside the rooms of this floor plan. Copy each one "
    "exactly as printed, once per room where it appears. Do not list text that is not printed. Skip "
    "handwriting, dimensions, areas and notes outside the plan. Return a JSON list of objects with "
    "\"label\" (the text) and \"point\" [y, x] normalised to 0-1000."
)


def _label_points(path: Path) -> tuple[list[tuple[str, float, float]], object]:
    """(text, x, y) on the 0-1000 grid. Gemini reads labels better (train: +7 to +18 points per
    room type); Nemotron is the fallback without a Gemini key."""
    from .. import gemini, vlm

    if gemini.available():
        reply = gemini.generate([gemini.image(path), GEMINI_LABEL_PROMPT], max_tokens=4000)
        try:
            items = reply.json()
        except ValueError:
            items = []
        points = []
        for it in items if isinstance(items, list) else []:
            pt = it.get("point") if isinstance(it, dict) else None
            if isinstance(pt, list) and len(pt) == 2:
                points.append((str(it.get("label", "")).strip(), float(pt[1]), float(pt[0])))
        return points, reply
    reply = vlm.chat([vlm.image_part(path), {"type": "text", "text": LABEL_PROMPT}], max_tokens=1200)
    return [(m.group(1).strip(), float(m.group(2)), float(m.group(3))) for m in LABEL_LINE.finditer(reply.content)], reply


def _labels(path: Path, w: int, h: int):
    points, reply = _label_points(path)
    seen, out = set(), []
    for text, gx, gy in points:
        x, y = gx / 1000 * w, gy / 1000 * h
        key = (text, round(x / (w * 0.02)), round(y / (h * 0.02)))
        if key in seen or not re.search(r"[A-Za-zÄÖÅäöå]", text):
            continue  # the same label repeated in place, or a printed area / level ("12.5", "+0.750")
        seen.add(key)
        out.append((text, x, y))
    # A generation loop repeats one text down the page; real plans rarely repeat a label more often.
    counts = {}
    for text, _, _ in out:
        counts[text] = counts.get(text, 0) + 1
    out = [o for o in out if counts[o[0]] <= MAX_REPEATS]
    return ([] if len(out) > MAX_LABELS else out), reply


ROOM_BOX_PROMPT = (
    "This floor plan's room labels are listed below with their positions ([y, x], 0-1000). For each label, "
    "give the box of the room it names: the area enclosed by that room's walls, doors and windows, not the "
    "label text and not neighbouring rooms, halls or stairs. If several labels name one open space (e.g. an "
    "open-plan living room and kitchen), split the space between them where the furniture and floor finish "
    "change. If a label is not a room (a note, a level, a dimension), return an empty box.\n"
    "Also give the room's floor area if it is printed on the plan for that room (usually a number under or "
    "beside the label, like \"11.0\", \"11,0 m²\" or \"8.5\"); leave it out if no area is printed. Never "
    "estimate an area yourself.\n"
    "Return a JSON list with one object per label: \"index\" (the number given), \"box_2d\" "
    "[ymin, xmin, ymax, xmax] normalised to 0-1000 or [] for none, and \"area_m2\" if printed.\nLabels:\n"
)
ROOM_BOX_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"index": {"type": "integer"}, "box_2d": {"type": "array", "items": {"type": "number"}},
                                               "area_m2": {"type": "number"}},
              "required": ["index", "box_2d"]},
}


INFER_PROMPT = (
    "This floor plan has few or no printed room names. Identify every room and space on it from what is drawn: "
    "fixtures (a toilet or shower means a bathroom or WC, a stove and counter a kitchen, a bed a bedroom, a sauna "
    "bench a sauna), size and position (a large space with windows a living room, a narrow space by the entrance "
    "a hall, a small enclosed space a closet or storage, an outdoor area behind a railing a balcony). One item per "
    "room, including halls and closets. Return a JSON list of objects: \"use\" (one of bedroom, bathroom, wc_room, "
    "kitchen, living_room, sauna, hall, closet, storage, balcony, other) and \"box_2d\" [ymin, xmin, ymax, xmax] "
    "normalised to 0-1000 around the room, inside its walls."
)
INFER_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"use": {"type": "string"}, "box_2d": {"type": "array", "items": {"type": "number"}}},
              "required": ["use", "box_2d"]},
}
INFERRED_NAMES = {"wc_room": "WC", "living_room": "living room"}


def infer_rooms(path: Path, w: int, h: int, thinking: int = 0):
    """Rooms recognised from what is drawn, for plans without printed names: [(name, use, box)], reply."""
    from .. import gemini

    reply = gemini.generate([gemini.image(path), INFER_PROMPT], schema=INFER_SCHEMA, max_tokens=3000, thinking_budget=thinking)
    try:
        items = reply.json()
    except ValueError:
        return [], reply
    out = []
    for it in items if isinstance(items, list) else []:
        use, b = str(it.get("use") or "other").lower(), it.get("box_2d")
        if isinstance(b, list) and len(b) == 4:
            y0, x0, y1, x1 = (float(v) for v in b)
            if x1 > x0 and y1 > y0:
                name = f"({INFERRED_NAMES.get(use, use.replace('_', ' '))})"
                out.append((name, use if use != "other" else None, [x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h]))
    return out, reply


def room_boxes(path: Path, labels: list[tuple[str, float, float]], w: int, h: int, thinking: int = 0):
    """Per label, the box of the room it names (pixels) and its floor area if printed on the plan;
    None where there is none. One Gemini call. A room's fill is kept inside its box, so a missed door
    cannot let it run into the next room."""
    from .. import gemini

    lines = "\n".join(f"{i}. '{t}' at [{round(y / h * 1000)}, {round(x / w * 1000)}]" for i, (t, x, y) in enumerate(labels))
    reply = gemini.generate([gemini.image(path), ROOM_BOX_PROMPT + lines], schema=ROOM_BOX_SCHEMA,
                            max_tokens=4000, thinking_budget=thinking)
    boxes: list = [None] * len(labels)
    areas: list = [None] * len(labels)
    try:
        items = reply.json()
    except ValueError:
        return boxes, areas, reply
    for it in items if isinstance(items, list) else []:
        i, b = it.get("index"), it.get("box_2d")
        if not (isinstance(i, int) and 0 <= i < len(labels)):
            continue
        if isinstance(b, list) and len(b) == 4:
            y0, x0, y1, x1 = (float(v) for v in b)
            if x1 > x0 and y1 > y0:
                boxes[i] = [x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h]
        a = it.get("area_m2")
        if isinstance(a, (int, float)) and 0.5 <= a <= 500:
            areas[i] = float(a)
    return boxes, areas, reply


ORIENT_PROMPT = (
    "Look at the printed text on this floor plan (room labels, notes). How must the image be turned so "
    "the text reads normally? Answer with one of: upright (already readable), rotate_90 (turn 90 degrees "
    "clockwise), rotate_180, rotate_270 (turn 90 degrees counter-clockwise), mirror (text reads backwards, "
    "flip left-right), mirror_180 (backwards and upside down, flip top-bottom)."
)
ORIENTATIONS = ["upright", "rotate_90", "rotate_180", "rotate_270", "mirror", "mirror_180"]
PLANS_DIR = Path("cache/plans")


UPRIGHT_PROMPT = (
    "Look at the printed text on this floor plan (room labels, notes). Does most of it read normally, "
    "left to right, not sideways, upside down or backwards?"
)
UPRIGHT_SCHEMA = {"type": "object", "properties": {"reads_normally": {"type": "boolean"}}, "required": ["reads_normally"]}


def _turned(image, orientation: str):
    import cv2

    turn = {"rotate_90": cv2.ROTATE_90_CLOCKWISE, "rotate_180": cv2.ROTATE_180, "rotate_270": cv2.ROTATE_90_COUNTERCLOCKWISE}
    if orientation in turn:
        return cv2.rotate(image, turn[orientation])
    if orientation == "mirror":
        return cv2.flip(image, 1)
    if orientation == "mirror_180":
        return cv2.flip(image, 0)  # backwards and upside down = rotate 180 then mirror
    return image


def _reads_upright(image, name: str) -> bool:
    """A second look at the turned image: models often confuse clockwise with counter-clockwise."""
    import cv2

    from .. import gemini

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    probe = PLANS_DIR / f"probe-{name}"
    cv2.imwrite(str(probe), image)
    try:
        return bool(gemini.generate([gemini.image(probe), UPRIGHT_PROMPT], schema=UPRIGHT_SCHEMA, max_tokens=100).json()["reads_normally"])
    except Exception:
        return False
    finally:
        probe.unlink(missing_ok=True)


MIRROR_PROMPT = (
    "Look closely at the letters of the printed room labels on this floor plan. Are the letters mirrored, "
    "i.e. written backwards as seen in a mirror (for example 'R' facing left, words reading right to left)?"
)
MIRROR_SCHEMA = {"type": "object", "properties": {"mirrored": {"type": "boolean"}}, "required": ["mirrored"]}


def _reads_mirrored(image, name: str) -> bool:
    """After a half turn: was the scan flipped top to bottom rather than turned? (3086, 14533)"""
    import cv2

    from .. import gemini

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    probe = PLANS_DIR / f"probe-{name}"
    cv2.imwrite(str(probe), image)
    try:
        return bool(gemini.generate([gemini.image(probe), MIRROR_PROMPT], schema=MIRROR_SCHEMA, max_tokens=100).json()["mirrored"])
    except Exception:
        return False
    finally:
        probe.unlink(missing_ok=True)


def _upright(path: Path):
    """Turn the image so its text reads normally (CubiCasa has rotated and mirrored scans).
    Returns (image, rotation degrees, mirrored, path of the upright copy)."""
    import cv2

    from .. import gemini

    original = cv2.imread(str(path))
    if original is None:
        raise ValueError(f"Cannot read image {path}")
    if not gemini.available():
        return original, 0, False, path
    schema = {"type": "object", "properties": {"orientation": {"type": "string", "enum": ORIENTATIONS}}, "required": ["orientation"]}
    try:
        orientation = gemini.generate([gemini.image(path), ORIENT_PROMPT], schema=schema, max_tokens=100).json()["orientation"]
    except Exception:
        orientation = "upright"  # unsure: leave the image as it is
    other = {"rotate_90": "rotate_270", "rotate_270": "rotate_90"}.get(orientation)
    if other and not _reads_upright(_turned(original, orientation), path.name) and _reads_upright(_turned(original, other), path.name):
        # A quarter turn the wrong way is the usual mistake (12200 was turned 270 instead of 90).
        # Only quarter turns are checked: the check itself misses upside-down text (11142, 3086).
        orientation = other
    if orientation == "upright" and not _reads_upright(original, path.name):
        # Sideways plans get called upright (8389, 1732, 2002: 21 of 151): check, then try both quarter turns.
        orientation = next((o for o in ("rotate_90", "rotate_270") if _reads_upright(_turned(original, o), path.name)), "upright")
    if orientation == "rotate_180" and _reads_mirrored(_turned(original, orientation), path.name):
        # Upside down and backwards: the scan was flipped, not turned. The orientation call
        # answers "rotate_180" for these; asking about mirrored letters directly catches them.
        orientation = "mirror_180"
    if orientation == "upright":
        return original, 0, False, path
    rotation = {"rotate_90": 90, "rotate_180": 180, "rotate_270": 270, "mirror_180": 180}.get(orientation, 0)
    image = _turned(original, orientation)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    upright_path = PLANS_DIR / path.name
    cv2.imwrite(str(upright_path), image)
    return image, rotation, orientation in ("mirror", "mirror_180"), upright_path


GEMINI_COUNT_SCHEMA = {**COUNT_SCHEMA, "properties": {k: {"type": "integer"} for k in COUNT_FIELDS}}


def whole_image_counts(path: Path) -> tuple[dict[str, int] | None, float]:
    """One call counting every COUNT_FIELDS type. Gemini first (train: 71.4% of CubiCasa answers
    right with its counts, 70.6% with Nemotron's), Nemotron without a Gemini key or if Gemini fails;
    None if neither answers, so those types say they can't be answered."""
    from .. import gemini, vlm

    if gemini.available():
        try:
            reply = gemini.generate([gemini.image(path), COUNT_PROMPT], schema=GEMINI_COUNT_SCHEMA, max_tokens=400)
            return {k: max(0, int(v)) for k, v in reply.json().items() if k in COUNT_FIELDS}, reply.cost_usd
        except Exception:
            pass
    try:
        reply = vlm.chat([vlm.image_part(path), {"type": "text", "text": COUNT_PROMPT}], schema=COUNT_SCHEMA,
                         max_tokens=300, retries=1, timeout=45)
        return {k: max(0, int(v)) for k, v in reply.json().items() if k in COUNT_FIELDS}, reply.cost_usd
    except Exception:
        return None, 0.0


def extract(path: Path, refine_rooms: bool = False) -> Drawing:
    """refine_rooms: also ask for each room's extent and keep its fill inside it (the app's
    \"Re-detect rooms\"; thinking on, so a second try is not the cached first)."""
    original = path
    image, rotation, mirrored, path = _upright(path)
    h, w = image.shape[:2]
    elements: list[Element] = []
    cost = 0.0

    def add(source: str = "script+vlm", **kw) -> Element:
        el = Element(id=len(elements) + 1, source=source, exact=False, **kw)
        elements.append(el)
        return el

    from .. import gemini

    # Windows, doors and fixtures first (boxes from Gemini, when a key is set): their doors close
    # the openings the room fill would otherwise leak through. Rooms are still added first, so
    # element ids, which saved reviews refer to, stay as they were.
    detected: list[tuple[str, list[float], float, str]] = []
    north = None
    if gemini.available():
        boxes, reply = detect_elements(path)
        cost += reply.cost_usd
        detected += [(kind, box, 0.9, "gemini") for kind, box in boxes]
        # A second look for doors and windows the first one missed (train: doors 37.8% -> 40.5%
        # exactly right). Its finds are uncertain marks, shown dashed for checking.
        extra, reply = second_look(path, boxes)
        cost += reply.cost_usd
        detected += [(kind, box, SECOND_LOOK_CONF, "gemini second look") for kind, box in extra]
        north, reply = north_arrow(path)
        cost += reply.cost_usd if reply else 0.0
    ink = geo.ink_mask(image)
    door_closures = []
    for kind, box, _, _ in detected:
        if kind == "door":
            swing = geo.door_swing(ink, box)
            door_closures.append((swing["hinge"], swing["closed"]) if swing else box)

    # Rooms: labels, then the free space around each, with doors shut.
    wall, k = geo.wall_mask(image)
    candidates = geo.openings(wall, k)  # sealed so room fills stop at windows and entrances
    labels, reply = _labels(path, w, h)
    cost += reply.cost_usd
    windows = [box for kind, box, _, _ in detected if kind == "window"]
    limits, printed = None, [None] * len(labels)
    if gemini.available() and (refine_rooms or ROOM_BOXES) and labels:
        limits, printed, reply = room_boxes(path, labels, w, h, thinking=1024 if refine_rooms else 0)
        cost += reply.cost_usd
    inferred_uses: list = [None] * len(labels)
    if gemini.available() and len([l for l in labels if room_type(l[0])]) < 2:
        # Hardly any printed names (e.g. 10062 has none): recognise the rooms from what is drawn.
        found, reply = infer_rooms(path, w, h, thinking=1024 if refine_rooms else 0)
        cost += reply.cost_usd
        for name, use, box in found:
            labels.append((name, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
            limits = (limits or [None] * (len(labels) - 1)) + [box]
            printed.append(None)
            inferred_uses.append(use)
    regions = geo.label_regions(image, wall, k, candidates, [(x, y) for _, x, y in labels], doors=door_closures,
                                windows=windows, limits=limits)
    for (text, x, y), region, use in zip(labels, regions, inferred_uses):
        rt = use or room_type(text)
        if region is None:
            s = max(w, h) * 0.02
            bbox, polygon = [x - s, y - s, x + s, y + s], None
        else:
            bbox, polygon = region.bbox, region.polygon
        # Recognised rather than read: uncertain, so it shows dashed and counts by confidence.
        conf = 0.6 if text.startswith("(") else 0.9 if rt else 0.5
        add(type="room", room_type=rt, label=text, bbox=[round(v, 1) for v in bbox], polygon=polygon, conf=conf,
            source="gemini (recognised from the drawing)" if text.startswith("(") else "script+vlm")
    rooms = [e for e in elements if e.type == "room"]

    covers = list(ROOM_MARKED_TYPES)
    for kind, box, conf, source in detected:
        add(type=kind, bbox=[round(v, 1) for v in box], conf=conf, source=source)
    if gemini.available():
        covers += ELEMENT_MARKED_TYPES
        orient_openings(image, elements, north)

    # Room areas: printed on the plan where they are; elsewhere pixels times the plan's scale.
    scale = plan_scale(rooms, printed, [e for e in elements if e.type == "door" and e.conf >= SECOND_LOOK_CONF])
    room_areas(rooms, printed, scale)

    # Whole-image counts for everything marks do not cover yet.
    counts, c = whole_image_counts(path)
    cost += c
    return Drawing(drawing=str(original), kind="raster", extractor_version=VERSION, units="px",
                   elements=elements, covers=covers, counts=counts, extraction_cost_usd=cost,
                   rotation=rotation, mirrored=mirrored, plan_image=str(path) if path != original else None, scale=scale)
