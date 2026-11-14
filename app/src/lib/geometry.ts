import type { Element, PlanInfo } from '../api/types';

export type Pt = [number, number];

/**
 * Drawing coordinates -> overlay coordinates.
 *
 * The overlay <svg> uses `viewBox = plan.viewbox`, so x passes through unchanged.
 * When flip_y is true (CAD / IFC, y up) y is mirrored inside the viewbox (API.md):
 *   screen_y = viewbox_y + viewbox_h - (y - viewbox_y)
 */
export function toOverlay(plan: Pick<PlanInfo, 'viewbox' | 'flip_y'>, x: number, y: number): Pt {
  if (!plan.flip_y) return [x, y];
  const [, vy, , vh] = plan.viewbox;
  return [x, vy + vh - (y - vy)];
}

/** Drawing coordinates -> image pixels (useful for tooltips and tests). */
export function toPixels(plan: PlanInfo, x: number, y: number): Pt {
  const [vx, vy, vw, vh] = plan.viewbox;
  const [ox, oy] = toOverlay(plan, x, y);
  return [((ox - vx) / vw) * plan.width, ((oy - vy) / vh) * plan.height];
}

/** A bbox [x0,y0,x1,y1] in drawing coordinates -> {x,y,w,h} rect in overlay coordinates. */
export function bboxToRect(
  plan: Pick<PlanInfo, 'viewbox' | 'flip_y'>,
  bbox: [number, number, number, number],
): { x: number; y: number; w: number; h: number } {
  const [ax, ay] = toOverlay(plan, bbox[0], bbox[1]);
  const [bx, by] = toOverlay(plan, bbox[2], bbox[3]);
  return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) };
}

export function polygonToPoints(plan: Pick<PlanInfo, 'viewbox' | 'flip_y'>, poly: [number, number][]): string {
  return poly.map(([x, y]) => toOverlay(plan, x, y).map((v) => round(v)).join(',')).join(' ');
}

/** Centre of an element in overlay coordinates, or null if it has no geometry. */
export function elementCentre(plan: Pick<PlanInfo, 'viewbox' | 'flip_y'>, el: Element): Pt | null {
  if (el.polygon && el.polygon.length) {
    const xs = el.polygon.map((p) => p[0]);
    const ys = el.polygon.map((p) => p[1]);
    return toOverlay(plan, (Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2);
  }
  if (el.bbox) return toOverlay(plan, (el.bbox[0] + el.bbox[2]) / 2, (el.bbox[1] + el.bbox[3]) / 2);
  return null;
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

/** Scale and offset that fit a (w,h) content box into a (cw,ch) container with padding. */
export function fitTransform(w: number, h: number, cw: number, ch: number, pad = 24) {
  const scale = Math.max(0.01, Math.min((cw - 2 * pad) / w, (ch - 2 * pad) / h));
  return { scale, tx: (cw - w * scale) / 2, ty: (ch - h * scale) / 2 };
}

/** Zoom by `factor` keeping the container point (cx, cy) fixed. */
export function zoomAt(
  t: { scale: number; tx: number; ty: number },
  factor: number,
  cx: number,
  cy: number,
  min = 0.05,
  max = 40,
) {
  const scale = Math.min(max, Math.max(min, t.scale * factor));
  const k = scale / t.scale;
  return { scale, tx: cx - (cx - t.tx) * k, ty: cy - (cy - t.ty) * k };
}

/** Union of element geometry in image pixels, or null when none of them has geometry. */
export function elementsPixelBox(plan: PlanInfo, els: Element[]): { x0: number; y0: number; x1: number; y1: number } | null {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const el of els) {
    const pts: [number, number][] = el.polygon?.length
      ? el.polygon
      : el.bbox
        ? [
            [el.bbox[0], el.bbox[1]],
            [el.bbox[2], el.bbox[3]],
          ]
        : [];
    for (const [x, y] of pts) {
      const [px, py] = toPixels(plan, x, y);
      x0 = Math.min(x0, px);
      y0 = Math.min(y0, py);
      x1 = Math.max(x1, px);
      y1 = Math.max(y1, py);
    }
  }
  return x0 === Infinity ? null : { x0, y0, x1, y1 };
}

/**
 * Transform that frames a pixel box in the container: never zooms out past "fit plan", never zooms in more than
 * `maxZoom` times the fit scale (so a single window does not fill the screen).
 */
export function frameBox(
  box: { x0: number; y0: number; x1: number; y1: number },
  planW: number,
  planH: number,
  cw: number,
  ch: number,
  pad = 80,
  maxZoom = 2.5,
) {
  const fit = fitTransform(planW, planH, cw, ch);
  const bw = Math.max(1, box.x1 - box.x0);
  const bh = Math.max(1, box.y1 - box.y0);
  const want = Math.min((cw - 2 * pad) / bw, (ch - 2 * pad) / bh);
  // Evidence spread over (nearly) the whole plan: just show the whole plan, centred.
  if (want <= fit.scale * 1.1) return fit;
  const scale = Math.min(want, fit.scale * maxZoom);
  const cx = (box.x0 + box.x1) / 2;
  const cy = (box.y0 + box.y1) / 2;
  return { scale, tx: cw / 2 - cx * scale, ty: ch / 2 - cy * scale };
}
