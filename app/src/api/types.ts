// Mirrors constructor/schema.py (Element, Drawing, Answer) and API.md exactly.
// Python dataclasses are serialised with asdict(), so every field is present; Optional fields are `| null`.

export type Kind = 'ifc' | 'dxf' | 'pdf' | 'raster' | 'sheet';
export type Unit = 'count' | 'm2' | 'm3' | 'm' | 'text';
export type QuantitySource = 'quantity_set' | 'property' | 'geometry' | 'model_geometry' | 'label' | 'scale' | 'reviewer';
export type Band = 'confirmed' | 'uncertain' | 'dropped';

// schema.py: CONFIRMED_CONF / UNCERTAIN_CONF
export const CONFIRMED_CONF = 0.8;
export const UNCERTAIN_CONF = 0.4;

// SPEC.md, "Data formats": the element types extractors emit.
export const ELEMENT_TYPES = [
  'window',
  'door',
  'wc',
  'sink',
  'shower',
  'bathtub',
  'wall',
  'column',
  'beam',
  'stair',
  'slab',
  'room',
  'apartment',
  'storey',
] as const;
export type ElementType = (typeof ELEMENT_TYPES)[number];

export interface Element {
  id: number;
  type: string; // ElementType in practice; kept open like schema.py
  source: string; // IFC GlobalId, DXF handle, PDF ref, or script / vlm / script+vlm
  exact: boolean;
  conf: number;
  bbox: [number, number, number, number] | null; // [x0, y0, x1, y1] in drawing coordinates
  polygon: [number, number][] | null;
  room_type: string | null;
  label: string | null;
  number: string | null;
  apartment: string | null;
  outdoor: boolean | null;
  quantities: Record<string, number> | null; // area_m2, length_m, side_area_m2, volume_m3
  quantity_source: Record<string, QuantitySource> | null;
  storey: string | null;
  page: number | null;
  /** Doors: hinge, leaf tip open and shut (drawing coordinates), the room it opens into. */
  swing?: Swing | null;
  /** Windows: outward direction, side of the sheet, compass point if north is known, the room it lights. */
  facing?: Facing | null;
}

export interface Swing {
  hinge: [number, number];
  open: [number, number];
  closed: [number, number];
  into: number | null;
  exact: boolean;
}

export interface Facing {
  normal: [number, number];
  sheet: 'top' | 'bottom' | 'left' | 'right';
  compass: string | null;
  room: number | null;
}

export interface Drawing {
  drawing: string;
  kind: Kind;
  extractor_version: string;
  units: string;
  elements: Element[];
  rotation: number;
  extraction_cost_usd: number;
  /** Image plans: metres per pixel and how it was found; sheets: their title block. */
  scale?: { m_per_px?: number; rel_err?: number; source?: string } | null;
}

export interface Answer {
  template: string | null;
  value: number | string | null;
  unit: Unit | null;
  exact: boolean;
  params: Record<string, unknown>;
  range: [number, number] | null;
  evidence_ids: number[];
  uncertain_ids: number[];
  cost_usd: number;
  fallback: boolean;
}

// ---- API.md shapes ----

export type DrawingStatus = 'ready' | 'not_extracted' | 'preparing' | 'failed';

export interface DrawingSummary {
  id: string;
  path: string;
  source: string;
  read_from: Kind;
  status: DrawingStatus;
  question_count: number;
  credit: string;
  /** Why extraction failed (status 'failed'), else null. */
  error: string | null;
  /** UX round 2 (API.md): readable name, "source · kind · exact", thumbnail URL or null. */
  title?: string | null;
  subtitle?: string | null;
  thumb_url?: string | null;
}

export interface PlanInfo {
  url: string;
  width: number;
  height: number;
  viewbox: [number, number, number, number]; // [x, y, width, height] in drawing coordinates
  flip_y: boolean;
}

export interface DrawingDetail {
  id: string;
  credit: string;
  /** Default plan: the first storey for IFC, the only plan otherwise. Null when plan_note is set. */
  plan: PlanInfo | null;
  /** IFC only: one plan per storey, each with its own viewbox. Empty otherwise. */
  plans: Record<string, PlanInfo>;
  /** Shown instead of a plan, e.g. NoDerivatives-licensed models. Answers still work. */
  plan_note: string | null;
  storeys: string[];
  sample_questions: string[];
  drawing: Drawing;
}

/** The plan for a storey (IFC) or the drawing's only plan. */
export function planFor(d: DrawingDetail, storey: string | null): PlanInfo | null {
  return (storey && d.plans[storey]) || d.plan;
}

/** POST /api/ask response: the Answer plus a ready-made sentence. */
export interface AskResponse extends Answer {
  text: string;
  /** True only when model prices are configured on the server; otherwise cost_usd is not a real figure. */
  cost_known?: boolean;
}

export type ReviewAction = 'accept' | 'reject' | 'retype' | 'add' | 'reshape';

export interface Review {
  id: number;
  action: ReviewAction;
  type?: string;
  /** "add" and "reshape": box in drawing coordinates (or an outline), and for added rooms their use and name. */
  bbox?: [number, number, number, number];
  polygon?: [number, number][];
  room_type?: string;
  label?: string;
  storey?: string;
}

/** What the plan view sends to add an element; the server assigns the id. */
export type NewElement = Omit<Review, 'id' | 'action'> & { type: string; bbox: [number, number, number, number] };

/** First id of reviewer-added elements (constructor/reviews.py ADDED_ID_BASE). */
export const ADDED_ID_BASE = 1_000_000;

export function polygonBounds(p: [number, number][]): [number, number, number, number] {
  const xs = p.map((q) => q[0]);
  const ys = p.map((q) => q[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** Area of an outline (or box) in drawing units squared (shoelace). */
function shapeArea(bbox: [number, number, number, number] | null, polygon: [number, number][] | null): number | null {
  if (polygon && polygon.length >= 3) {
    let a = 0;
    for (let i = 0; i < polygon.length; i++) {
      const [x0, y0] = polygon[i];
      const [x1, y1] = polygon[(i + 1) % polygon.length];
      a += x0 * y1 - x1 * y0;
    }
    return Math.abs(a) / 2;
  }
  return bbox ? Math.abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) : null;
}

/**
 * An element with a reviewer's reshape applied, as the server does it (reviews.apply_reviews): a
 * room's area follows its new outline, unless it is printed on the plan. Image plans use their scale
 * and keep its error margin; CAD and IFC areas become the reviewer's outline in metres.
 */
export function reshaped(el: Element, r: Review, drawing?: Pick<Drawing, 'kind' | 'units' | 'scale'>): Element {
  let out = el;
  if (r.polygon) out = { ...el, polygon: r.polygon, bbox: polygonBounds(r.polygon), conf: Math.max(el.conf, 1) };
  else if (r.bbox) out = { ...el, bbox: r.bbox, polygon: null, conf: Math.max(el.conf, 1) };
  if (!drawing || (el.type !== 'room' && el.type !== 'apartment') || el.quantity_source?.area_m2 === 'label') return out;
  const px = shapeArea(out.bbox, out.polygon);
  if (px == null) return out;
  const scale = drawing.scale;
  if (drawing.kind === 'raster' && scale?.m_per_px) {
    const area = px * scale.m_per_px ** 2;
    return {
      ...out,
      quantities: { ...out.quantities, area_m2: Math.round(area * 100) / 100, area_m2_err: Math.round(area * (scale.rel_err ?? 0.3) * 100) / 100 },
      quantity_source: { ...out.quantity_source, area_m2: 'scale' },
    };
  }
  if ((drawing.kind === 'ifc' || drawing.kind === 'dxf') && drawing.units === 'm') {
    const { area_m2_err: _, ...rest } = out.quantities ?? {};
    return { ...out, quantities: { ...rest, area_m2: Math.round(px * 1000) / 1000 }, quantity_source: { ...out.quantity_source, area_m2: 'reviewer' } };
  }
  return out;
}

/** One verdict (accept/reject/retype) and one reshape per element, kept apart. */
export function reviewGroup(r: Pick<Review, 'action'>): string {
  return r.action === 'accept' || r.action === 'reject' || r.action === 'retype' ? 'verdict' : r.action;
}

/** A reviewer's addition, as an element the plan and callouts can show. */
export function addedElement(r: Review): Element {
  return {
    id: r.id,
    type: r.type ?? 'door',
    source: 'added by you',
    exact: false,
    conf: 1,
    bbox: r.polygon ? polygonBounds(r.polygon) : (r.bbox ?? null),
    polygon: r.polygon ?? null,
    room_type: r.room_type ?? null,
    label: r.label ?? null,
    number: null,
    apartment: null,
    outdoor: null,
    quantities: null,
    quantity_source: null,
    storey: r.storey ?? null,
    page: null,
  };
}

export function band(conf: number): Band {
  if (conf >= CONFIRMED_CONF) return 'confirmed';
  if (conf >= UNCERTAIN_CONF) return 'uncertain';
  return 'dropped';
}

// ---- API.md, "Overview, suggestions, thumbnails (UX round 2)" ----

export interface OverviewFact {
  key: string;
  label: string;
  question: string;
  answer: AskResponse;
}

export interface OverviewRoom {
  id: number;
  label: string | null;
  number: string | null;
  type?: string;
  room_type: string | null;
  area_m2: number | null;
  storey: string | null;
  apartment?: string | null;
  exact: boolean;
  /** False when the room is only a small box around its label (raster), not a real outline. */
  has_area?: boolean;
}

export interface Overview {
  kind: Kind;
  exact: boolean;
  facts: OverviewFact[];
  rooms: OverviewRoom[];
  /** Technical sheets: what the title block says. */
  sheet?: { sheet_id?: string; title?: string; discipline?: string; printed?: string; units?: string; summary?: string } | null;
}
