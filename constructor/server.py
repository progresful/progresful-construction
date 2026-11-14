"""HTTP API for the app (API.md). Answers go through the same answer() as the batch runner.

    uv run --extra app uvicorn constructor.server:app --port 8000
    CONSTRUCTOR_DATA=data/preview/junction-dataset-preview  (default)
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from urllib.parse import quote
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import analyst, gemini, llm, overview, render
from .answer import answer
from .batch import FIELDS, load_questions
from .ingest import best_source, cache_path, ensure_extracted, load_cached, route
from .reviews import apply_reviews, load_reviews, next_added_id, save_review
from .schema import Answer, Drawing
from .templates import ELEMENT_TYPES

DATA = Path(os.environ.get("CONSTRUCTOR_DATA", "data/preview/junction-dataset-preview"))
SAMPLE_QUESTIONS = 8
# Costs are only meaningful once list prices are configured; until then the app says "not priced".
COST_KNOWN = any(float(os.environ.get(k, "0")) > 0 for k in (
    "VLM_PRICE_IN_PER_M", "VLM_PRICE_OUT_PER_M", "GEMINI_PRICE_IN_PER_M", "GEMINI_PRICE_OUT_PER_M"))

app = FastAPI(title="Constructor")
pool = ThreadPoolExecutor(max_workers=2)
preparing: set[str] = set()
failed: dict[str, str] = {}
lock = threading.Lock()


# --- index -----------------------------------------------------------------------------


def _drawing_id(path: str) -> str:
    rel = path.removeprefix("data/")
    return re.sub(r"[^\w.-]+", "_", rel.rsplit(".", 1)[0].replace("/", "__"))


@lru_cache(maxsize=1)
def index() -> dict[str, dict]:
    """Drawings that have questions, keyed by id, with their questions."""
    questions: dict[str, list[str]] = defaultdict(list)
    for r in load_questions(DATA / "questions.jsonl"):
        questions[r[FIELDS["drawing"]]].append(r[FIELDS["question"]])
    out = {}
    # Challenge sheets first: shared by the owners with no gold answers, their example questions as starters.
    for path, qs in _challenge().items():
        out[_drawing_id(path)] = {"path": path, "source": "challenge", "questions": qs, "starters": qs}
    for path, qs in questions.items():
        out[_drawing_id(path)] = {"path": path, "source": path.split("/")[1], "questions": qs}
    return out


def _challenge() -> dict[str, list[str]]:
    """data/challenge/*: the owners' example sheets and their starter questions (starters.json)."""
    folder = DATA / "data" / "challenge"
    if not folder.is_dir():
        return {}
    starters = json.loads((folder / "starters.json").read_text()) if (folder / "starters.json").exists() else {}
    return {f"data/challenge/{f.name}": starters.get(f.name, []) for f in sorted(folder.iterdir())
            if f.suffix.lower() in (".png", ".jpg", ".jpeg")}


def _entry(drawing_id: str) -> dict:
    entry = index().get(drawing_id)
    if entry is None:
        raise HTTPException(404, f"No drawing {drawing_id}")
    return entry


def _file(entry: dict) -> Path:
    return DATA / entry["path"]


@lru_cache(maxsize=None)
def _read_from(path: str) -> str:
    try:
        return route(best_source(DATA / path))
    except Exception:
        return "unknown"


@lru_cache(maxsize=None)
def _licence_table(source: str) -> tuple[dict[str, tuple[str, str, str]], tuple[str, str] | None]:
    """Per-file (licence, credit, title) from data/<source>/LICENSE.md, plus the "All files:" default."""
    path = DATA / "data" / source / "LICENSE.md"
    if not path.exists():
        return {}, None
    per_file: dict[str, tuple[str, str, str]] = {}
    default = None
    for line in path.read_text().splitlines():
        if line.startswith("| ") and not line.startswith(("| file", "|---")):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 4:
                per_file[cells[0]] = (cells[2], cells[3], cells[1])
        elif m := re.match(r"All files: (\S+)\. Credit: (.+)", line):
            default = (m.group(1).strip(), m.group(2).strip())
    return per_file, default


def licence(entry: dict) -> tuple[str, str]:
    per_file, default = _licence_table(entry["source"])
    name = Path(entry["path"]).name
    lic, credit = (per_file[name][:2] if name in per_file else None) or default or ("unknown", entry["source"])
    return lic, f"{credit} · {lic}"


def _title(entry: dict) -> str:
    per_file, _ = _licence_table(entry["source"])
    row = per_file.get(Path(entry["path"]).name)
    return overview.title(entry["path"], row[2] if row else None)


@lru_cache(maxsize=None)
def _cache_file(path: str) -> Path:
    """Where a drawing's extraction is cached (the richest sibling decides; looked up once)."""
    return cache_path(best_source(DATA / path))


def _status(drawing_id: str, entry: dict) -> str:
    if drawing_id in preparing:
        return "preparing"
    # Only whether it was read: parsing every cached drawing made the list slow at thousands of them.
    if _cache_file(entry["path"]).exists():
        return "ready"
    return "failed" if drawing_id in failed else "not_extracted"


def _load(drawing_id: str) -> tuple[dict, Drawing]:
    entry = _entry(drawing_id)
    cached = load_cached(best_source(_file(entry)))
    if cached is None:
        raise HTTPException(409, "Drawing is not extracted yet; POST /extract first")
    return entry, cached


# --- plans -----------------------------------------------------------------------------


@lru_cache(maxsize=512)
def _image_size(path: str) -> tuple[int, int]:
    """(height, width) without decoding the pixels: sheets are 10,000 pixels wide."""
    from PIL import Image

    with Image.open(path) as im:
        return im.height, im.width


def _plan_info(drawing_id: str, d: Drawing, storey: str | None = None) -> dict | None:
    url = f"/api/drawings/{drawing_id}/plan"
    if d.kind == "ifc":
        viewbox = render.ifc_storey_viewbox(d, storey) if storey else None
        if viewbox is None:
            return None
        url += f"?storey={quote(storey)}"
        return {"url": url, "width": viewbox[2] * 40, "height": viewbox[3] * 40, "viewbox": viewbox, "flip_y": True}
    if d.kind == "dxf":
        _, viewbox = _dxf_plan(d.drawing)
        return {"url": url, "width": viewbox[2] * 60, "height": viewbox[3] * 60, "viewbox": viewbox, "flip_y": True}
    if d.kind in ("raster", "pdf", "sheet") and (d.plan_image or d.kind in ("raster", "sheet")):
        h, w = _image_size(d.plan_image or d.drawing)
        # The image behind this URL changes when re-extraction turns it; a new URL keeps browsers
        # from showing a cached old image under the new marks.
        url += f"?v={d.extractor_version}-{d.rotation}{'m' if d.mirrored else ''}"
        return {"url": url, "width": w, "height": h, "viewbox": [0, 0, w, h], "flip_y": False}
    return None


@lru_cache(maxsize=32)
def _dxf_plan(path: str) -> tuple[str, list[float]]:
    return render.dxf_svg(Path(path))


def _no_derivatives(entry: dict) -> bool:
    # NoDerivatives files must stay unchanged; the dataset renders no drawings from them, nor do we.
    return "-ND" in licence(entry)[0].upper()


# --- answer text -----------------------------------------------------------------------

NOUNS = {
    "window": "windows", "door": "doors", "wc": "WCs", "sink": "sinks", "shower": "showers",
    "bathtub": "bathtubs", "shower_or_bathtub": "showers and bathtubs", "wall": "walls",
    "column": "columns", "beam": "beams", "stair": "stairs", "slab": "slabs", "apartment": "apartments",
    "space": "rooms", "valve": "valves", "pump": "pumps", "instrument": "instruments", "fitting": "fittings",
    "fixture": "fixtures", "equipment": "pieces of equipment", "tank": "tanks",
}
ROOM_NOUNS = {
    "bedroom": "bedrooms", "bathroom": "bathrooms", "kitchen": "kitchens", "sauna": "saunas",
    "wc_room": "WC rooms", "balcony": "balconies", "living_room": "living rooms", "hall": "halls",
    "closet": "closets", "storage": "storage rooms",
}
UNITS = {"m2": "m²", "m3": "m³", "m": "m"}


def _highlighted(a: Answer) -> str:
    n = len(a.evidence_ids)
    return f"{n} element{'' if n == 1 else 's'} highlighted on the plan."


def answer_text(a: Answer) -> str:
    if a.value is None:
        why = a.params.get("reading") if a.template == "analyst" else None
        return f"I can't answer this from the drawing. {why}" if why else "I can't answer this from the drawing yet."
    if a.template == "analyst":
        reading = a.params.get("reading", "")
        n = len(a.evidence_ids) + len(a.uncertain_ids)
        marked = f" {n} marked on the plan." if n else ""
        if a.params.get("aggregate") == "list":
            dropped = a.params.get("dropped") or 0
            note = f" {dropped} more line(s) left out because their numbers could not be checked." if dropped else ""
            return f"{a.value}. {reading}{note}".strip()
        if a.params.get("aggregate") == "describe":
            return f"{a.value} {marked}".strip()
        if a.params.get("aggregate") == "calculate":
            shown = f"{a.value:g} {UNITS.get(a.unit or '', '')}".strip()
            return f"≈ {shown}, calculated from {len(a.evidence_ids)} printed dimensions (boxed on the plan): {a.params.get('expression')}. {reading}".strip()
        if a.params.get("aggregate") == "read":
            shown = f"{a.value:g} {UNITS.get(a.unit or '', '')}".strip() if isinstance(a.value, float) else str(a.value)
            return f"{shown}, as printed on the drawing (boxed on the plan). {reading}".strip()
        if a.unit == "text":
            return f"{a.value} {reading}{marked}".strip()
        if a.unit == "count":
            noun = a.params.get("noun") or "elements"
            head = f"{a.value} {noun if a.value != 1 else noun.removesuffix('s')}"
            if a.params.get("unknown"):
                head += f" (up to {a.value + a.params['unknown']}: {a.params['unknown']} could not be checked)"
        else:
            head = f"{a.value} {UNITS.get(a.unit or '', '')}".strip()
            basis = a.params.get("basis") or []
            if "scale" in basis:
                rng = f"; likely {a.range[0]:g} to {a.range[1]:g} {UNITS.get(a.unit or '', '')}" if a.range else ""
                head = f"≈ {head} (estimate, measured on the image with an estimated scale{rng})"
            elif basis == ["label"]:
                head = f"{head} (as printed on the plan)"
        return f"{head}. {reading}{marked}".strip()
    if a.unit == "count" and a.template == "count_elements" and a.params.get("items"):
        noun = NOUNS.get(a.params.get("element", ""), "items")
        parts = ", ".join(f"{int(i['value'])} {i['label']}" for i in a.params["items"])
        return f"{a.value} {noun}: {parts}. Each one marked on the plan."
    if a.unit == "count":
        room = ROOM_NOUNS.get(a.params.get("room_type", ""), f"rooms labelled {a.params['label']}" if a.params.get("label") else "rooms")
        noun = NOUNS.get(a.params.get("element", ""), room if a.template == "count_rooms" else "storeys" if a.template == "count_storeys" else "items")
        if a.value == 1:
            noun = {"showers and bathtubs": "shower or bathtub", "WCs": "WC", "storeys": "storey", "balconies": "balcony",
                    "WC rooms": "WC room", "storage rooms": "storage room"}.get(noun, noun.removesuffix("s"))
        head = f"{a.value} {noun}"
    else:
        head = f"{a.value} {UNITS.get(a.unit or '', '')}".strip()
    if a.exact:
        return f"{head} (exact, from model data). {_highlighted(a)}"
    if a.unit == "count" and not a.evidence_ids:
        rng = f", likely {a.range[0]} to {a.range[1]}" if a.range else ""
        if not a.uncertain_ids:
            return f"{head} (estimate from one look at the whole image{rng}; no elements marked yet)."
        n = len(a.uncertain_ids)
        agree = "they agree" if n == a.value else f"the count and the {n} marked disagree; check them"
        return f"{head} (estimate from one look at the whole image{rng}). {n} label{'' if n == 1 else 's'} marked on the plan; {agree}."
    basis = a.params.get("basis") or []
    if "scale" in basis or ("label" in basis and a.params.get("scale_source") is not None):
        how = {"printed areas": "the room areas printed on the plan", "door width": "door widths (a door taken as 0.85 m)"}.get(
            a.params.get("scale_source"), "the plan's scale")
        printed = " partly read from areas printed on the plan," if "label" in basis and "scale" in basis else ""
        rng = f"; likely {a.range[0]:g} to {a.range[1]:g} m²" if a.range else ""
        return f"≈ {head} (estimate:{printed} measured on the image using {how}{rng}). {_highlighted(a)}"
    if basis == ["label"]:
        return f"{head} (as printed on the plan). {_highlighted(a)}"
    if not a.uncertain_ids and a.unit != "count":
        # Structured elements, but the quantity was computed from their geometry, not read from the file.
        return f"{head} (computed from the drawing geometry, not read from the file). {_highlighted(a)}"
    tail = f"{len(a.evidence_ids)} marked on the plan" + (f", {len(a.uncertain_ids)} of them uncertain" if a.uncertain_ids else "")
    rng = f", likely {a.range[0]} to {a.range[1]}" if a.range and a.range[0] != a.range[1] else ""
    # Calibrated ranges reach past the marks when marks of this type tend to miss some.
    misses = " Marks like these often miss a few; look for unmarked ones." if a.range and a.range[1] > a.value + 1 else ""
    return f"{head} (estimate{rng}). {tail}.{misses}"


# --- routes ----------------------------------------------------------------------------


@app.get("/api/drawings")
def drawings() -> list[dict]:
    out = []
    for drawing_id, entry in index().items():
        out.append({
            "id": drawing_id,
            "path": entry["path"],
            "source": entry["source"],
            "read_from": _read_from(entry["path"]),
            "status": _status(drawing_id, entry),
            "question_count": len(entry["questions"]),
            "credit": licence(entry)[1],
            "error": failed.get(drawing_id),
            "title": _title(entry),
            "subtitle": overview.subtitle(entry["source"], _read_from(entry["path"]), entry["path"]),
            "thumb_url": f"/api/drawings/{drawing_id}/thumb" if _thumb_source(entry) else None,
        })
    return out


@app.get("/api/drawings/{drawing_id}")
def drawing(drawing_id: str) -> dict:
    entry, d = _load(drawing_id)
    storeys = [e.label for e in d.elements if e.type == "storey" and e.label] if d.kind == "ifc" else []
    plans = {} if _no_derivatives(entry) else {s: p for s in storeys if (p := _plan_info(drawing_id, d, s))}
    plan = None if _no_derivatives(entry) else (next(iter(plans.values()), None) if d.kind == "ifc" else _plan_info(drawing_id, d))
    seen, samples = set(), []
    for q in entry["questions"]:
        if q not in seen and q.isascii():
            seen.add(q)
            samples.append(q)
    return {
        "id": drawing_id,
        "credit": licence(entry)[1],
        "plan": plan,
        "plans": plans,
        "plan_note": "No plan shown: the file's licence (NoDerivatives) does not allow rendered drawings." if _no_derivatives(entry) else None,
        "storeys": [s for s in storeys if s in plans] or storeys,
        "sample_questions": samples[:SAMPLE_QUESTIONS],
        "drawing": json.loads(d.to_json()),
    }


@app.get("/api/drawings/{drawing_id}/plan")
def plan(drawing_id: str, storey: str | None = None):
    entry, d = _load(drawing_id)
    if _no_derivatives(entry):
        raise HTTPException(403, "NoDerivatives licence: no rendered plan")
    if d.kind == "ifc":
        if not storey:
            raise HTTPException(400, "IFC plans are per storey: ?storey=")
        svg = render.ifc_svg(d, storey)
        if svg is None:
            raise HTTPException(404, f"Nothing to draw on storey {storey}")
        return Response(svg[0], media_type="image/svg+xml")
    if d.kind == "dxf":
        return Response(_dxf_plan(d.drawing)[0], media_type="image/svg+xml")
    if d.kind in ("raster", "pdf", "sheet") and (d.plan_image or d.kind in ("raster", "sheet")):
        return FileResponse(d.plan_image or d.drawing)  # the upright copy / rendered page the marks refer to
    raise HTTPException(404, f"No plan renderer for {d.kind} yet")


@app.post("/api/drawings/{drawing_id}/extract")
def extract(drawing_id: str) -> dict:
    entry = _entry(drawing_id)

    def run():
        try:
            # The user asked for this drawing, so paid (vision) extraction is allowed.
            ensure_extracted(_file(entry), allow_raster=True)
            failed.pop(drawing_id, None)
        except NotImplementedError:
            failed[drawing_id] = f"The {_read_from(entry['path'])} extractor is not built yet."
        except RuntimeError:  # paid extraction not allowed
            failed[drawing_id] = "This drawing needs the vision model, which is not enabled yet."
        except Exception as e:  # shown in the drawing list; the details go to the server log
            print(f"extraction failed: {entry['path']}: {type(e).__name__}: {e}")
            failed[drawing_id] = "Extraction failed on this drawing."
        finally:
            with lock:
                preparing.discard(drawing_id)

    with lock:
        if drawing_id not in preparing:
            preparing.add(drawing_id)
            pool.submit(run)
    return {"ok": True, "status": "preparing"}


@app.post("/api/drawings/{drawing_id}/rooms/redetect")
def redetect_rooms(drawing_id: str) -> dict:
    """Find this image plan's rooms again, more carefully: Gemini gives each room's extent (thinking
    on, so it is a fresh attempt, not the cached one) and every fill is kept inside it. Element ids
    stay the same, so saved reviews still apply."""
    from .extractors import raster

    entry, d = _load(drawing_id)
    if d.kind != "raster":
        raise HTTPException(400, "Rooms on this drawing are read from the file; there is nothing to re-detect.")
    if not gemini.available():
        raise HTTPException(400, "Re-detecting rooms needs GEMINI_API_KEY.")
    source = best_source(_file(entry))
    new = raster.extract(source, refine_rooms=True)
    new.save(cache_path(source))
    rooms = [e for e in new.elements if e.type == "room"]
    return {"ok": True, "rooms": len(rooms), "with_outline": sum(e.polygon is not None for e in rooms),
            "cost_usd": new.extraction_cost_usd, "cost_known": COST_KNOWN}


class Ask(BaseModel):
    drawing_id: str
    question: str
    # The last few questions and answers on this drawing, for follow-ups ("and in the bathrooms?").
    history: list[dict] | None = None


@app.post("/api/ask")
def ask(body: Ask) -> dict:
    entry, d = _load(body.drawing_id)
    d = apply_reviews(d, load_reviews(cache_path(best_source(_file(entry)))))
    try:
        a = answer(d, body.question, llm=llm.mapper(), verify=llm.verifier())
    except RuntimeError as e:  # the model could not be reached: answer from the rules alone
        print(f"mapping with Gemini failed: {e}")
        a = answer(d, body.question)
    if d.scale and "scale" in (a.params.get("basis") or []):
        a.params["scale_source"] = d.scale.get("source")
    if a.value is None and gemini.available():
        # No template asks this: let Gemini pick the elements that answer it; the value is computed from them.
        try:
            a = analyst.analyse(d, body.question, body.history) or Answer.cannot_answer(cost_usd=a.cost_usd)
        except Exception as e:
            print(f"analyst failed: {type(e).__name__}: {e}")
    text = answer_text(a)
    if gemini.available():
        try:
            text, cost = llm.phrase(body.question, text)
            a.cost_usd += cost
        except Exception as e:  # phrasing is a nicety; the English sentence is always correct
            print(f"phrasing failed: {type(e).__name__}: {e}")
    return {**a.to_dict(), "text": text, "cost_known": COST_KNOWN}


class Review(BaseModel):
    id: int | None = None  # None for "add": the server assigns one
    action: str
    type: str | None = None
    # "add" only: the box in drawing coordinates, and for rooms their use and name.
    bbox: list[float] | None = None
    polygon: list[list[float]] | None = None  # "add" and "reshape": an outline instead of a box
    room_type: str | None = None
    label: str | None = None
    storey: str | None = None


REVIEW_TYPES = set(NOUNS) - {"shower_or_bathtub", "space"} | {"room", "storey"} | {t for ts in ELEMENT_TYPES.values() for t in ts}


@app.post("/api/drawings/{drawing_id}/reviews")
def review(drawing_id: str, body: Review) -> dict:
    entry, d = _load(drawing_id)
    cache_file = cache_path(best_source(_file(entry)))
    edits = load_reviews(cache_file)
    if body.action not in ("accept", "reject", "retype", "add", "reshape"):
        raise HTTPException(400, "action must be accept, reject, retype, add or reshape")
    if body.action == "reshape":
        if not (body.bbox and len(body.bbox) == 4) and not (body.polygon and len(body.polygon) >= 3):
            raise HTTPException(400, "reshape needs bbox [x0, y0, x1, y1] or a polygon of 3+ points")
        if body.bbox:
            x0, y0, x1, y1 = body.bbox
            body.bbox = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    if body.action in ("retype", "add") and body.type not in REVIEW_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(REVIEW_TYPES)}")
    if body.action == "add":
        if body.polygon and len(body.polygon) >= 3:
            xs, ys = [p[0] for p in body.polygon], [p[1] for p in body.polygon]
            body.bbox = [min(xs), min(ys), max(xs), max(ys)]
        if not body.bbox or len(body.bbox) != 4:
            raise HTTPException(400, "add needs bbox [x0, y0, x1, y1] (or a polygon) in drawing coordinates")
        x0, y0, x1, y1 = body.bbox
        edit = {**body.model_dump(exclude_none=True), "id": next_added_id(edits),
                "bbox": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]}
        save_review(cache_file, edit)
        return {"ok": True, "id": edit["id"], "review": edit}
    known = {e.id for e in d.elements} | {e["id"] for e in edits if e["action"] == "add"}
    if body.id not in known:
        raise HTTPException(404, f"No element {body.id}")
    save_review(cache_file, body.model_dump(exclude_none=True))
    return {"ok": True}


@app.get("/api/drawings/{drawing_id}/reviews")
def reviews(drawing_id: str) -> list[dict]:
    entry = _entry(drawing_id)
    return load_reviews(cache_path(best_source(_file(entry))))


# --- overview, suggestions, thumbnails ---------------------------------------------------

THUMB_DIR = Path("cache/thumbs")
THUMB_WIDTH = 240


def _thumb_source(entry: dict) -> Path | None:
    """An image of the drawing to shrink: the PNG itself, or a rendered sibling (Swiss PNG, plan PDF)."""
    if _no_derivatives(entry):
        return None
    f = _file(entry)
    for candidate in (f.with_suffix(".png"), f.with_suffix(".jpg"), f.with_suffix(".pdf")):
        if candidate.exists():
            return candidate
    plan_pdfs = sorted(f.parent.glob(f"{f.stem}_plan-*.pdf"))  # IFC models with a rendered plan
    return plan_pdfs[0] if plan_pdfs else None


@app.get("/api/drawings/{drawing_id}/thumb")
def thumb(drawing_id: str):
    import cv2
    import numpy as np

    entry = _entry(drawing_id)
    source = _thumb_source(entry)
    if source is None:
        raise HTTPException(404, "No thumbnail for this drawing")
    out = THUMB_DIR / f"{drawing_id}.png"
    if not out.exists():
        if source.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(source))
            page = pdf[0]
            scale = THUMB_WIDTH * 2 / page.get_width()
            image = cv2.cvtColor(np.asarray(page.render(scale=scale).to_pil()), cv2.COLOR_RGB2BGR)
            pdf.close()
        else:
            image = cv2.imread(str(source))
        h, w = image.shape[:2]
        thumb_img = cv2.resize(image, (THUMB_WIDTH, max(1, int(h * THUMB_WIDTH / w))), interpolation=cv2.INTER_AREA)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), thumb_img)
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


@app.get("/api/drawings/{drawing_id}/overview")
def drawing_overview(drawing_id: str) -> dict:
    entry, d = _load(drawing_id)
    d = apply_reviews(d, load_reviews(cache_path(best_source(_file(entry)))))
    facts = overview.facts(d, answer_text)
    for f in facts:
        f["answer"]["cost_known"] = COST_KNOWN
    return {
        "kind": d.kind,
        "exact": d.kind in ("ifc", "dxf"),
        "facts": facts,
        "rooms": overview.rooms(d),
        # Technical sheets: what the title block says (sheet id, title, discipline, scale, units, summary).
        "sheet": d.scale if d.kind == "sheet" else None,
    }


@app.get("/api/drawings/{drawing_id}/suggestions")
def drawing_suggestions(drawing_id: str) -> list[str]:
    entry, d = _load(drawing_id)
    return entry.get("starters") or overview.suggestions(d)
