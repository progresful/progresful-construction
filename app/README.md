# Constructor app

React + TypeScript + Vite web UI for Constructor: a drawing list, the plan with an evidence overlay, and a
question box with answer cards. It talks to the Python server through the contract in [`../API.md`](../API.md).

## Run

```sh
cd app
npm install

npm run dev:mock     # mock API only (VITE_MOCK=1), no backend needed
npm run dev          # real API: Vite proxies /api to http://localhost:8000;
                     # falls back to the mock automatically if /api/drawings is unreachable
VITE_MOCK=0 npm run dev   # real API only, never fall back
```

Open http://localhost:5173. The header pill says **Mock data** or **Live API** (hover it for the reason).

```sh
npm run typecheck    # tsc --noEmit
npm test             # vitest: coordinate transform (flip_y / viewbox) and estimate maths
npm run build        # typecheck + production build into dist/
```

## Layout

| Path | What |
|---|---|
| `src/api/types.ts` | Element / Drawing / Answer mirrored from `constructor/schema.py`, plus the API.md shapes |
| `src/api/client.ts` | `Api` interface, real HTTP client, `connect()` that picks real or mock |
| `src/api/mock.ts`, `mockData.ts` | In-memory mock: generated placeholder plans (IFC two storeys, CubiCasa-style raster, Swiss-style DXF), keyword question mapper, reviews, extraction |
| `src/lib/geometry.ts` | Drawing coordinates to overlay (viewbox, flip_y), fit and zoom maths |
| `src/lib/estimate.ts` | Estimate maths and review application (mirrors `templates.py` / `reviews.py`; mock only) |
| `src/lib/marks.ts` | Which elements to draw for an answer, and how |
| `src/components/` | `DrawingList`, `PlanView` (image + overlay + pan/zoom), `PlanOverlay`, `AnswerCard`, `QuestionBox`, `OverviewPanel`, `ReviewPopover` |

Beyond API.md the app uses the server's `credit`, `plans` (per-storey PlanInfo, each with its own viewbox),
`plan_note` (shown instead of the plan, e.g. NoDerivatives models), list-item `error` and status `failed`, and
FastAPI `{"detail": ...}` errors. The mock follows the same shapes.

Mock plans are generated SVGs. Nothing from `data/` is copied into the app (dataset licences are non-commercial).

## Using it

- **Overview** (default when a drawing opens): facts from `GET /overview` as a compact grid (click one to open its answer
  card and evidence, without re-asking) and a rooms table (hover or click a row to find the room on the plan).
- **Ask**: Enter asks, Shift+Enter is a newline; suggestions come from `GET /suggestions`. Cards appear immediately with a
  skeleton and fill in; template, params and cost sit under "Details". Esc clears the active card.
- **Zoom to evidence**: the active card frames its evidence (capped at 2.5x the fit scale; IFC switches storey). "Fit plan"
  returns to the whole drawing.
- **Plan**: wheel to zoom at the cursor, drag to pan, **Fit** to reset. IFC drawings get a storey selector.
- **Evidence**: the active card's `evidence_ids` are solid, `uncertain_ids` dashed. Green for exact, amber for estimates.
  "Show all elements" draws the rest lightly (rejected marks red dashed). Hover any mark for type, label, id, source, conf.
- **Review** (estimates only): click a mark, then Accept / Reject / Retype. The app POSTs the review, re-asks the card's
  question and updates the card in place. Accepted and retyped marks turn solid green; the card counts reviewed marks.
