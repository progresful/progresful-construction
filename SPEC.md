# Constructor app spec

14 Nov 2026 · @Jurgis · rev 7 (calibrated ranges, upright plans, IFC area properties)

Constructor answers questions about construction drawings and shows where each answer came from. Structured data (IFC quantities, IFC and DXF elements, vector PDF text) gives exact answers. Anything reconstructed or seen in pixels gives an estimate, with every counted element marked on the plan for review. It is our entry for Stoa's "Make Blueprints Talk" challenge at Junction 2026.

## How it works

A drawing is extracted once, when it is added. Structured files are parsed. Images go through a script that proposes candidates and the NVIDIA vision model that confirms them. Every question after that is a lookup in the cached file. Extraction has a one-off cost per drawing, and each question costs one cheap text-model call to pick a template. Both are reported (see Cost).

## What the user sees

One screen with three parts: a drawing list on the left, the drawing in the middle, and a question box with answer cards on the right.

1. Add a drawing. The user picks one from the dataset or uploads a file. The app shows "Preparing" while extraction runs, once per drawing.
2. Ask a question in any language, for example "Kuinka monta ikkunaa pohjapiirustuksessa on?" The card answers in the language of the question.
3. Read the answer card. It carries a badge, the value, and the evidence drawn on the plan.
4. Review. On an estimate, the user clicks a mark to accept, reject or retype it, and the count updates.

Every displayed drawing shows its credit and licence from `data/<source>/LICENSE.md`. The dataset requires it.

| | Exact | Estimate |
|---|---|---|
| When | Every evidence element is exact (see Exactness) | Any evidence element is derived or seen in pixels |
| Typical sources | IFC with quantity sets, DXF blocks and text, vector PDF text | PNG, JPEG, scanned PDF, reconstructed DXF rooms |
| Badge | "Exact, from model data" | "Estimate" |
| Answer | One value with its unit | One value plus a range, such as 13 (12 to 14) |
| Evidence | The room or elements highlighted, with their IDs | A mark on every counted element: solid when confirmed, dashed when uncertain |
| Review | Not needed | Marks can be accepted, rejected or retyped |

An estimate card reads: 13 windows (estimate, 12 to 14). 12 confirmed, 2 uncertain, marked on the plan.

Questions the app has no template for get a plain "I can't answer this from the drawing yet", never a guess. The batch runner may use a fallback for scoring (see Scoring).

## Components

The chat app and the batch runner call the same `answer()` function, so the demo and the score cannot drift apart.

| Part | Owns | Built with |
|---|---|---|
| Ingest | Picking the richest copy of a drawing (IFC > DXF > PDF > image: a Swiss `.pdf` is read from its `.dxf`, an `ifc_models` plan PDF from its `.ifc`), routing by file type (scanned PDFs go to raster), running extraction once, caching one JSON per drawing per extractor version | Python |
| Exact extractors | IFC storeys, spaces, doors, windows, fixtures and quantities; DXF rooms, labels and blocks; PDF text and tables | ifcopenshell (LGPL), ezdxf (MIT), shapely (BSD), pypdfium2 (Apache/BSD), pdfplumber (MIT) |
| Plan renderer | IFC: a section cut per storey to SVG. DXF: ezdxf drawing add-on to SVG. PDF: page to PNG. Renders the copy that was extracted, so evidence lines up; the app shows that rendering, not the file the user picked | ifcopenshell.geom, ezdxf, pypdfium2 |
| Raster extractor | Fixing rotation, proposing candidates from pixels, confirming them with the NVIDIA vision model, a second look for misses | opencv (Apache), Tesseract or PaddleOCR (Apache), Nemotron VL |
| Answer engine | Mapping a question to a template and parameters, then running a count, area or lookup function over the cached JSON; questions no template asks go to the analyst (Gemini picks element ids from a digest of the drawing, the app computes the value from them, the reading is shown); phrasing the answer in the asker's language | Python; rule-based mapper first, Gemini as fallback (returns "none" for conditions no template expresses, so it never guesses); Gemini rewrites the answer sentence keeping every number (`constructor/llm.py`) |
| App | Drawing list with titles and thumbnails, an overview of what the drawing already answers (facts and a room table, from the same `answer()` as the chat), short suggestions, question box, answer cards that zoom the plan to their evidence, editable marks | React, SVG overlay on the rendered plan; `constructor/overview.py` on the server |
| Batch runner | Running questions.jsonl through `answer()` and printing accuracy and cost per source, tier and template, on the held-out split | Python CLI |

The raster extractor is specified in STOA_RASTER_BRIEF.md.

If a trained detector is needed, use an Apache or MIT one (torchvision Faster R-CNN, RT-DETR via HF transformers, YOLOX). Ultralytics YOLO is AGPL and is ruled out. PyMuPDF is AGPL and is ruled out. `scripts/license_check.py` fails the build on any AGPL or GPL dependency.

## Data formats

Every extractor writes the same file, one per drawing, so the answer engine does not care where the data came from. The schema lives in `constructor/schema.py`.

```json
{
  "drawing": "data/cubicasa5k/colorful-11397.png",
  "kind": "raster",
  "extractor_version": "raster-0.1",
  "units": "px",
  "rotation": 180,
  "extraction_cost_usd": 0.004,
  "elements": [
    {"id": 1, "type": "window", "bbox": [412, 88, 472, 102], "conf": 0.94, "exact": false, "source": "script+vlm", "storey": null, "page": null},
    {"id": 2, "type": "room", "room_type": "bedroom", "label": "MH", "number": null, "apartment": null, "outdoor": false, "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]], "quantities": null, "quantity_source": null, "exact": false, "source": "vlm"}
  ]
}
```

- `kind` is `ifc`, `dxf`, `pdf` or `raster`.
- `extractor_version` is bumped whenever an extractor changes. Ingest re-extracts only drawings whose cached version is older. Raster re-extraction costs vision calls, so it is never automatic.
- `bbox` is `[x0, y0, x1, y1]`. Positions are in the drawing's own coordinates: model units for IFC and DXF (`units` says which), PDF points for PDF, pixels for images.
- Raster coordinates are in the image **after** the rotation fix. The app shows the rotated image, so marks line up without conversion.
- `type` is one of `window`, `door`, `wc`, `sink`, `shower`, `bathtub`, `wall`, `column`, `beam`, `stair`, `slab`, `room`, `apartment`, `storey`. Extractors emit one `storey` element per IFC storey, or per plan drawn in an image.
- `exact` is per element. It is true only when the element is read directly from the file: an IFC element, a DXF block insert or text entity, or PDF text. Rooms rebuilt from DXF polylines and anything from pixels are `exact: false`.
- `label` is the room name as written (`'Cage d'escalier'`, `'TUALETTRUUM (43-3)'`). `number` is the room number (`2.13`), `apartment` the apartment letter, `outdoor` marks balconies, loggias and terraces.
- `quantities` holds `area_m2`, `length_m`, `side_area_m2` and `volume_m3`, filled only where the file carries real units or a printed value. DXF with `$INSUNITS` unset gives no quantities, not a guess.
- `quantity_source` says, per quantity, `quantity_set` (read from an IFC quantity set), `label` (printed on the drawing) or `geometry` (computed). An answer is exact only if every quantity it sums was read, not computed.
- `source` is the IFC GlobalId, the DXF handle, the PDF object reference, or `script`, `vlm` or `script+vlm` for images.
- `storey` is the IFC storey name for IFC elements. `page` is the 0-based page for PDF elements.
- `conf` is 1.0 for structured sources.

Review edits never touch this file. They live in `reviews/<drawing-id>.json` as `{"id": 7, "action": "reject" | "accept" | "retype", "type": "door"}`. The app applies them on top of the cache. The batch runner ignores them, so human review never leaks into the score.

### Answer

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
  "fallback": false
}
```

- `value` is a number for counts and areas and a string for lookups. It is what gets scored.
- `unit` is `count`, `m2`, `m3`, `m` or `text`. Gold answers in `ft2` are converted at scoring time.
- `exact` is true only when every element in `evidence_ids` is exact.
- `evidence_ids` are the confirmed elements. `uncertain_ids` are the uncertain ones. The two lists do not overlap.
- `cost_usd` is the cost of this question only (mapping call plus any fallback). Extraction cost is on the drawing.
- When there is no template: `template: null`, `value: null`, and the app shows "I can't answer this from the drawing yet".
- `fallback: true` marks an answer from the batch-only fallback (see Scoring).

### Estimate maths

Raster candidates are sorted by `conf`:

- `conf >= 0.8`: confirmed, solid mark.
- `0.4 <= conf < 0.8`: uncertain, dashed mark.
- `conf < 0.4`: dropped, not shown.

`value = confirmed + round(sum of conf over uncertain)`, `range = [confirmed, confirmed + uncertain]`. Example: 12 confirmed plus uncertain at 0.6 and 0.5 gives 12 + round(1.1) = 13, range 12 to 14. The thresholds are tuned on the training split, never on the held-out split.

Image marks miss things the bands cannot see (a mark that was never proposed has no `conf`), so raster count ranges are then widened by calibration: per type, the 10th and 90th percentile of (gold − count) on train, for mark counts and for whole-image counts separately, and per count size (≤3, 4–9, ≥10; a size with under 15 train cases uses the type's overall band) so a studio's one window doesn't inherit a house's misses (`scripts/calibrate.py` writes `constructor/calibration.json`). Windows, for example, run −1 to +7 (marks under-count), so 12 marked windows read "12, likely 11 to 19" and the card says marks like these often miss a few. The range contains the true count 83 to 100% of the time per type on both splits; the value itself is right for windows only 26 to 29% of the time, so the 10-versus-13 miss in review was typical.

## Data handling

- **The preview is in `data/preview/`** (0.5 GB, 320 drawings, 7,990 questions; `scripts/check_spec_numbers.py`). The 10 GB full set (about 14,000 drawings, 120,000 questions) is not downloaded yet; it needs about 20 GB of disk with the zip.
- **What the preview holds.** Questions point at four file kinds, but the richest copy decides the extractor:

  | Source | Questions | Question file | Read from | Languages |
  |---|---|---|---|---|
  | cubicasa5k | 4,270 (53%) | PNG | PNG | en, fi (each question twice) |
  | swiss_dwellings | 2,358 (30%) | PDF | DXF | en, de, fr, it |
  | ifc_models | 1,049 (13%) | IFC, plan PDF | IFC (24 questions on the FZK-Haus plan PDF have no IFC in the preview) | en, da, et, de |
  | ifc_bench | 249 (3%) | IFC | IFC | en, free-form text answers |
  | opening_design | 64 (1%) | PDF | vector PDF (door and finish schedules) | en |

  Question types: 6,076 count, 1,599 area, 34 volume, 16 length, 265 text. The challenge-page figures check out: 16% IFC (13.5% direct plus 2.8% plan PDFs rendered from IFC), 30% DXF, 402 English IFC room-area questions, 12 CubiCasa templates.
- **The split happens before anyone reads the questions.** `constructor/split.py` assigns each drawing *group* to train or held-out by a hash (20% held out). A group keeps every copy of one drawing together: the same stem in other formats, an IFC model and its plan PDFs, all sheets of one `opening_design` project. Templates, the Finnish abbreviation dictionary, prompts and thresholds are designed on train only. The held-out numbers go in the deck.
- **The Swiss held-out number is contaminated.** Until rev 4, `split.group_of` misread full paths (it took the first `data/` folder), and the DXF rules were fitted on files picked with it: 6 of the 7 held-out Swiss drawings were looked at. The bug is fixed and tested. The Swiss held-out score (100%, 268 questions) is therefore not a clean estimate; the clean check is the full set's Swiss drawings that are not in the preview. Report it that way in the deck.
- **The held-out split is coarse for IFC.** It holds 1,148 questions: 712 CubiCasa, 268 Swiss, 147 `ifc_bench`, 20 `opening_design` and 1 `ifc_models`, because the preview has only a handful of IFC models. The IFC held-out number therefore says little; the deck reports it with its question count.
- **CubiCasa exclusion.** `scripts/cubicasa_exclusion.py` matches Stoa's raster filenames against CubiCasa5K plan IDs and writes `excluded_ids.txt` (241 IDs from the preview; rerun on the full set). Any training or few-shot example reads that file and skips those plans. The CubiCasa5K pretrained weights were trained on the full set, so they are not used. The deck discloses which CubiCasa5K plans we trained on.
- **Licences.** Each drawing keeps its own licence, credited in `data/<source>/LICENSE.md`. CubiCasa5K is CC BY-NC-SA 4.0: non-commercial use is fine, and a detector trained on it may count as an adaptation that must carry the same licence. Keep trained weights out of the MIT code release and publish them, if at all, under CC BY-NC-SA.

## Scoring

The batch runner scores the way the dataset README says Stoa scores: counts must be exact; areas, lengths and volumes must be within 2%; text answers are free-form. `constructor/scoring.py` scores text by normalised match, which undercounts; the 265 text questions are checked by hand or by a model judge, and reported separately.

A refusal scores zero. The app always refuses honestly. The batch runner has a `--fallback` flag that sends unmapped questions to the whole-image vision model, sets `fallback: true`, and reports fallback answers and their accuracy in their own column. We submit whichever is higher on held-out data, and the deck says which.

## Cost

The cost report shows three numbers per source and tier:

1. Extraction cost per drawing (one-off).
2. Cost per question (template mapping plus any fallback).
3. Total cost per question: (2) plus (1) spread over the drawing's questions in the dataset.

All costs use the provider's list price, even where we run on free credits.

## Build order

Each step ends with the batch runner's scoreboard, so progress is a number.

0. **Done.** Preview downloaded, split by drawing group, CubiCasa exclusion list built, numbers checked, licence check passing.
1. **Done.** Batch runner and question templates. Nine template families (`count_elements`, `count_rooms`, `count_storeys`, `room_area`, `total_area`, `apartment_area`, `wall_length`, `wall_side_area`, `element_volume`) with about 50 parameter combinations. The rule-based mapper maps 98.3% of train questions to a template with the gold answer's unit (`scripts/coverage.py`): 100% of CubiCasa, Swiss and `ifc_models`, 55% of `opening_design`, 7% of the free-form `ifc_bench`.
2. **Done.** IFC extractor (`constructor/extractors/ifc.py`). Quantity sets first (per-quantity unit scale: Molio lengths are mm), geometry when a model has none (Esplanades spaces: footprint of the space solid). Stair flights inside a stair are not counted. Recorded area properties (e.g. Esplanades `AR_Ruum.120_Pindala`) are read before geometry, so those areas are exact (284 of 285 spaces). Train: every numeric `ifc_models` question correct (97.7% of the tier; the 24 misses are the FZK-Haus plan PDF with no IFC in the preview).
3. **Done.** IFC plan renderer (`constructor/render.py`): one SVG per storey from the extracted footprints, in metres, so the overlay lines up by construction. Known gap: walls contained in another storey (Molio external walls) are not drawn.
4. **Done.** DXF extractor and renderer for the Swiss apartments (`constructor/extractors/dxf.py`). Rules: one 5-point door symbol per door (swing arcs are per leaf), one closed window outline per window, fixtures by shape (69-point tub, 5-point shower tray, 48-point bowl with or without a tap), apartments are tagged units only, number-only rooms bounded by a railing (wall ≤ 0.1 m) are balconies. Train: 99.6% (2,090 questions).
5. **Started.** Every PDF now opens: page 0 is rendered for the viewer and its words become label elements (`constructor/extractors/pdf.py`); no counts or areas yet. The FZK-Haus plan sheet has no IFC in the preview, so its whole-model questions say "can't answer". Next: vector PDF extractor for the `opening_design` door and finish schedules (64 questions; about half need schedule-specific templates). Scanned PDFs go to raster.
5b. `ifc_bench` free-form questions (249, text answers): a text model over the extracted IFC JSON. Low priority: 3% of questions, scored by hand.
6. **Done.** Raster baseline (`scripts/raster_baseline.py`, prompt in `constructor/extractors/raster.py`): one Nemotron 3.5 Super VL call per image returns all 12 CubiCasa counts as schema-constrained JSON, thinking off, temperature 0, cached by request hash. About 1,250 tokens and 1 to 3 s per image; 191 images took 50 s with 12 parallel calls, so the full set fits easily. Accuracy, train 61.0% (3,558 questions), held-out 65.2% (712, clean): storeys 97.5%, bathrooms 85%, kitchens 81%, balconies 80%, saunas 78%, bedrooms 74%, showers and bathtubs 71%, WC seats 58%, WC rooms 57%, sinks 50%, doors 16%, windows 15%. These counts now answer every raster question as "estimate from one look at the whole image; no elements marked yet" (`Drawing.counts`), until step 8 produces marks that beat them per type.
7. **Started.** Raster text labels: OCR plus the Finnish abbreviation dictionary (`constructor/extractors/raster.py`, Tesseract, free). Keeps only near-black pixels so coloured walls and fills don't drown the text; ignores lower-case handwriting. Train: room-type counts 40 to 69% correct (mostly under-counting by one: missed labels). Window, door and fixture counts and the storey count return "can't answer" (the drawing's `covers` lists only rooms) until step 8. Next: recover missed labels (rotation, small fonts, multi-word labels), then the vision baseline for comparison.
8. **Done for most types.** Per image, three model calls and free geometry (`constructor/extractors/raster.py`, `raster_geometry.py`):
   - Room labels with positions (Gemini `gemini-3.8-flash`; Nemotron without a Gemini key). The prompt lists no example labels: with examples a model lists them whether printed or not. Free geometry finds the walls, seals wall-thick gaps and splits the floor between the labels by growing them all at once, so each label gets its room's area (96% of rooms; the rest get a box around the label).
   - Windows, doors, WC seats, sinks, showers and bathtubs as boxes (Gemini, one call). Gemini localises plan symbols well where Nemotron did not (Nemotron read decking, stairs and counters as windows).
   - Room fills run after detection, with every detected door shut (hinge to shut position, or the box side the wall runs through when the swing is unknown) and every window treated as wall; each fill then loses thin necks and keeps its main body. This stopped rooms leaking through doorways onto balconies (e.g. 11397's living room). Rooms with an outline: 95.3% -> 95.5%. Each fill is also kept inside the room's extent, which Gemini gives per label (one call; it splits open-plan spaces where furniture and finish change, so they no longer split on a diagonal). The app's "Re-detect rooms" reruns this for one drawing with thinking on, and the Adjust tool redraws single outlines.
   - A second look for missed doors and windows (Gemini, one call): the plan is shown with what was found boxed, and only unboxed ones are asked for. Its finds are uncertain marks (conf 0.75, dashed). Train: doors exactly right 37.8% -> 40.5%, windows unchanged; mainly it puts misses like double and folding doors on the plan for checking.
   - Door swings and window facing, free: the hinge is the box corner whose quarter arc is inked, the leaf is the edge whose tip points into open floor (the shut edge runs into wall), the room it opens into is the room under the swing. Windows face the side across the glazing that is in no room. A north arrow, if drawn, turns that into a compass point (one Gemini call). 710 of 2,137 doors get a swing (double, sliding and folding doors return none), 975 of 1,768 windows a facing. Swiss CAD doors get exact swings from their arcs (36/36 on a sample plan).
   - Whole-image counts (Gemini first, Nemotron without a key: with everything else equal, 71.4% vs 70.6% of CubiCasa train answers right; none if neither answers, and those types then say "can't answer"), for types marks do not beat. A failed Nemotron call marks it down for the rest of the run, so a dead endpoint costs one timeout.
   - Before all of these, one Gemini call classifies orientation (upright, rotated, mirrored); the upright copy is what models read and what the viewer shows (`Drawing.rotation`, `mirrored`, `plan_image`). 90 of 241 CubiCasa images were turned or mirrored. After a turn, quarter turns are re-checked ("does the text read normally?"; models confuse clockwise and anticlockwise), plans called upright are checked the same way (21 of 151 were sideways), and half turns are checked for mirrored letters (2 of 41 were flipped, not turned). CubiCasa now: train 74.6%, held-out 74.7%.
   On all 201 train images, marks beat the whole-image count for windows (30.3% vs 14.9%), doors (41.9% vs 16.2%), WC seats (80.5% vs 57.5%), sinks (62.8% vs 50.3%), WC rooms (89.2% vs 57.0%), balconies (85.5% vs 80.0%) and bedrooms (77.3% vs 74.2%); those are counted from marks. Kitchens, bathrooms, saunas, showers and bathtubs keep the whole-image value with their marks shown as evidence, and the card says when the two disagree. CubiCasa: train 71.6%, held-out 72.5% (was 61.0% / 65.2% with whole-image counts only).
9. **In progress.** App (`app/`, React) built on mock data; API server (`constructor/server.py`) serves real extractions, plans and answers. Wiring the app to the server is being verified.
10. Review marks and the cost report.
11. Deck and demo video.

## When

| Checkpoint | |
|---|---|
| Sat 09:00 | IFC score in (steps 0 and 1 are done) |
| Sat 13:00 | IFC renderer and DXF score in |
| Sat 15:00 | Raster baseline, rate-limit maths and first pipeline score. Decide whether a trained detector is needed (Apache or MIT only) |
| Sat 22:00 | App shows exact and estimate answers with overlays. Full-dataset run started, if the rate-limit maths says it fits |
| Sun 04:00 | Deck and demo video drafted |
| Sun 06:00 | Freeze. Held-out numbers go in the deck |
| Sun 10:00 | Submission switched to FINAL |

## Rules

How it maps to Stoa's judging (25% each):

- **Accuracy:** exact parsing where the file is structured, and a measured held-out score per tier on images.
- **Verifiable reasoning:** every answer points to elements on the drawing, and says whether it is exact or estimated.
- **Creativity:** the script proposes, the model confirms, a person reviews.
- **Low inference cost:** vision runs once per drawing. The cost report shows extraction, per-question and amortised cost.

Rules:

- No use of CubiCasa5K's public annotation files, or weights trained on them, for plans in Stoa's dataset. Enforced by `excluded_ids.txt`. Training on other CubiCasa5K plans is allowed and is disclosed.
- All code is written at the event and released under MIT. No AGPL or GPL dependencies in shipped code. Enforced by `scripts/license_check.py`.
- API keys stay in environment variables (`VERDA_INFERENCE_KEY` for Nemotron, `GEMINI_API_KEY` for Gemini), never in the repo. `.instructions` holds both today and is gitignored; move them to the shell environment or a gitignored `.env`. Without `GEMINI_API_KEY` everything still runs: Nemotron reads labels, windows/doors/fixtures fall back to whole-image counts, mapping is rule-based and answers are in English.

## Open questions

1. **Refusals and text answers.** The README gives the metric for numbers. How are text answers judged, and is a refusal scored as wrong or skipped? Ask Stoa.
2. **FZK-Haus.** Is `ifc_bench/ac20_arc.ifc` the model the `ifc_models` FZK-Haus plan PDF was rendered from? If so, route those 24 questions to it.
3. **Vision model price.** The endpoint is a dedicated DataCrunch/Verda container (no visible rate limit; the full run fits). Per-token cost depends on its hourly price: set `VLM_PRICE_IN_PER_M` / `VLM_PRICE_OUT_PER_M`, or report cost per image from the hourly price and measured throughput.
4. **Team split.** Who owns the app from step 2, and who owns raster?
5. **Unseen question types.** The one held-out `ifc_models` question ("How many sanitary fixtures…", clinic plumbing model) has no template; train had none like it. Expect more of these in the full set; decide whether the text-model fallback answers them.
6. **Hidden test set.** Does Stoa score on drawings or question phrasings we have not seen? If so, the rule-based mapper needs the text-model fallback switched on for submission.
