import type { PlanInfo } from '../api/types';
import { toOverlay } from '../lib/geometry';

export type Pt = [number, number];
export interface Shape {
  bbox: [number, number, number, number] | null;
  polygon: Pt[] | null;
}

interface Props {
  plan: PlanInfo;
  shape: Shape;
  /** Redrawing an outline: the points clicked so far (drawing coordinates). */
  redraw: Pt[] | null;
  /** Drawing units per screen pixel, so handles keep their size on screen. */
  u: number;
}

/** Box corners and edge midpoints, in drawing coordinates, with the handle names the drag logic uses. */
export function boxHandles(b: [number, number, number, number]): [string, Pt][] {
  const [x0, y0, x1, y1] = b;
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  return [
    ['c0', [x0, y0]],
    ['c1', [x1, y0]],
    ['c2', [x1, y1]],
    ['c3', [x0, y1]],
    ['e0', [mx, y0]],
    ['e1', [x1, my]],
    ['e2', [mx, y1]],
    ['e3', [x0, my]],
  ];
}

/** Apply a drag of (dx, dy) drawing units on `handle` to the shape as it was when the drag began. */
export function dragShape(start: Shape, handle: string, dx: number, dy: number): Shape {
  if (start.polygon) {
    if (handle === 'move') return { bbox: null, polygon: start.polygon.map(([x, y]) => [x + dx, y + dy]) };
    const i = Number(handle.slice(1));
    return { bbox: null, polygon: start.polygon.map((p, j) => (j === i ? [p[0] + dx, p[1] + dy] : p)) };
  }
  let [x0, y0, x1, y1] = start.bbox!;
  if (handle === 'move') return { bbox: [x0 + dx, y0 + dy, x1 + dx, y1 + dy], polygon: null };
  if (handle === 'c0' || handle === 'c3' || handle === 'e3') x0 += dx;
  if (handle === 'c1' || handle === 'c2' || handle === 'e1') x1 += dx;
  if (handle === 'c0' || handle === 'c1' || handle === 'e0') y0 += dy;
  if (handle === 'c2' || handle === 'c3' || handle === 'e2') y1 += dy;
  return { bbox: [x0, y0, x1, y1], polygon: null };
}

/** Handles over the element being adjusted: drag a handle to resize or reshape, the body to move. */
export function ShapeEditor({ plan, shape, redraw, u }: Props) {
  const [vx, vy, vw, vh] = plan.viewbox;
  const o = (p: Pt) => toOverlay(plan, p[0], p[1]);
  const s = 9 * u;

  let body: JSX.Element | null = null;
  let handles: [string, Pt][] = [];
  if (redraw) {
    const pts = redraw.map(o);
    body = (
      <>
        {pts.length > 1 && <polyline className="edit-redraw" points={pts.map((p) => p.join(',')).join(' ')} strokeWidth={1.6 * u} />}
        {pts.map((p, i) => (
          <circle key={i} className={`edit-point${i === 0 ? ' is-first' : ''}`} cx={p[0]} cy={p[1]} r={(i === 0 ? 6 : 4) * u} strokeWidth={1.4 * u} data-handle={i === 0 ? 'close' : undefined} />
        ))}
      </>
    );
  } else if (shape.polygon) {
    body = <polygon className="edit-body" points={shape.polygon.map(o).map((p) => p.join(',')).join(' ')} strokeWidth={1.6 * u} data-handle="move" />;
    handles = shape.polygon.map((p, i) => [`v${i}`, p]);
  } else if (shape.bbox) {
    const [ax, ay] = o([shape.bbox[0], shape.bbox[1]]);
    const [bx, by] = o([shape.bbox[2], shape.bbox[3]]);
    body = (
      <rect
        className="edit-body"
        x={Math.min(ax, bx)}
        y={Math.min(ay, by)}
        width={Math.abs(bx - ax)}
        height={Math.abs(by - ay)}
        strokeWidth={1.6 * u}
        data-handle="move"
      />
    );
    handles = boxHandles(shape.bbox);
  }

  return (
    <svg className="shape-editor" viewBox={`${vx} ${vy} ${vw} ${vh}`} width={plan.width} height={plan.height} preserveAspectRatio="none">
      {body}
      {handles.map(([name, p]) => {
        const [x, y] = o(p);
        return <rect key={name} className="edit-handle" x={x - s / 2} y={y - s / 2} width={s} height={s} strokeWidth={1.4 * u} data-handle={name} />;
      })}
    </svg>
  );
}
