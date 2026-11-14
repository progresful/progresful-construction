import { describe, expect, it } from 'vitest';
import { bboxToRect, fitTransform, toOverlay, toPixels, zoomAt } from './geometry';
import type { PlanInfo } from '../api/types';

const ifc: PlanInfo = { url: '', width: 1400, height: 1100, viewbox: [-1, -1, 14, 11], flip_y: true };
const raster: PlanInfo = { url: '', width: 1000, height: 720, viewbox: [0, 0, 1000, 720], flip_y: false };

describe('toOverlay', () => {
  it('passes raster coordinates through', () => {
    expect(toOverlay(raster, 120, 56)).toEqual([120, 56]);
  });
  it('flips y inside the viewbox (API.md formula)', () => {
    // screen_y = vy + vh - (y - vy) = -1 + 11 - (y + 1)
    expect(toOverlay(ifc, 0, 0)).toEqual([0, 9]);
    expect(toOverlay(ifc, 3, 9)).toEqual([3, 0]);
    expect(toOverlay(ifc, 0, -1)[1]).toBe(10); // bottom edge of the viewbox -> bottom of the image
    expect(toOverlay(ifc, 0, 10)[1]).toBe(-1); // top edge -> top
  });
  it('flips with a non-zero viewbox origin', () => {
    const p = { viewbox: [100, 200, 50, 40] as [number, number, number, number], flip_y: true };
    expect(toOverlay(p, 120, 200)).toEqual([120, 240]);
    expect(toOverlay(p, 120, 240)).toEqual([120, 200]);
  });
});

describe('toPixels', () => {
  it('maps the viewbox corners to the image corners', () => {
    expect(toPixels(ifc, -1, 10)).toEqual([0, 0]);
    expect(toPixels(ifc, 13, -1)).toEqual([1400, 1100]);
    expect(toPixels(raster, 1000, 720)).toEqual([1000, 720]);
  });
});

describe('bboxToRect', () => {
  it('normalises a flipped bbox to a positive rect', () => {
    const r = bboxToRect(ifc, [1, -0.15, 2.6, 0.15]);
    expect(r.x).toBeCloseTo(1);
    expect(r.y).toBeCloseTo(8.85);
    expect(r.w).toBeCloseTo(1.6);
    expect(r.h).toBeCloseTo(0.3);
  });
});

describe('pan/zoom', () => {
  it('fits and centres content', () => {
    const t = fitTransform(1000, 500, 1200, 800, 0);
    expect(t.scale).toBeCloseTo(1.2);
    expect(t.tx).toBeCloseTo(0);
    expect(t.ty).toBeCloseTo(100);
  });
  it('keeps the cursor point fixed when zooming', () => {
    const t0 = { scale: 1, tx: 10, ty: 20 };
    const t1 = zoomAt(t0, 2, 110, 120);
    // content point under the cursor before: ((110-10)/1, (120-20)/1) = (100, 100)
    expect((110 - t1.tx) / t1.scale).toBeCloseTo(100);
    expect((120 - t1.ty) / t1.scale).toBeCloseTo(100);
  });
});

describe('zoom to evidence', () => {
  it('frames the union of evidence in pixels, capped at 2.5x the fit scale', async () => {
    const { elementsPixelBox, frameBox } = await import('./geometry');
    const el = (bbox: [number, number, number, number]) =>
      ({ id: 1, type: 'window', source: '', exact: true, conf: 1, bbox, polygon: null }) as never;
    const box = elementsPixelBox(raster, [el([100, 100, 120, 110]), el([200, 300, 210, 320])])!;
    expect(box).toEqual({ x0: 100, y0: 100, x1: 210, y1: 320 });
    const fit = fitTransform(1000, 720, 1000, 720);
    const t = frameBox({ x0: 100, y0: 100, x1: 104, y1: 104 }, 1000, 720, 1000, 720);
    expect(t.scale).toBeCloseTo(fit.scale * 2.5);
    // the box centre lands in the middle of the container
    expect(102 * t.scale + t.tx).toBeCloseTo(500);
    expect(102 * t.scale + t.ty).toBeCloseTo(360);
  });
  it('maps flipped IFC geometry into the image', async () => {
    const { elementsPixelBox } = await import('./geometry');
    const room = { id: 1, type: 'room', source: '', exact: true, conf: 1, bbox: null, polygon: [[0, 0], [7, 0], [7, 5], [0, 5]] } as never;
    expect(elementsPixelBox(ifc, [room])).toEqual({ x0: 100, y0: 500, x1: 800, y1: 1000 });
  });
});
