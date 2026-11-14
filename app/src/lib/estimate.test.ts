import { describe, expect, it } from 'vitest';
import { applyReviews, countAnswer, roundHalfUp } from './estimate';
import type { Drawing, Element } from '../api/types';

const win = (id: number, conf: number, exact = false): Element => ({
  id, type: 'window', source: 'script+vlm', exact, conf, bbox: [0, 0, 1, 1], polygon: null, room_type: null,
  label: null, number: null, apartment: null, outdoor: null, quantities: null, quantity_source: null, storey: null, page: null,
});

const spec = [...Array.from({ length: 12 }, (_, i) => win(i + 1, 0.9)), win(13, 0.6), win(14, 0.5), win(15, 0.3)];

describe('estimate maths (SPEC.md)', () => {
  it('12 confirmed + 0.6 + 0.5 uncertain = 13, range 12 to 14; 0.3 dropped', () => {
    const a = countAnswer(spec, 'count_elements', { element: 'window' });
    expect(a.value).toBe(13);
    expect(a.range).toEqual([12, 14]);
    expect(a.exact).toBe(false);
    expect(a.evidence_ids).toHaveLength(12);
    expect(a.uncertain_ids).toEqual([13, 14]);
  });
  it('rounds half up like the backend, not banker style', () => {
    expect(roundHalfUp(0.5)).toBe(1);
    expect(roundHalfUp(2.5)).toBe(3);
    expect(roundHalfUp(1.1)).toBe(1);
  });
  it('is exact with no range when every element is exact and confirmed', () => {
    const a = countAnswer([win(1, 1, true), win(2, 1, true)], 'count_elements', { element: 'window' });
    expect(a).toMatchObject({ value: 2, exact: true, range: null });
  });
  it('reviews: accept confirms, reject drops, retype changes type', () => {
    const d: Drawing = { drawing: 'x', kind: 'raster', extractor_version: 't', units: 'px', elements: spec, rotation: 0, extraction_cost_usd: 0 };
    const r = applyReviews(d, [
      { id: 13, action: 'accept' },
      { id: 14, action: 'reject' },
      { id: 1, action: 'retype', type: 'door' },
    ]);
    const a = countAnswer(r.elements.filter((e) => e.type === 'window'), 'count_elements', { element: 'window' });
    expect(a.value).toBe(12); // 11 original confirmed + accepted 13
    expect(a.range).toEqual([12, 12]); // still an estimate: pixel elements are never exact
    expect(a.uncertain_ids).toEqual([]);
  });
});
