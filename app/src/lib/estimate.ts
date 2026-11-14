// Estimate maths from SPEC.md, mirrored from constructor/templates.py (count) and
// constructor/reviews.py (apply_reviews). Used by the mock API only; the real server owns this.
import type { Answer, Drawing, Element, Review } from '../api/types';
import { band } from '../api/types';

/** Python's round() is banker's rounding; the backend uses floor(x + 0.5). */
export function roundHalfUp(x: number): number {
  return Math.floor(x + 0.5);
}

export function applyReviews(drawing: Drawing, reviews: Review[]): Drawing {
  const byId = new Map(reviews.map((r) => [r.id, r]));
  const elements: Element[] = [];
  for (const el of drawing.elements) {
    const r = byId.get(el.id);
    if (!r) elements.push(el);
    else if (r.action === 'accept') elements.push({ ...el, conf: 1.0 });
    else if (r.action === 'retype') elements.push({ ...el, conf: 1.0, type: r.type ?? el.type });
    // reject drops the element
  }
  return { ...drawing, elements };
}

/**
 * value = confirmed + round(sum of conf over uncertain), range = [confirmed, confirmed + uncertain].
 * Exact only when nothing is uncertain and every confirmed element is exact.
 */
export function countAnswer(elements: Element[], template: string, params: Record<string, unknown>): Answer {
  const kept = elements.filter((e) => band(e.conf) !== 'dropped');
  const confirmed = kept.filter((e) => band(e.conf) === 'confirmed');
  const uncertain = kept.filter((e) => band(e.conf) === 'uncertain');
  const exact = uncertain.length === 0 && confirmed.every((e) => e.exact);
  return {
    template,
    params,
    value: confirmed.length + roundHalfUp(uncertain.reduce((s, e) => s + e.conf, 0)),
    unit: 'count',
    exact,
    range: exact ? null : [confirmed.length, confirmed.length + uncertain.length],
    evidence_ids: confirmed.map((e) => e.id),
    uncertain_ids: uncertain.map((e) => e.id),
    cost_usd: 0,
    fallback: false,
  };
}

/** Sum a quantity; exact only if every value was read (quantity set or printed label), not computed. */
export function sumAnswer(
  elements: Element[],
  key: string,
  unit: 'm2' | 'm3' | 'm',
  template: string,
  params: Record<string, unknown>,
): Answer | null {
  const kept = elements.filter((e) => band(e.conf) !== 'dropped');
  const values = kept.map((e) => e.quantities?.[key]);
  if (!kept.length || values.some((v) => v == null)) return null;
  const exact = kept.every((e) => e.exact && ['quantity_set', 'label'].includes(e.quantity_source?.[key] ?? ''));
  const total = values.reduce<number>((s, v) => s + (v as number), 0);
  return {
    template,
    params,
    value: Math.round(total * 1000) / 1000,
    unit,
    exact,
    range: null,
    evidence_ids: kept.filter((e) => band(e.conf) === 'confirmed').map((e) => e.id),
    uncertain_ids: kept.filter((e) => band(e.conf) === 'uncertain').map((e) => e.id),
    cost_usd: 0,
    fallback: false,
  };
}
