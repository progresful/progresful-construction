import type { Answer, DrawingSummary, Element, Kind } from '../api/types';

export function fileName(path: string): string {
  return path.split('/').pop() ?? path;
}

export function sourceLabel(source: string): string {
  return (
    {
      challenge: 'Challenge sheets',
      cubicasa5k: 'CubiCasa5K',
      swiss_dwellings: 'Swiss Dwellings',
      ifc_models: 'IFC models',
      ifc_bench: 'IFC-Bench',
      opening_design: 'OpeningDesign',
    }[source] ?? source
  );
}

export function unitLabel(unit: Answer['unit']): string {
  return { m2: 'm²', m3: 'm³', m: 'm', count: '', text: '' }[unit ?? 'text'] ?? '';
}

const PLURAL: Record<string, string> = {
  window: 'windows',
  door: 'doors',
  wc: 'WCs',
  sink: 'sinks',
  shower: 'showers',
  bathtub: 'bathtubs',
  wall: 'walls',
  column: 'columns',
  beam: 'beams',
  stair: 'stairs',
  slab: 'slabs',
  room: 'rooms',
  apartment: 'apartments',
  storey: 'storeys',
};

/** What a count is counting, for the unit slot of the card ("windows", "bedrooms", ...). */
export function countNoun(a: Answer): string {
  if (a.template === 'analyst') return typeof a.params.noun === 'string' ? a.params.noun : '';
  if (a.template === 'count_storeys') return 'storeys';
  if (a.template === 'count_rooms') {
    const rt = a.params.room_type;
    return typeof rt === 'string' ? `${rt.replace(/_/g, ' ')}s` : 'rooms';
  }
  const el = a.params.element;
  return typeof el === 'string' ? (PLURAL[el] ?? `${el}s`) : '';
}

export function formatValue(a: Answer): string {
  if (a.value == null) return '';
  if (typeof a.value === 'string') return a.value;
  if (a.unit === 'count') return String(a.value);
  return a.value.toLocaleString('en-GB', { maximumFractionDigits: 3 });
}

export function formatCost(usd: number): string {
  if (usd === 0) return '$0';
  if (usd < 0.01) return `$${usd.toPrecision(2)}`;
  return `$${usd.toFixed(3)}`;
}

export function formatParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ');
}

export function statusLabel(s: DrawingSummary['status']): string {
  return { ready: 'Ready', not_extracted: 'Not extracted', preparing: 'Preparing', failed: 'Not available yet' }[s];
}

/** Where an element came from, in plain words for the hover tooltip. */
export function provenance(el: Element, kind: Kind): string {
  if (el.source.startsWith('added by')) return 'added by you';
  if (el.exact) {
    return kind === 'ifc' ? 'from the IFC model' : kind === 'dxf' ? 'from the CAD file' : kind === 'pdf' ? 'from the PDF text' : 'from model data';
  }
  if (kind === 'raster') return 'detected in the image';
  if (kind === 'sheet') return 'read from the sheet, tile by tile';
  if (kind === 'dxf') return 'rebuilt from CAD lines';
  return 'derived from the drawing';
}

export function areaProvenance(src: string | undefined): string {
  return src === 'quantity_set' ? 'from model data' : src === 'model_geometry' ? "computed from the model's geometry" : src === 'property' ? 'recorded in the model' : src === 'label' ? 'printed on the plan' : src === 'geometry' ? 'computed from the outline' : src === 'scale' ? 'measured on the image, estimated scale' : src === 'reviewer' ? 'from the outline you drew' : '';
}

export function drawingTitle(d: DrawingSummary): string {
  return d.title || fileName(d.path);
}

export function drawingSubtitle(d: DrawingSummary): string {
  return d.subtitle || `${sourceLabel(d.source)} · ${d.read_from.toUpperCase()}`;
}

export function roomName(r: { label: string | null; number: string | null; room_type?: string | null }): string {
  const name = r.label || (r.room_type ? r.room_type.replace(/_/g, ' ') : 'Room');
  return r.number && !name.includes(r.number) ? `${name} ${r.number}` : name;
}

/** "likely between X and Y", only for a real interval (X < Y); never "10 to 10". */
export function rangeText(a: Pick<Answer, 'range'>): string | null {
  if (!a.range || !(a.range[0] < a.range[1])) return null;
  const f = (n: number) => n.toLocaleString('en-GB', { maximumFractionDigits: 3 });
  return `likely between ${f(a.range[0])} and ${f(a.range[1])}`;
}
