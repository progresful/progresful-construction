import type { DrawingSummary, Kind } from '../api/types';

/** Drawing-register number: a short code per dataset plus the drawing's own number. */
export function dwgNo(d: Pick<DrawingSummary, 'path' | 'source'> & { title?: string | null }): string {
  const stem = (d.path.split('/').pop() ?? d.path).replace(/\.[^.]+$/, '');
  if (d.source === 'challenge') return d.title?.match(/\(([A-Z]+-[\w.]+)\)/)?.[1] ?? 'CH';
  if (d.source === 'cubicasa5k') return `CC-${stem.split('-').pop()}`;
  const swiss = stem.match(/site(\d+)_bldg(\d+)_floor(-?\d+)/);
  if (swiss) return `SD-${swiss[1]}-${swiss[2]}-${swiss[3]}`;
  const prefix = { ifc_models: 'IFC', ifc_bench: 'IB', opening_design: 'OD' }[d.source] ?? d.source.slice(0, 3).toUpperCase();
  const plan = stem.match(/_plan-(\d+)/);
  const short = stem
    .replace(/_plan-.*/, '')
    .split(/[_-]/)
    .filter((w) => /[a-z]/i.test(w))
    .slice(0, 2)
    .map((w) => w.slice(0, 4).toUpperCase())
    .join('-');
  return `${prefix}-${short}${plan ? `-P${plan[1]}` : ''}`;
}

/** The file format the answers are read from, as a drawing office would say it. */
export function formatName(kind: Kind): string {
  return { ifc: 'IFC model', dxf: 'CAD (DXF)', pdf: 'PDF sheet', raster: 'Scanned image', sheet: 'Technical sheet' }[kind] ?? kind;
}

/** Whether answers from this format are exact. */
export function basis(kind: Kind): 'exact' | 'estimate' | 'text' {
  return kind === 'ifc' || kind === 'dxf' ? 'exact' : kind === 'pdf' ? 'text' : 'estimate';
}

export function today(): string {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
}
