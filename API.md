# App API

The Python server (`constructor/server.py`) serves this; the React app (`app/`) consumes it.
All JSON. The app talks to `/api` and the Vite dev server proxies it to `http://localhost:8000`.

## Drawings

`GET /api/drawings`

```json
[
  {
    "id": "swiss_dwellings__site3387_bldg5238_floor23498",
    "path": "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf",
    "source": "swiss_dwellings",
    "read_from": "dxf",
    "status": "ready",
    "question_count": 37,
    "credit": "Swiss Dwellings v3.0.0 by ... · CC-BY-4.0",
    "error": null
  }
]
```

- `status` is `ready` (extracted and cached), `not_extracted`, `preparing`, or `failed` (then `error` says why, e.g. "The raster extractor is not built yet").
- `read_from` is the kind actually extracted: `ifc`, `dxf`, `pdf` or `raster`.
- `credit` must be shown whenever the drawing is shown.

`GET /api/drawings/{id}` returns the cached Drawing (schema in SPEC.md, "Data formats") plus:

```json
{
  "id": "...",
  "credit": "...",
  "plan": {"url": "/api/drawings/{id}/plan", "width": 1200, "height": 900, "viewbox": [0, 0, 1200, 900], "flip_y": false},
  "plans": {"1. Sal": {"url": "/api/drawings/{id}/plan?storey=1.%20Sal", "...": "PlanInfo"}},
  "plan_note": null,
  "storeys": ["1. Sal", "2. Sal"],
  "sample_questions": ["How many windows are drawn on this floor plan?", "..."],
  "drawing": { "...Drawing JSON...": "elements, kind, units, ..." }
}
```

- `plan.url` is an image (PNG or SVG) of the plan. Element `bbox` and `polygon` coordinates map onto it through `viewbox` (`[x, y, width, height]` in drawing coordinates). When `flip_y` is true (CAD and IFC, where y points up), y must be flipped: `screen_y = viewbox_y + viewbox_h - (y - viewbox_y)`.
- For IFC, the plan is per storey, each with its own viewbox: use `plans[storey]`. `plan` is the first storey. Elements carry `storey`; show only the selected storey's elements.
- When `plan_note` is set (files under a NoDerivatives licence), `plan` is null and `plans` is empty: show the note instead of an image. Answers still work.
- DXF and IFC plans are SVG drawn in metres with `flip_y: true`; raster plans are the image itself.

`POST /api/drawings/{id}/extract` starts extraction; poll `GET /api/drawings` for `status`.

## Asking

`POST /api/ask`

```json
{"drawing_id": "...", "question": "Kuinka monta ikkunaa pohjapiirustuksessa on?"}
```

returns the Answer (SPEC.md, "Answer") plus a ready-made sentence:

```json
{
  "template": "count_elements",
  "params": {"element": "window"},
  "value": 13,
  "unit": "count",
  "exact": false,
  "range": [12, 14],
  "evidence_ids": [1, 5, 9],
  "uncertain_ids": [7, 12],
  "cost_usd": 0.0002,
  "fallback": false,
  "text": "13 windows (estimate, 12 to 14). 12 confirmed, 2 uncertain, marked on the plan."
}
```

Questions no template asks ("how many doors open inwards", "which room is biggest", follow-ups) go to the
analyst (`constructor/analyst.py`, needs `GEMINI_API_KEY`): Gemini reads a digest of the extracted elements and returns
the ids that answer plus how to combine them; the value is computed from those ids, which are the marks. Such answers
have `template: "analyst"`, `exact: false`, `params.reading` (how the question was read), `params.noun`, and, when some
elements could not be checked, `params.unknown` and a `range`. `POST /api/ask` takes an optional `history`
(`[{question, answer}]`, oldest first) for follow-ups. A rule match on a question with a condition no template expresses
is dropped (English words; non-English rule matches are double-checked by the Gemini mapper), so the analyst gets it.

When `value` is null the app shows "I can't answer this from the drawing yet". `text` is always present (English for now).
The answer reflects saved reviews for that drawing.

Errors are JSON `{"detail": "..."}` with a 4xx status; 409 means the drawing is not extracted yet.

## Re-detecting rooms

`POST /api/drawings/{id}/rooms/redetect` (image plans, needs `GEMINI_API_KEY`) finds the rooms again, more carefully, and
replaces the cached drawing; element ids stay the same so reviews still apply. Returns `{"ok": true, "rooms": 12,
"with_outline": 11, ...}`. 400 for drawings whose rooms are read from the file.

## Reviews

`POST /api/drawings/{id}/reviews` with `{"id": 7, "action": "accept" | "reject" | "retype", "type": "door"}`
returns `{"ok": true}`. The app then re-asks the drawing's questions so the counts update.

Adding something the drawing missed: `{"action": "add", "type": "door", "bbox": [x0, y0, x1, y1]}` with the box in
drawing coordinates, plus `room_type`, `label` (rooms) and `storey` (IFC) where they apply. Returns
`{"ok": true, "id": 1000000, "review": {...}}`. Added elements get ids from 1,000,000 up (re-extraction numbers from 1),
count as confirmed marks but never as exact, and make their type countable from marks on image plans. Rejecting an
added id deletes the addition; retyping changes its type. The batch runner never reads reviews.

Adjusting a found or added element: `{"id": 7, "action": "reshape", "bbox": [...]}` or `{"id": 7, "action": "reshape",
"polygon": [[x, y], ...]}` (drawing coordinates). An element keeps one verdict (accept, reject or retype) and one reshape,
independently. A room's area follows a new outline only where it was computed from geometry (metres); areas read from
the file or printed on the plan stay as they are.

`GET /api/drawings/{id}/reviews` returns the list of saved edits.

## Overview, suggestions, thumbnails (UX round 2)

List items (`GET /api/drawings`) also carry:

- `title`: a readable name, e.g. "Molio Demo-hus · Plantegning: Kælder", "Swiss apartment floor · site 2150", "CubiCasa plan 11397".
- `subtitle`: source and kind, e.g. "Swiss Dwellings · DXF · exact".
- `thumb_url`: `/api/drawings/{id}/thumb` (PNG, about 240 px wide) or null when there is none (NoDerivatives, or not extracted).

`GET /api/drawings/{id}/overview` (drawing must be extracted) answers the drawing's standard questions with the same
`answer()` as `/api/ask`, so overview and chat never disagree:

```json
{
  "kind": "raster",
  "exact": false,
  "facts": [
    {"key": "window", "label": "Windows", "question": "How many windows are shown on this floor plan?",
     "answer": { "...Answer as from /api/ask, with text...": "" }},
    {"key": "room_area:2.04", "label": "Pièce 2.04", "question": "...", "answer": {}}
  ],
  "rooms": [
    {"id": 12, "label": "Pièce", "number": "2.04", "type": "room", "room_type": null, "area_m2": 16.19, "storey": "2e étage", "exact": false}
  ]
}
```

- `facts` lists counts and totals the drawing can answer (value not null), most useful first. Clicking one should show
  its answer card and evidence, exactly as if the user had asked `question`.
- `rooms` lists the drawing's rooms (with area where known), for a room table; ids are element ids for highlighting.

`GET /api/drawings/{id}/suggestions` returns 4–6 short questions this drawing can answer, e.g.
`["How many windows?", "How many bedrooms?", "Area of apartment A?"]`. They go through the mapper like typed questions.
