"""Questions no template asks: Gemini reads a digest of the extracted drawing and picks the elements
that answer, the app does the arithmetic.

The model never states a number. It returns element ids and how to combine them (count them, sum
their areas, ...); the value is computed here from those elements, and they are the marks shown on
the plan. Its reading of an ambiguous question comes back as one line, shown with the answer.
Only the app uses this; the batch runner answers from templates alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import gemini
from .schema import Answer, Drawing, Element

MODEL = "gemini-3.8-flash"
DETAIL_TYPES = {"room", "door", "window", "wc", "sink", "shower", "bathtub", "stair", "apartment", "column", "storey"}
STRUCTURE = re.compile(r"\b(walls?|slabs?|beams?|columns?|floors? slab|seinä|wand|mur|muro)\b", re.I)
MAX_LINES = 1500

PROMPT = """You answer questions about one construction drawing, using only the elements listed below. They were extracted from the drawing; each has an id.

Drawing: {kind}. {basis}
{storeys}{elements}
{history}Question: {question}

Symbols in the list carry no subtype: on piping and equipment drawings their type is the tag printed beside them (e.g. CV-1 check valve, FCV flow control valve, MAV manual air vent, PS pipe support); use the nearest text to break counts down by type.
Baseboards (skirting) run along a room's perimeter: use sum_perimeter over the rooms asked about; say in reading that door openings (about 0.9 m each) are not subtracted. "One room" of a repeated type: pick one typical room of that type.
Door directions, "which way doors open", inward/outward and hinge side are the doors' swing attributes; window directions are their faces attribute. Directions are given on the sheet (top/bottom/left/right) unless a compass point is listed.

{image_note}
Answer with:
- aggregate: "count" (the answer is how many of the chosen elements), "sum_area" / "sum_length" / "sum_volume" (add up that quantity of the chosen elements), "pick" (the answer is the chosen element(s) themselves, e.g. "which room is biggest"), "read" (only when the elements cannot answer it but the answer is printed on the drawing image: a dimension, a note, a title-block field), or "none" if neither can answer it.
- "calculate": only for drawings with printed text in the list: a quantity worked out from printed numbers (e.g. a slab area from its dimensions). Give expression: plain arithmetic with numbers and + - * / ( ) only, e.g. "(17100*12800 - 2200*3300)/1000000"; inputs: one object per number taken from the drawing, {{"id": the text element it was read from, "value": the number}}; unit ("m2", "m", "count"); and explain the steps in reading. Only unit-conversion constants (1000, 1000000, 0.3048, 0.092903, 12) may appear in the expression without being inputs.
- "list": for breakdowns ("by type", "the different areas", "each room"): items, one per line of the answer, each {{"label": what it is, "unit": "m2"/"m"/"count"/"text", and one of: "ids" (for a count line: exactly the elements counted; the app counts them), "value" with "id" (read from that text element), or "expression" with "inputs" (calculated, same rules as calculate)}}.
- "describe": for what-is / what-does-it-show questions with no single number: text (2-4 sentences, plain words) and ids of the elements it rests on.
- A number you worked out yourself is only shown with its working: give "expression" and "inputs" for it, never just the result. Lines or answers that state a computed figure without its expression are discarded.
- When printed numbers are not enough for an exact figure, still calculate a reasonable estimate from the overall printed dimensions and element counts, and say exactly what you assumed in reading. Refuse ("none") only when the drawing really cannot support an estimate.
- For "read": value (the number or text exactly as printed, numbers as numbers), unit ("m2", "m", "count" or "text"), and box_2d [ymin, xmin, ymax, xmax] 0-1000 around where you read it. Never estimate or measure for "read": only what is printed.
- ids: every element that makes up the answer. For a count, exactly the elements counted. Never invent ids.
- reading: one short sentence on how you read the question and chose the elements, e.g. "Inward = the door opens into a room rather than into the hall." State assumptions plainly.
- text: for "pick", a short answer (for a list, group them, e.g. "4 open towards the right, 3 towards the bottom"); otherwise "".
In text and reading never write element ids like #17: the reader sees numbered marks, not ids. Refer to elements by their room or label ("the door into KPH").
- noun: what is counted or picked, plural, in English (e.g. "doors", "rooms").
- unknown: how many elements that could belong in the answer lack the attribute needed to decide (e.g. doors with swing=unknown when the question is about which way doors open); 0 if none. Mention them in reading.
Do not compute or state numbers yourself; the app adds them up from the ids."""

SCHEMA = {
    "type": "object",
    "properties": {
        "aggregate": {"type": "string", "enum": ["count", "sum_area", "sum_length", "sum_volume", "sum_perimeter", "pick", "read", "calculate", "list", "describe", "none"]},
        "ids": {"type": "array", "items": {"type": "integer"}},
        "reading": {"type": "string"},
        "text": {"type": "string"},
        "noun": {"type": "string"},
        "unknown": {"type": "integer"},
        "value": {"type": "string"},
        "unit": {"type": "string"},
        "box_2d": {"type": "array", "items": {"type": "number"}},
        "expression": {"type": "string"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "unit": {"type": "string"}, "value": {"type": "string"}, "id": {"type": "integer"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "expression": {"type": "string"},
            "inputs": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "value": {"type": "number"}}, "required": ["id", "value"]}},
        }, "required": ["label"]}},
        "inputs": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "value": {"type": "number"}}, "required": ["id", "value"]}},
    },
    "required": ["aggregate", "ids", "reading"],
}

QUANTITY = {"sum_area": ("area_m2", "m2"), "sum_length": ("length_m", "m"), "sum_volume": ("volume_m3", "m3"),
            "sum_perimeter": ("perimeter_m", "m")}


def _name(e: Element) -> str:
    name = e.label or (e.room_type.replace("_", " ") if e.room_type else None)
    return f" '{name}'" if name else ""


SIDES = {(1, 0): "right", (-1, 0): "left", (0, 1): "bottom", (0, -1): "top"}


def _side(dx: float, dy: float, y_up: bool) -> str:
    if y_up:
        dy = -dy
    return SIDES[(1 if dx > 0 else -1, 0)] if abs(dx) >= abs(dy) else SIDES[(0, 1 if dy > 0 else -1)]


def _swing_words(swing: dict, y_up: bool) -> str:
    """"opens towards the top of the sheet, hinge on the left": the leaf moves from shut to open."""
    (hx, hy), (ox, oy), (cx, cy) = swing["hinge"], swing["open"], swing["closed"]
    return f"opens towards the {_side(ox - hx, oy - hy, y_up)} of the sheet, hinge on the {_side(hx - cx, hy - cy, y_up)} side of the opening"


def _line(e: Element, by_id: dict[int, Element], y_up: bool = False) -> str:
    if e.type == "text":  # sheets: printed text with where it is (pixels), so it can be cited
        x0, y0, x1, y1 = e.bbox or (0, 0, 0, 0)
        return f"#{e.id} text \"{e.label}\" at x={round((x0 + x1) / 2)} y={round((y0 + y1) / 2)}"
    parts = [f"#{e.id} {e.type}{_name(e)}"]
    if e.bbox and e.type not in ("room", "sheet"):
        parts.append(f"at x={round((e.bbox[0] + e.bbox[2]) / 2)} y={round((e.bbox[1] + e.bbox[3]) / 2)}")
    if e.type == "room" and e.room_type:
        parts.append(f"use={e.room_type}")
    if e.number:
        parts.append(f"no={e.number}")
    q = e.quantities or {}
    for key, unit in (("area_m2", "m²"), ("perimeter_m", "m"), ("length_m", "m"), ("volume_m3", "m³")):
        if q.get(key) is not None:
            parts.append(f"{key.split('_')[0]}={q[key]:.2f}{unit}")
    if e.storey:
        parts.append(f"storey={e.storey}")
    if e.apartment:
        parts.append(f"apartment={e.apartment}")
    if e.outdoor:
        parts.append("outdoor")
    if e.swing:
        into = by_id.get(e.swing.get("into")) if e.swing.get("into") is not None else None
        parts.append(f"swing: {_swing_words(e.swing, y_up)}, " + (f"into #{into.id}{_name(into)}" if into else "into no listed room (hall, corridor, outside or unlabelled)"))
    elif e.type == "door":
        parts.append("swing=unknown (symbol not read)")
    if e.facing:
        f = e.facing
        lit = by_id.get(f.get("room")) if f.get("room") is not None else None
        parts.append(f"faces={f.get('compass') or f.get('sheet') + ' of sheet'}" + (f" lights=#{lit.id}{_name(lit)}" if lit else ""))
    if not e.exact and e.conf < 0.8:
        parts.append(f"uncertain({e.conf:.2f})")
    if e.source.startswith("added by"):
        parts.append("added by reviewer")
    return " ".join(parts)


def digest(d: Drawing, question: str) -> str:
    """The drawing's elements, one line each. Structural elements (walls, slabs, ...) are listed only
    when the question is about them; otherwise just counted, to keep the prompt small."""
    by_id = {e.id: e for e in d.elements}
    structural = bool(STRUCTURE.search(question)) or d.kind == "sheet"  # a sheet's text is its content
    lines, skipped = [], {}
    for e in d.elements:
        if e.type in DETAIL_TYPES or structural:
            lines.append(_line(e, by_id, y_up=d.kind in ("dxf", "ifc")))
        else:
            skipped[e.type] = skipped.get(e.type, 0) + 1
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"... {len(lines) - MAX_LINES} more not listed"]
    out = "Elements:\n" + "\n".join(lines)
    if skipped:
        out += "\nAlso present, not listed: " + ", ".join(f"{n} {t}" for t, n in sorted(skipped.items()))
    if d.covers is not None:
        out += ("\nOnly these types were looked for on this image: " + ", ".join(sorted(set(d.covers) | {"room"}))
                + ". Others may exist without being listed.")
    return out


def _image(d: Drawing) -> Path | None:
    """The image the model can look at: an image plan, a rendered PDF page or a sheet's reduced
    overview (same proportions as the sheet). Not CAD or IFC."""
    if d.kind == "sheet":
        overview = Path("cache/plans") / f"{Path(d.drawing).stem}-overview.jpg"
        return overview if overview.exists() else None
    if d.kind not in ("raster", "pdf"):
        return None
    path = Path(d.plan_image or d.drawing)
    return path if path.exists() and path.suffix.lower() in (".png", ".jpg", ".jpeg") else None


def _drawing_size(d: Drawing) -> tuple[int, int]:
    """(width, height) of the drawing's own pixel coordinates."""
    from PIL import Image

    with Image.open(d.plan_image or d.drawing) as im:
        return im.width, im.height


def _read_answer(d: Drawing, image: Path, out: dict, reading: str, cost: float) -> Answer | None:
    """A value read off the image. The box where it was read is shown on the plan, so it can be checked."""
    raw = str(out.get("value") or "").strip()
    box = out.get("box_2d")
    if not raw or not (isinstance(box, list) and len(box) == 4):
        return Answer(template="analyst", value=None, unit=None, exact=False, params={"reading": reading}, cost_usd=cost)
    w, h = _drawing_size(d)  # boxes are 0-1000 of the image, which has the drawing's proportions
    y0, x0, y1, x1 = (float(v) for v in box)
    # The image plan's pixels are the drawing coordinates (rendered PDF pages are drawn the same way).
    read_box = [round(x0 / 1000 * w, 1), round(y0 / 1000 * h, 1), round(x1 / 1000 * w, 1), round(y1 / 1000 * h, 1)]
    unit = out.get("unit") if out.get("unit") in ("m2", "m", "count", "text") else "text"
    try:
        value: float | str = float(raw.replace(",", ".").replace(" ", "")) if unit != "text" else raw
    except ValueError:
        value, unit = raw, "text"
    return Answer(template="analyst", value=value, unit=unit, exact=False, cost_usd=cost,
                  params={"reading": reading, "aggregate": "read", "read_box": read_box})


CONSTANTS = {1000.0, 1000000.0, 0.3048, 0.092903, 12.0, 2.0, 144.0, 10.7639}
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _evaluate(expression: str) -> float | None:
    """Plain arithmetic only: numbers, + - * / and brackets. Anything else is refused."""
    import ast

    if not re.fullmatch(r"[\d.+\-*/() \t]+", expression or ""):
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}.get(type(n.op), a / b if b else float("nan"))
        raise ValueError("not arithmetic")

    try:
        return ev(ast.parse(expression, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None


def _calculated(by_id: dict[int, Element], out: dict, reading: str, cost: float) -> Answer:
    """A quantity worked out from printed numbers. The app checks that every number in the expression
    was read from a cited piece of text (unit constants aside) and does the arithmetic itself."""
    expression = (out.get("expression") or "").strip()
    inputs = [i for i in out.get("inputs") or [] if isinstance(i, dict) and i.get("id") in by_id]
    unit = out.get("unit") if out.get("unit") in ("m2", "m", "count") else None
    cited = {float(i["value"]) for i in inputs}
    used = [float(n) for n in NUMBER.findall(expression)]
    # Small whole numbers may be counts or multipliers (e.g. 10 rooms in a wing); the expression is shown.
    unknown = [n for n in used if n not in cited and n not in CONSTANTS and not (n == int(n) and n <= 100)]
    # Each cited number must really be printed in the text it is said to come from.
    misquoted = [i for i in inputs if not any(float(n) == float(i["value"]) for n in NUMBER.findall((by_id[i["id"]].label or "").replace(",", "")))]
    value = _evaluate(expression)
    if value is None or unit is None or unknown or misquoted or not inputs:
        why = ("its arithmetic used numbers not read from the drawing" if unknown
               else "a number it cited is not in the text it cited" if misquoted else "its working could not be checked")
        return Answer(template="analyst", value=None, unit=None, exact=False, cost_usd=cost,
                      params={"reading": f"{reading} (Not shown: {why}.)".strip()})
    ids = list(dict.fromkeys(i["id"] for i in inputs))
    return Answer(template="analyst", value=round(value, 3), unit=unit, exact=False, cost_usd=cost, evidence_ids=ids,
                  params={"reading": reading, "aggregate": "calculate", "expression": expression,
                          "noun": "" if unit != "count" else (out.get("noun") or "")})


def _first_number(raw: str) -> float | None:
    """The number in a value the model quoted, which may carry its unit ("6,095 SF")."""
    m = NUMBER.search(str(raw or "").replace(",", ""))
    return float(m.group()) if m else None


def _number_in(text: str, value: float) -> bool:
    return any(float(n) == value for n in NUMBER.findall((text or "").replace(",", "")))


def _listed(by_id: dict[int, Element], out: dict, reading: str, cost: float) -> Answer:
    """A breakdown: one checked line per item. Read lines must quote a number printed in the cited
    text; calculated lines go through the same checks as calculate. Lines that fail are left out and
    counted, never shown unchecked."""
    rows, ids, dropped = [], [], 0
    listed = [i for i in out.get("ids") or [] if i in by_id]
    texts = [e for e in by_id.values() if e.type == "text"]
    for it in out.get("items") or []:
        if not isinstance(it, dict) or not (it.get("label") or "").strip():
            continue
        raw_unit = str(it.get("unit") or "").strip().lower()
        sqft = raw_unit in ("sq ft", "sf", "sqft", "ft2", "ft²", "square feet")
        unit = "sqft" if sqft else it.get("unit") if it.get("unit") in ("m2", "m", "count", "text") else "text"
        if not it.get("expression") and it.get("id") not in by_id and str(it.get("value") or "").strip():
            # The source was not given per line: take a printed text holding exactly this number,
            # preferring the elements the model listed. No such text, no line.
            num = _first_number(it["value"])
            if num is not None:
                pool = [by_id[i] for i in listed if by_id[i].type == "text"] + texts
                src = next((e for e in pool if _number_in(e.label, num)), None)
                if src is not None:
                    it = {**it, "id": src.id}
        counted = [i for i in dict.fromkeys(it.get("ids") or []) if i in by_id]
        if counted and not it.get("expression"):
            # A count line: its value is how many cited elements there are, counted here.
            rows.append({"label": it["label"].strip(), "value": float(len(counted)), "unit": "count", "how": "counted"})
            ids += counted
            continue
        if it.get("expression"):
            a = _calculated(by_id, {**it, "unit": unit if unit != "text" else None}, "", 0.0)
            if a.value is None:
                dropped += 1
                continue
            rows.append({"label": it["label"].strip(), "value": a.value, "unit": unit, "how": f"= {it['expression']}"})
            ids += a.evidence_ids
        elif it.get("id") in by_id and str(it.get("value") or "").strip():
            raw = str(it["value"]).strip()
            src = by_id[it["id"]].label or ""
            num = _first_number(raw) if unit != "text" or re.fullmatch(r"[\d,.\s]+(sf|sq ?ft|m2|m²|m)?", raw.lower()) else None
            if num is not None and not _number_in(src, num):
                dropped += 1  # quoted a number that is not in the text it cites
                continue
            row = {"label": it["label"].strip(), "value": num if num is not None else raw, "unit": unit, "how": "printed"}
            if sqft and num is not None:
                row["m2"] = round(num * 0.092903, 1)
            rows.append(row)
            ids.append(it["id"])
        else:
            dropped += 1
    if not rows:
        return Answer(template="analyst", value=None, unit=None, exact=False, cost_usd=cost, params={"reading": reading})
    def fmt(r: dict) -> str:
        if not isinstance(r["value"], float):
            return f"{r['label']}: {r['value']}"
        if r["unit"] == "sqft":
            return f"{r['label']}: {r['value']:,g} SF ({r['m2']:,g} m²)"
        unit = "" if r["unit"] in ("count", "text") else r["unit"].replace("m2", "m²")
        return f"{r['label']}: {r['value']:,g} {unit}".strip()

    return Answer(template="analyst", value="; ".join(fmt(r) for r in rows), unit="text", exact=False, cost_usd=cost,
                  evidence_ids=list(dict.fromkeys(ids)),
                  params={"reading": reading, "aggregate": "list", "items": rows, "dropped": dropped})


def analyse(d: Drawing, question: str, history: list[dict] | None = None, retry: bool = True) -> Answer | None:
    """An answer built from the elements Gemini picks. When it cannot answer, value is None and
    params["reading"] says why; None only when the reply is unusable."""
    basis = ("Elements were read exactly from the file." if d.covers is None
             else "Elements were detected in an image; positions and counts are estimates.")
    if d.kind == "sheet" and d.scale:
        info = d.scale
        basis += (f" Sheet {info.get('sheet_id') or ''} \"{info.get('title') or ''}\" ({info.get('discipline') or 'unknown'} "
                  f"drawing; printed scale {info.get('scale') or info.get('printed') or 'unknown'}; dimensions in "
                  f"{info.get('units') or 'unknown units'}). {info.get('summary') or ''} The element list is the "
                  "sheet's printed text and symbols, read tile by tile at full resolution.")
    storeys = [e.label for e in d.elements if e.type == "storey" and e.label]
    hist = ""
    if history:
        hist = "Earlier in this conversation:\n" + "\n".join(f"Q: {h.get('question', '')}\nA: {h.get('answer', '')}" for h in history[-4:]) + "\n"
    image = _image(d)
    note = ("The drawing image is attached: use it to understand the question and to read printed numbers or notes. "
            "Coordinates in the element list are image pixels." if image else "")
    prompt = PROMPT.format(kind=d.kind, basis=basis, storeys=f"Storeys: {', '.join(storeys)}\n" if storeys else "",
                           elements=digest(d, question), history=hist, question=question, image_note=note)
    parts = [gemini.image(image), prompt] if image else [prompt]
    reply = gemini.generate(parts, model=MODEL, schema=SCHEMA, max_tokens=6000)
    try:
        out = reply.json()
    except ValueError:
        return None
    by_id = {e.id: e for e in d.elements}
    ids = [i for i in dict.fromkeys(out.get("ids") or []) if i in by_id]  # known ids only, once each
    agg = out.get("aggregate")
    reading = (out.get("reading") or "").strip()
    if agg == "read" and image:
        return _read_answer(d, image, out, reading, reply.cost_usd)
    if agg == "calculate":
        answer = _calculated(by_id, out, reading, reply.cost_usd)
        if answer.value is None and retry:
            note = ("\nYour previous answer was discarded: " + answer.params.get("reading", "").split("(Not shown: ")[-1].rstrip(".)")
                    + ". Cite each printed number you use as an input.")
            again = analyse(d, question + note, history, retry=False)
            if again is not None:
                again.cost_usd += reply.cost_usd
                return again
        return answer
    if agg == "list":
        answer = _listed(by_id, out, reading, reply.cost_usd)
        if answer.value is None and out.get("items") and retry:
            # Every line failed its check: say why, once, and let the model redo it with its working.
            note = ("\nYour previous answer was discarded: its lines gave results without an expression and inputs "
                    "(or quoted numbers that are not in the cited text). Give each calculated line its expression and "
                    "the printed numbers it uses.")
            again = analyse(d, question + note, history, retry=False)
            if again is not None:
                again.cost_usd += reply.cost_usd
                return again
        return answer
    if agg == "describe" and (out.get("text") or "").strip():
        return Answer(template="analyst", value=out["text"].strip(), unit="text", exact=False, cost_usd=reply.cost_usd,
                      evidence_ids=ids, params={"reading": reading, "aggregate": "describe"})
    if agg not in ("count", "sum_area", "sum_length", "sum_volume", "sum_perimeter", "pick") or (agg != "count" and not ids):
        # Cannot answer, but say why: that is still useful ("no north arrow on this plan").
        return Answer(template="analyst", value=None, unit=None, exact=False, params={"reading": reading}, cost_usd=reply.cost_usd)
    chosen = [by_id[i] for i in ids]
    params = {"reading": reading, "aggregate": agg}
    noun = (out.get("noun") or "").strip().lower()
    if noun and re.fullmatch(r"[a-z][a-z ]{0,30}", noun):
        params["noun"] = noun  # so the answer says "4 doors", not "4 items"
    unknown = out.get("unknown")
    if isinstance(unknown, int) and unknown > 0:
        params["unknown"] = unknown
    if agg == "count":
        value, unit = len(chosen), "count"
    elif agg == "pick":
        value, unit = (out.get("text") or "").strip() or ", ".join(f"#{e.id}{_name(e)}" for e in chosen), "text"
    else:
        key, unit = QUANTITY[agg]
        missing = [e for e in chosen if (e.quantities or {}).get(key) is None]
        if missing:  # the drawing does not hold that quantity for every chosen element
            return Answer(template="analyst", value=None, unit=None, exact=False, cost_usd=reply.cost_usd,
                          params={"reading": f"{len(missing)} of the elements it needs have no {key.split('_')[0]} in this drawing."})
        value = round(sum(e.quantities[key] for e in chosen), 3)
        # Image plans: areas measured with an estimated scale carry an error; show it as a range.
        err = sum((e.quantities or {}).get(f"{key}_err") or 0.0 for e in chosen)
        params["basis"] = sorted({(e.quantity_source or {}).get(key) for e in chosen} - {None})
        if err:
            rng_q = [round(value - err, 2), round(value + err, 2)]
            params["range"] = rng_q
    certain = [e.id for e in chosen if e.exact or e.conf >= 0.8]
    unsure = [e.id for e in chosen if e.id not in set(certain)]
    rng = params.pop("range", None)
    if agg == "count" and params.get("unknown"):
        rng = [value, value + params["unknown"]]  # each undecidable element might belong in the answer
    # Never "exact": the elements may be, but which ones answer the question is the model's reading.
    return Answer(template="analyst", value=value, unit=unit, exact=False, params=params, range=rng,
                  evidence_ids=certain, uncertain_ids=unsure, cost_usd=reply.cost_usd)
