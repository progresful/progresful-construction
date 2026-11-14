// Fictional drawings for the mock API. Nothing here is copied from data/ (dataset licences are
// non-commercial); plans are generated SVGs drawn from the same geometry as the elements.
import type { Drawing, DrawingDetail, DrawingSummary, Element, PlanInfo } from './types';
import { toPixels } from '../lib/geometry';

type Box = [number, number, number, number];

function el(partial: Partial<Element> & Pick<Element, 'id' | 'type' | 'source' | 'exact'>): Element {
  return {
    conf: 1.0,
    bbox: null,
    polygon: null,
    room_type: null,
    label: null,
    number: null,
    apartment: null,
    outdoor: null,
    quantities: null,
    quantity_source: null,
    storey: null,
    page: null,
    ...partial,
  };
}

function rect([x0, y0, x1, y1]: Box): [number, number][] {
  return [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
}

/** Deterministic IFC-GlobalId-looking strings (22 chars of the IFC base64 alphabet). */
function guid(seed: number): string {
  const abc = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$';
  let s = seed * 2654435761;
  let out = '';
  for (let i = 0; i < 22; i++) {
    s = (s * 1103515245 + 12345) % 2147483648;
    out += abc[s % 64];
  }
  return out;
}

const svgUrl = (svg: string) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

// ---------------------------------------------------------------------------------------------
// 1. IFC-style model: two storeys, metres, y up (flip_y = true). Exact answers.
// ---------------------------------------------------------------------------------------------

const IFC_PLAN: PlanInfo = { url: '', width: 1400, height: 1100, viewbox: [-1, -1, 14, 11], flip_y: true };

interface RoomSpec {
  box: Box;
  label: string;
  number: string;
  area: number;
  room_type: string;
}
interface StoreySpec {
  name: string;
  rooms: RoomSpec[];
  windows: Box[];
  doors: Box[];
}

const IFC_STOREYS: StoreySpec[] = [
  {
    name: 'Ground floor',
    rooms: [
      { box: [0, 0, 7, 5], label: 'Living room', number: '0.01', area: 33.62, room_type: 'living_room' },
      { box: [7, 0, 12, 5], label: 'Kitchen', number: '0.02', area: 23.86, room_type: 'kitchen' },
      { box: [0, 5, 4, 9], label: 'Entrance hall', number: '0.03', area: 15.21, room_type: 'hall' },
      { box: [4, 5, 7, 9], label: 'Bathroom', number: '0.04', area: 11.06, room_type: 'bathroom' },
      { box: [7, 5, 12, 9], label: 'Study', number: '0.05', area: 19.18, room_type: 'office' },
    ],
    windows: [
      [1.0, -0.15, 2.6, 0.15],
      [4.0, -0.15, 5.6, 0.15],
      [8.2, -0.15, 9.8, 0.15],
      [11.85, 1.6, 12.15, 3.2],
      [11.85, 6.2, 12.15, 7.8],
      [8.6, 8.85, 10.4, 9.15],
      [5.0, 8.85, 6.0, 9.15],
      [-0.15, 1.6, 0.15, 3.4],
    ],
    doors: [
      [1.5, 8.85, 2.5, 9.15],
      [2.0, 4.85, 3.0, 5.15],
      [3.85, 6.5, 4.15, 7.4],
      [6.85, 1.8, 7.15, 2.8],
      [7.6, 4.85, 8.5, 5.15],
    ],
  },
  {
    name: 'First floor',
    rooms: [
      { box: [0, 0, 6, 5], label: 'Bedroom 1', number: '1.01', area: 28.74, room_type: 'bedroom' },
      { box: [6, 0, 12, 5], label: 'Bedroom 2', number: '1.02', area: 28.74, room_type: 'bedroom' },
      { box: [0, 5, 5, 9], label: 'Bathroom', number: '1.03', area: 19.0, room_type: 'bathroom' },
      { box: [5, 5, 12, 9], label: 'Landing', number: '1.04', area: 26.95, room_type: 'hall' },
    ],
    windows: [
      [1.4, -0.15, 3.4, 0.15],
      [8.4, -0.15, 10.4, 0.15],
      [-0.15, 6.0, 0.15, 7.6],
      [11.85, 6.3, 12.15, 7.7],
      [7.6, 8.85, 9.4, 9.15],
      [11.85, 1.6, 12.15, 3.2],
    ],
    doors: [
      [2.0, 4.85, 3.0, 5.15],
      [8.0, 4.85, 9.0, 5.15],
      [4.85, 6.4, 5.15, 7.3],
    ],
  },
];

function buildIfcDrawing(path: string): Drawing {
  const elements: Element[] = [];
  let id = 1;
  for (const s of IFC_STOREYS) {
    elements.push(el({ id: id++, type: 'storey', source: guid(id), exact: true, label: s.name, storey: s.name }));
    for (const r of s.rooms) {
      elements.push(
        el({
          id: id++,
          type: 'room',
          source: guid(id),
          exact: true,
          polygon: rect(r.box),
          label: r.label,
          number: r.number,
          room_type: r.room_type,
          outdoor: false,
          quantities: { area_m2: r.area },
          quantity_source: { area_m2: 'quantity_set' },
          storey: s.name,
        }),
      );
    }
    for (const w of s.windows) elements.push(el({ id: id++, type: 'window', source: guid(id), exact: true, bbox: w, storey: s.name }));
    for (const d of s.doors) elements.push(el({ id: id++, type: 'door', source: guid(id), exact: true, bbox: d, storey: s.name }));
  }
  return { drawing: path, kind: 'ifc', extractor_version: 'ifc-0.3', units: 'm', elements, rotation: 0, extraction_cost_usd: 0 };
}

function ifcPlanSvg(storey: string): string {
  const s = IFC_STOREYS.find((x) => x.name === storey) ?? IFC_STOREYS[0];
  const P = (x: number, y: number) => toPixels(IFC_PLAN, x, y);
  const R = (b: Box) => {
    const [ax, ay] = P(b[0], b[1]);
    const [bx, by] = P(b[2], b[3]);
    return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) };
  };
  const parts: string[] = [];
  parts.push(`<rect width="1400" height="1100" fill="#ffffff"/>`);
  // grid
  for (let x = -1; x <= 13; x++) {
    const [px] = P(x, 0);
    parts.push(`<line x1="${px}" y1="0" x2="${px}" y2="1100" stroke="#eef1f5" stroke-width="1"/>`);
  }
  for (let y = -1; y <= 10; y++) {
    const [, py] = P(0, y);
    parts.push(`<line x1="0" y1="${py}" x2="1400" y2="${py}" stroke="#eef1f5" stroke-width="1"/>`);
  }
  for (const r of s.rooms) {
    const q = R(r.box);
    parts.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="none" stroke="#2b2f36" stroke-width="10"/>`);
  }
  const outer = R([0, 0, 12, 9]);
  parts.push(`<rect x="${outer.x}" y="${outer.y}" width="${outer.w}" height="${outer.h}" fill="none" stroke="#2b2f36" stroke-width="30"/>`);
  for (const w of s.windows) {
    const q = R(w);
    parts.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="#fff" stroke="#2b2f36" stroke-width="2"/>`);
    if (q.w > q.h) parts.push(`<line x1="${q.x}" y1="${q.y + q.h / 2}" x2="${q.x + q.w}" y2="${q.y + q.h / 2}" stroke="#2b2f36" stroke-width="2"/>`);
    else parts.push(`<line x1="${q.x + q.w / 2}" y1="${q.y}" x2="${q.x + q.w / 2}" y2="${q.y + q.h}" stroke="#2b2f36" stroke-width="2"/>`);
  }
  for (const d of s.doors) {
    const q = R(d);
    parts.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="#fff"/>`);
    const L = Math.max(q.w, q.h);
    if (q.w > q.h) parts.push(`<path d="M${q.x} ${q.y + q.h / 2} l0 ${-L} A${L} ${L} 0 0 1 ${q.x + L} ${q.y + q.h / 2}" fill="none" stroke="#5b6472" stroke-width="2"/>`);
    else parts.push(`<path d="M${q.x + q.w / 2} ${q.y} l${L} 0 A${L} ${L} 0 0 1 ${q.x + q.w / 2} ${q.y + L}" fill="none" stroke="#5b6472" stroke-width="2"/>`);
  }
  for (const r of s.rooms) {
    const q = R(r.box);
    const cx = q.x + q.w / 2;
    const cy = q.y + q.h / 2;
    parts.push(
      `<text x="${cx}" y="${cy - 6}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="26" fill="#2b2f36">${esc(r.label)}</text>`,
      `<text x="${cx}" y="${cy + 26}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="#5b6472">${r.number} · ${r.area.toFixed(2)} m²</text>`,
    );
  }
  parts.push(
    `<text x="40" y="1070" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#5b6472">${esc(s.name)} · section cut at +1.20 m · placeholder model (mock)</text>`,
  );
  // scale bar: 2 m
  const [sx0, sy] = P(9.5, -0.75);
  const [sx1] = P(11.5, -0.75);
  parts.push(`<line x1="${sx0}" y1="${sy}" x2="${sx1}" y2="${sy}" stroke="#2b2f36" stroke-width="4"/>`);
  parts.push(`<text x="${(sx0 + sx1) / 2}" y="${sy - 10}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="18" fill="#2b2f36">2 m</text>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1100" viewBox="0 0 1400 1100">${parts.join('')}</svg>`;
}

// ---------------------------------------------------------------------------------------------
// 2. Raster CubiCasa-style plan: pixels, y down. Estimates with confirmed and uncertain marks.
// ---------------------------------------------------------------------------------------------

const RASTER_PLAN: PlanInfo = { url: '', width: 1000, height: 720, viewbox: [0, 0, 1000, 720], flip_y: false };

const RASTER_ROOMS: { box: Box; label: string; room_type: string; area: number; outdoor?: boolean; fill: string }[] = [
  { box: [60, 60, 480, 380], label: 'OH', room_type: 'living_room', area: 27.5, fill: '#f6e7c8' },
  { box: [480, 60, 700, 380], label: 'K', room_type: 'kitchen', area: 14.0, fill: '#f3d9d2' },
  { box: [700, 60, 940, 380], label: 'MH', room_type: 'bedroom', area: 15.5, fill: '#dbe8f4' },
  { box: [60, 380, 340, 640], label: 'MH', room_type: 'bedroom', area: 14.5, fill: '#dbe8f4' },
  { box: [340, 380, 560, 640], label: 'ET', room_type: 'hall', area: 11.0, fill: '#ececec' },
  { box: [560, 380, 740, 640], label: 'KH', room_type: 'bathroom', area: 9.0, fill: '#d6efe9' },
  { box: [740, 380, 940, 520], label: 'S', room_type: 'sauna', area: 5.5, fill: '#efe1cf' },
  { box: [740, 520, 940, 640], label: 'WC', room_type: 'toilet', area: 4.5, fill: '#d6efe9' },
  { box: [60, 640, 340, 700], label: 'PARV', room_type: 'balcony', area: 3.5, outdoor: true, fill: '#f4f4f4' },
];

// [bbox, conf]. 12 confirmed + 0.6 + 0.5 uncertain + one dropped (0.3) => 13 (12 to 14).
const RASTER_WINDOWS: [Box, number][] = [
  [[120, 56, 200, 64], 0.94],
  [[300, 56, 380, 64], 0.92],
  [[540, 56, 620, 64], 0.9],
  [[760, 56, 840, 64], 0.9],
  [[860, 56, 920, 64], 0.88],
  [[56, 150, 64, 230], 0.91],
  [[56, 260, 64, 340], 0.9],
  [[56, 440, 64, 520], 0.9],
  [[936, 140, 944, 220], 0.93],
  [[936, 260, 944, 340], 0.9],
  [[100, 636, 180, 644], 0.86],
  [[600, 636, 680, 644], 0.9],
  [[936, 420, 944, 470], 0.6],
  [[800, 636, 860, 644], 0.5],
  [[476, 100, 484, 150], 0.3],
];

const RASTER_DOORS: [Box, number][] = [
  [[400, 636, 470, 644], 0.92],
  [[336, 440, 344, 500], 0.88],
  [[556, 450, 564, 510], 0.85],
  [[476, 250, 484, 310], 0.9],
  [[380, 376, 440, 384], 0.95],
  [[736, 560, 744, 610], 0.9],
  [[696, 250, 704, 310], 0.65],
  [[736, 420, 744, 470], 0.7],
  [[240, 636, 300, 644], 0.55],
];

const RASTER_FIXTURES: [string, Box, number][] = [
  ['wc', [880, 560, 920, 610], 0.9],
  ['sink', [580, 396, 630, 426], 0.85],
  ['sink', [600, 66, 660, 96], 0.7],
  ['shower', [680, 575, 734, 634], 0.9],
];

function buildRasterDrawing(path: string): Drawing {
  const elements: Element[] = [];
  let id = 1;
  elements.push(el({ id: id++, type: 'storey', source: 'vlm', exact: false, conf: 0.95, label: '1. krs' }));
  for (const r of RASTER_ROOMS) {
    elements.push(
      el({
        id: id++,
        type: 'room',
        source: 'script+vlm',
        exact: false,
        conf: r.label === 'PARV' ? 0.7 : 0.92,
        polygon: rect(r.box),
        label: r.label,
        room_type: r.room_type,
        outdoor: r.outdoor ?? false,
        quantities: { area_m2: r.area },
        quantity_source: { area_m2: 'label' },
      }),
    );
  }
  for (const [b, c] of RASTER_WINDOWS) elements.push(el({ id: id++, type: 'window', source: 'script+vlm', exact: false, conf: c, bbox: b }));
  for (const [b, c] of RASTER_DOORS) elements.push(el({ id: id++, type: 'door', source: 'script+vlm', exact: false, conf: c, bbox: b }));
  for (const [t, b, c] of RASTER_FIXTURES) elements.push(el({ id: id++, type: t, source: c >= 0.8 ? 'script+vlm' : 'script', exact: false, conf: c, bbox: b }));
  return { drawing: path, kind: 'raster', extractor_version: 'raster-0.1', units: 'px', elements, rotation: 0, extraction_cost_usd: 0.004 };
}

function rasterPlanSvg(): string {
  const p: string[] = [`<rect width="1000" height="720" fill="#fbfaf7"/>`];
  for (const r of RASTER_ROOMS) {
    const [x0, y0, x1, y1] = r.box;
    p.push(`<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="${r.fill}" stroke="#222" stroke-width="${r.outdoor ? 2 : 5}"/>`);
  }
  p.push(`<rect x="60" y="60" width="880" height="580" fill="none" stroke="#222" stroke-width="12"/>`);
  // windows that are really drawn (the 0.3 candidate is a false positive: nothing there)
  for (const [[x0, y0, x1, y1], c] of RASTER_WINDOWS) {
    if (c < 0.4) continue;
    p.push(`<rect x="${x0}" y="${y0 - 2}" width="${x1 - x0}" height="${y1 - y0 + 4}" fill="#fff" stroke="#222" stroke-width="1.5"/>`);
    if (x1 - x0 > y1 - y0) p.push(`<line x1="${x0}" y1="${(y0 + y1) / 2}" x2="${x1}" y2="${(y0 + y1) / 2}" stroke="#222" stroke-width="1.5"/>`);
    else p.push(`<line x1="${(x0 + x1) / 2}" y1="${y0}" x2="${(x0 + x1) / 2}" y2="${y1}" stroke="#222" stroke-width="1.5"/>`);
  }
  for (const [[x0, y0, x1, y1]] of RASTER_DOORS) {
    p.push(`<rect x="${x0}" y="${y0 - 2}" width="${x1 - x0}" height="${y1 - y0 + 4}" fill="#fbfaf7"/>`);
    const L = Math.max(x1 - x0, y1 - y0);
    if (x1 - x0 > y1 - y0) p.push(`<path d="M${x0} ${(y0 + y1) / 2} l0 ${-L} A${L} ${L} 0 0 1 ${x0 + L} ${(y0 + y1) / 2}" fill="none" stroke="#444" stroke-width="1.5"/>`);
    else p.push(`<path d="M${(x0 + x1) / 2} ${y0} l${L} 0 A${L} ${L} 0 0 1 ${(x0 + x1) / 2} ${y0 + L}" fill="none" stroke="#444" stroke-width="1.5"/>`);
  }
  // fixtures
  p.push(`<ellipse cx="900" cy="585" rx="16" ry="22" fill="#fff" stroke="#333" stroke-width="2"/>`);
  p.push(`<rect x="580" y="396" width="50" height="30" rx="6" fill="#fff" stroke="#333" stroke-width="2"/>`);
  p.push(`<rect x="600" y="66" width="60" height="30" rx="4" fill="#fff" stroke="#333" stroke-width="1.5"/>`);
  p.push(`<rect x="680" y="575" width="54" height="59" fill="#fff" stroke="#333" stroke-width="2"/><path d="M680 575 L734 634 M734 575 L680 634" stroke="#999" stroke-width="1"/>`);
  for (const r of RASTER_ROOMS) {
    const [x0, y0, x1, y1] = r.box;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    p.push(`<text x="${cx}" y="${cy}" text-anchor="middle" font-family="Arial, sans-serif" font-weight="bold" font-size="${r.outdoor ? 14 : 22}" fill="#222">${r.label}</text>`);
    if (!r.outdoor) p.push(`<text x="${cx}" y="${cy + 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="15" fill="#444">${r.area.toFixed(1).replace('.', ',')} m²</text>`);
  }
  p.push(`<text x="960" y="700" text-anchor="end" font-family="Arial, sans-serif" font-size="14" fill="#888">placeholder raster plan (mock)</text>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="720" viewBox="0 0 1000 720">${p.join('')}</svg>`;
}

// ---------------------------------------------------------------------------------------------
// 3. DXF-style apartment floor (Swiss): metres, y up. Windows/doors exact (blocks), rooms rebuilt
//    from polylines (exact: false, areas from geometry) -> area answers are estimates.
// ---------------------------------------------------------------------------------------------

const DXF_PLAN: PlanInfo = { url: '', width: 1200, height: 800, viewbox: [-1, -1, 18, 12], flip_y: true };

const DXF_ROOMS: { box: Box; label: string; number: string; apartment: string; room_type: string }[] = [
  { box: [0, 0, 5, 5], label: 'Wohnen', number: '1', apartment: 'A', room_type: 'living_room' },
  { box: [5, 0, 8, 5], label: 'Küche', number: '2', apartment: 'A', room_type: 'kitchen' },
  { box: [0, 5, 4, 10], label: 'Zimmer', number: '3', apartment: 'A', room_type: 'bedroom' },
  { box: [4, 5, 8, 10], label: 'Bad', number: '4', apartment: 'A', room_type: 'bathroom' },
  { box: [8, 0, 16, 6], label: 'Wohnen', number: '1', apartment: 'B', room_type: 'living_room' },
  { box: [8, 6, 12, 10], label: 'Zimmer', number: '2', apartment: 'B', room_type: 'bedroom' },
  { box: [12, 6, 16, 10], label: 'Bad', number: '3', apartment: 'B', room_type: 'bathroom' },
];
const DXF_WINDOWS: Box[] = [
  [1, -0.15, 3, 0.15],
  [5.5, -0.15, 7, 0.15],
  [9, -0.15, 11.5, 0.15],
  [13, -0.15, 15, 0.15],
  [15.85, 2, 16.15, 4],
  [-0.15, 6.5, 0.15, 8.5],
  [9, 9.85, 11, 10.15],
  [13, 9.85, 14.5, 10.15],
];
const DXF_DOORS: Box[] = [
  [2, 4.85, 3, 5.15],
  [4.85, 2, 5.15, 3],
  [5, 4.85, 6, 5.15],
  [9.5, 5.85, 10.5, 6.15],
  [13, 5.85, 14, 6.15],
  [7.85, 3, 8.15, 4],
];

function buildDxfDrawing(path: string): Drawing {
  const elements: Element[] = [];
  let id = 1;
  const handle = () => (0x1a0 + id * 7).toString(16).toUpperCase();
  for (const r of DXF_ROOMS) {
    const area = (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]) - 0.4;
    elements.push(
      el({
        id: id,
        type: 'room',
        source: handle(),
        exact: false,
        polygon: rect(r.box),
        label: r.label,
        number: r.number,
        apartment: r.apartment,
        room_type: r.room_type,
        outdoor: false,
        quantities: { area_m2: Math.round(area * 100) / 100 },
        quantity_source: { area_m2: 'geometry' },
      }),
    );
    id++;
  }
  for (const w of DXF_WINDOWS) {
    elements.push(el({ id, type: 'window', source: handle(), exact: true, bbox: w }));
    id++;
  }
  for (const d of DXF_DOORS) {
    elements.push(el({ id, type: 'door', source: handle(), exact: true, bbox: d }));
    id++;
  }
  return { drawing: path, kind: 'dxf', extractor_version: 'dxf-0.2', units: 'm', elements, rotation: 0, extraction_cost_usd: 0 };
}

function dxfPlanSvg(): string {
  const P = (x: number, y: number) => toPixels(DXF_PLAN, x, y);
  const R = (b: Box) => {
    const [ax, ay] = P(b[0], b[1]);
    const [bx, by] = P(b[2], b[3]);
    return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) };
  };
  const p: string[] = [`<rect width="1200" height="800" fill="#ffffff"/>`];
  for (const r of DXF_ROOMS) {
    const q = R(r.box);
    p.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="none" stroke="#111" stroke-width="5"/>`);
  }
  const o = R([0, 0, 16, 10]);
  p.push(`<rect x="${o.x}" y="${o.y}" width="${o.w}" height="${o.h}" fill="none" stroke="#111" stroke-width="16"/>`);
  for (const w of DXF_WINDOWS) {
    const q = R(w);
    p.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="#fff" stroke="#111" stroke-width="1.5"/>`);
  }
  for (const d of DXF_DOORS) {
    const q = R(d);
    p.push(`<rect x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" fill="#fff"/>`);
  }
  for (const r of DXF_ROOMS) {
    const q = R(r.box);
    p.push(`<text x="${q.x + q.w / 2}" y="${q.y + q.h / 2}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="#111">${esc(r.label)}</text>`);
    p.push(`<text x="${q.x + q.w / 2}" y="${q.y + q.h / 2 + 22}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="15" fill="#666">${r.apartment}.${r.number}</text>`);
  }
  p.push(`<text x="40" y="780" font-family="Helvetica, Arial, sans-serif" font-size="16" fill="#666">placeholder DXF floor (mock)</text>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">${p.join('')}</svg>`;
}

// ---------------------------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------------------------

export interface MockEntry {
  summary: DrawingSummary;
  /** Built lazily once the drawing is "extracted". */
  build: () => DrawingDetail;
  /** When set, extraction ends in status 'failed' with this error. */
  failWith?: string;
}

const MOCK_NOTE = 'Placeholder plan generated by the app (mock data).';
const CUBICASA = `${MOCK_NOTE} Real plans: CubiCasa5K, (c) 2019 CubiCasa, Kalervo et al., SCIA 2019. CC BY-NC-SA 4.0.`;

function ifcDetail(id: string, path: string, credit: string, noPlan: string | null): DrawingDetail {
  const plans: Record<string, PlanInfo> = {};
  // Each storey gets its own PlanInfo, as the server does (viewboxes may differ per storey).
  if (!noPlan) for (const s of IFC_STOREYS) plans[s.name] = { ...IFC_PLAN, url: svgUrl(ifcPlanSvg(s.name)) };
  return {
    id,
    credit,
    plan: noPlan ? null : plans[IFC_STOREYS[0].name],
    plans,
    plan_note: noPlan,
    storeys: IFC_STOREYS.map((s) => s.name),
    sample_questions: [
      'What is the area of the Kitchen?',
      'How many windows are on the ground floor?',
      'How many storeys does the building have?',
      'What is the total area of the first floor?',
      'Wie viele Türen gibt es?',
    ],
    drawing: buildIfcDrawing(path),
  };
}

export function createMockEntries(): MockEntry[] {
  const ifcCredit = `${MOCK_NOTE} Real IFC models: credit per model, data/ifc_models/LICENSE.md.`;
  const ndCredit = 'Mock NoDerivatives model (CC BY-ND 3.0): no rendered plan may be shown.';
  const swissCredit = `${MOCK_NOTE} Real plans: Swiss Dwellings, CC BY 4.0.`;
  return [
    {
      summary: {
        id: 'ifc_models__demo_house',
        path: 'data/ifc_models/demo_house.ifc',
        source: 'ifc_models',
        read_from: 'ifc',
        status: 'ready',
        question_count: 24,
        credit: ifcCredit,
        error: null,
      },
      build: () => ifcDetail('ifc_models__demo_house', 'data/ifc_models/demo_house.ifc', ifcCredit, null),
    },
    {
      summary: {
        id: 'cubicasa5k__colorful-demo',
        path: 'data/cubicasa5k/colorful-demo.png',
        source: 'cubicasa5k',
        read_from: 'raster',
        status: 'ready',
        question_count: 26,
        credit: CUBICASA,
        error: null,
      },
      build: () => ({
        id: 'cubicasa5k__colorful-demo',
        credit: CUBICASA,
        plan: { ...RASTER_PLAN, url: svgUrl(rasterPlanSvg()) },
        plans: {},
        plan_note: null,
        storeys: [],
        sample_questions: [
          'How many windows are drawn on this floor plan?',
          'Kuinka monta ikkunaa pohjapiirustuksessa on?',
          'How many doors are there?',
          'How many bedrooms are there?',
          'What is the area of the sauna?',
          'Is there a dishwasher?',
        ],
        drawing: buildRasterDrawing('data/cubicasa5k/colorful-demo.png'),
      }),
    },
    {
      summary: {
        id: 'swiss_dwellings__site0001_bldg0001_floor0001',
        path: 'data/swiss_dwellings/site0001_bldg0001_floor0001.pdf',
        source: 'swiss_dwellings',
        read_from: 'dxf',
        status: 'not_extracted',
        question_count: 37,
        credit: swissCredit,
        error: null,
      },
      build: () => ({
        id: 'swiss_dwellings__site0001_bldg0001_floor0001',
        credit: swissCredit,
        plan: { ...DXF_PLAN, url: svgUrl(dxfPlanSvg()) },
        plans: {},
        plan_note: null,
        storeys: [],
        sample_questions: [
          'How many windows are there?',
          'What is the area of apartment B?',
          'Wie viele Zimmer hat die Wohnung A?',
          'Combien de portes y a-t-il ?',
        ],
        drawing: buildDxfDrawing('data/swiss_dwellings/site0001_bldg0001_floor0001.dxf'),
      }),
    },
    {
      summary: {
        id: 'ifc_bench__nd_demo',
        path: 'data/ifc_bench/nd_demo.ifc',
        source: 'ifc_bench',
        read_from: 'ifc',
        status: 'ready',
        question_count: 51,
        credit: ndCredit,
        error: null,
      },
      build: () =>
        ifcDetail(
          'ifc_bench__nd_demo',
          'data/ifc_bench/nd_demo.ifc',
          ndCredit,
          "No plan shown: the file's licence (NoDerivatives) does not allow rendered drawings.",
        ),
    },
    {
      summary: {
        id: 'cubicasa5k__high_quality-demo',
        path: 'data/cubicasa5k/high_quality-demo.png',
        source: 'cubicasa5k',
        read_from: 'raster',
        status: 'not_extracted',
        question_count: 18,
        credit: CUBICASA,
        error: null,
      },
      failWith: 'The raster extractor is not built yet.',
      build: () => {
        throw new Error('not extracted');
      },
    },
  ];
}
