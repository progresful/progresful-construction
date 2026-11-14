import type { Answer, Element, Review } from '../api/types';

export type MarkRole = 'evidence' | 'uncertain' | 'highlight' | 'other' | 'rejected' | 'ghost';

export interface Mark {
  el: Element;
  role: MarkRole;
  review: Review | null;
}

/**
 * Which elements to draw and how:
 * - evidence_ids solid, uncertain_ids dashed (accepted/retyped ones are drawn solid too),
 * - `highlight` ids (rooms picked in the overview table) in the accent colour,
 * - everything else only when `showAll`, lightly; rejected ones only when `showAll`;
 * - otherwise as invisible `ghost`s that show on hover and open their details on click.
 * Elements without geometry and storey markers are never drawn.
 */
const GHOSTLESS = new Set(['slab', 'apartment', 'label']);

export function computeMarks(
  elements: Element[],
  answer: Answer | null,
  reviews: Review[],
  showAll: boolean,
  highlight: number[] = [],
): Mark[] {
  const ev = new Set(answer?.evidence_ids ?? []);
  const un = new Set(answer?.uncertain_ids ?? []);
  const hi = new Set(highlight);
  const byId = new Map(reviews.map((r) => [r.id, r]));
  const out: Mark[] = [];
  for (const el of elements) {
    if (!el.bbox && !el.polygon) continue;
    if (el.type === 'storey') continue;
    const review = byId.get(el.id) ?? null;
    let role: MarkRole | null = null;
    if (hi.has(el.id)) role = 'highlight';
    else if (ev.has(el.id)) role = 'evidence';
    else if (un.has(el.id)) role = review && review.action !== 'reject' ? 'evidence' : 'uncertain';
    else if (showAll) role = review?.action === 'reject' ? 'rejected' : 'other';
    // Invisible until hovered, so any element can be inspected without asking first. Slabs and
    // apartments cover whole floors and would block the rooms under them.
    else if (!GHOSTLESS.has(el.type)) role = 'ghost';
    if (role) out.push({ el, role, review });
  }
  // Areas first so smaller marks sit on top and stay clickable; highlights on top of their peers.
  const rank = (m: Mark) =>
    (m.el.type === 'room' || m.el.type === 'apartment' ? 0 : 3) + (m.role === 'other' || m.role === 'rejected' || m.role === 'ghost' ? 0 : m.role === 'highlight' ? 2 : 1);
  return out.sort((a, b) => rank(a) - rank(b));
}
