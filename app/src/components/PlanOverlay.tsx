import type { Facing, PlanInfo, Swing } from '../api/types';
import { ADDED_ID_BASE } from '../api/types';
import { bboxToRect, elementCentre, toOverlay } from '../lib/geometry';
import type { Mark } from '../lib/marks';

interface Props {
  plan: PlanInfo;
  marks: Mark[];
  /** Screen pixels per image pixel (the pan/zoom scale), so strokes stay a constant width on screen. */
  scale: number;
  tone: 'exact' | 'estimate';
  selectedId: number | null;
  onHover: (id: number | null, e?: React.PointerEvent) => void;
  onMarkClick: (id: number, e: React.MouseEvent) => void;
  /** Where an answer was read off the drawing (drawing coordinates), drawn so it can be checked. */
  readBox?: [number, number, number, number] | null;
}

/** Above this many counted marks, numbers would bury the plan; the marks alone are clearer. */
const MAX_NUMBERED = 80;

type Pt = [number, number];

/** The outline of an element in overlay coordinates, padded a little so thin symbols read. */
function outline(plan: PlanInfo, m: Mark, pad: number, min: number): Pt[] | null {
  if (m.el.polygon && m.el.polygon.length > 2) return m.el.polygon.map(([x, y]) => toOverlay(plan, x, y));
  if (!m.el.bbox) return null;
  const r = bboxToRect(plan, m.el.bbox);
  const w = Math.max(r.w + 2 * pad, min);
  const h = Math.max(r.h + 2 * pad, min);
  const x = r.x + r.w / 2 - w / 2;
  const y = r.y + r.h / 2 - h / 2;
  return [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h],
  ];
}

/**
 * A revision cloud around a polygon: the checker's red-pencil mark. Each edge is split into
 * scallops of about `s`; arcs bulge outward whichever way the polygon winds.
 */
export function cloudPath(pts: Pt[], s: number): string {
  let area = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    area += x0 * y1 - x1 * y0;
  }
  const sweep = area > 0 ? 1 : 0;
  const f = (v: number) => Math.round(v * 100) / 100;
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[(i + 1) % pts.length];
    const len = Math.hypot(bx - ax, by - ay);
    if (len === 0) continue;
    const n = Math.max(1, Math.round(len / s));
    const r = len / n / 2;
    for (let k = 1; k <= n; k++) {
      d += ` A${f(r)} ${f(r)} 0 0 ${sweep} ${f(ax + ((bx - ax) * k) / n)} ${f(ay + ((by - ay) * k) / n)}`;
    }
  }
  return d + 'Z';
}

/**
 * Number the counted marks in reading order (top to bottom in rows, then left to right), so a
 * count can be checked by eye: "12 windows" means bubbles 1 to 12 on the plan.
 */
export function numberMarks(plan: PlanInfo, marks: Mark[]): Map<number, { n: number; x: number; y: number }> {
  const out = new Map<number, { n: number; x: number; y: number }>();
  const counted = marks.filter((m) => m.role === 'evidence' || m.role === 'uncertain');
  if (counted.length === 0 || counted.length > MAX_NUMBERED) return out;
  const placed = counted
    .map((m) => {
      const isArea = m.el.type === 'room' || m.el.type === 'apartment';
      if (!isArea && m.el.bbox) {
        const r = bboxToRect(plan, m.el.bbox);
        return { id: m.el.id, x: r.x + r.w, y: r.y, cy: r.y + r.h / 2, cx: r.x + r.w / 2 }; // top-right corner
      }
      const c = elementCentre(plan, m.el);
      return c ? { id: m.el.id, x: c[0], y: c[1], cy: c[1], cx: c[0] } : null;
    })
    .filter((p): p is NonNullable<typeof p> => p !== null);
  const row = Math.abs(plan.viewbox[3]) / 12;
  placed.sort((a, b) => Math.floor(a.cy / row) - Math.floor(b.cy / row) || a.cx - b.cx);
  placed.forEach((p, i) => out.set(p.id, { n: i + 1, x: p.x, y: p.y }));
  return out;
}

/**
 * The checker's markup, drawn over the plan in its own coordinates:
 * exact evidence is yellow-lined (highlighter), estimates are clouded in red pencil, uncertain
 * marks are dashed clouds tagged with a revision delta, counted marks carry grid bubbles.
 */
export function PlanOverlay({ plan, marks, scale, tone, selectedId, onHover, onMarkClick, readBox }: Props) {
  const [vx, vy, vw, vh] = plan.viewbox;
  const u = vw / plan.width / scale; // drawing units per screen pixel
  const pins = numberMarks(plan, marks);

  return (
    <svg
      className={`overlay tone-${tone}`}
      viewBox={`${vx} ${vy} ${vw} ${vh}`}
      width={plan.width}
      height={plan.height}
      preserveAspectRatio="none"
    >
      {marks.map((m) => {
        const { el, role, review } = m;
        const pts = outline(plan, m, 3 * u, 12 * u);
        if (!pts) return null;
        const pin = pins.get(el.id);
        const area = el.type === 'room' || el.type === 'apartment';
        const pencil = el.id < ADDED_ID_BASE && (role === 'uncertain' || (role === 'evidence' && tone === 'estimate' && !review));
        const cls = [
          'mark',
          `mark-${role}`,
          area ? 'is-room' : 'is-box',
          pencil ? 'is-cloud' : 'is-plain',
          review ? `reviewed-${review.action}` : '',
          el.id >= ADDED_ID_BASE ? 'is-added' : '',
          selectedId === el.id ? 'is-selected' : '',
        ].join(' ');
        const d = pencil ? cloudPath(pts, (area ? 22 : 9) * u) : `M${pts.map((p) => p.join(' ')).join('L')}Z`;
        return (
          <path
            key={el.id}
            d={d}
            className={cls}
            strokeWidth={(role === 'other' || role === 'rejected' ? 1 : pencil ? 1.8 : 1.2) * u}
            strokeDasharray={role === 'uncertain' || role === 'rejected' ? `${5 * u} ${3 * u}` : undefined}
            style={pin ? { animationDelay: `${Math.min(pin.n * 35, 900)}ms` } : undefined}
            data-id={el.id}
            onPointerEnter={(e) => onHover(el.id, e)}
            onPointerMove={(e) => onHover(el.id, e)}
            onPointerLeave={() => onHover(null)}
            onClick={(e) => onMarkClick(el.id, e)}
          />
        );
      })}
      {readBox && (() => {
        const r = bboxToRect(plan, readBox);
        const pad = 4 * u;
        return (
          <g className="read-box" aria-hidden>
            <rect x={r.x - pad} y={r.y - pad} width={r.w + 2 * pad} height={r.h + 2 * pad} strokeWidth={1.8 * u} strokeDasharray={`${5 * u} ${3 * u}`} />
            <text x={r.x - pad} y={r.y - pad - 4 * u} fontSize={10 * u}>
              read here
            </text>
          </g>
        );
      })()}
      <g className="openings" aria-hidden>
        {marks.map(({ el, role }) => {
          const shown = role === 'evidence' || role === 'uncertain' || role === 'highlight' || selectedId === el.id;
          if (!shown) return null;
          if (el.type === 'door' && el.swing) return <SwingArrow key={el.id} plan={plan} swing={el.swing} u={u} />;
          if (el.type === 'window' && el.facing && el.bbox) return <FacingArrow key={el.id} plan={plan} bbox={el.bbox} facing={el.facing} u={u} />;
          return null;
        })}
      </g>
      <g className="pins" aria-hidden>
        {[...pins.entries()].map(([id, p]) => {
          const uncertain = marks.find((m) => m.el.id === id)?.role === 'uncertain';
          const r = (p.n > 9 ? 9 : 8) * u;
          return (
            <g key={id} transform={`translate(${p.x} ${p.y})`}>
              <g className={`pin${uncertain ? ' is-delta' : ''}${selectedId === id ? ' is-selected' : ''}`} style={{ animationDelay: `${Math.min(p.n * 35, 900) + 120}ms` }}>
                {uncertain ? (
                  <path d={`M0 ${-r * 1.25} L${r * 1.15} ${r * 0.75} L${-r * 1.15} ${r * 0.75}Z`} strokeWidth={1.2 * u} />
                ) : (
                  <circle r={r} strokeWidth={1.2 * u} />
                )}
                <text fontSize={9.5 * u} dy={(uncertain ? 2.6 : 3.3) * u}>
                  {p.n}
                </text>
              </g>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

/** The door's swing: a curved arrow from the shut leaf to the open one, around the hinge. */
function SwingArrow({ plan, swing, u }: { plan: PlanInfo; swing: Swing; u: number }) {
  const [hx, hy] = toOverlay(plan, ...swing.hinge);
  const [ox, oy] = toOverlay(plan, ...swing.open);
  const [cx, cy] = toOverlay(plan, ...swing.closed);
  const r = Math.hypot(cx - hx, cy - hy) * 0.72;
  const at = (x: number, y: number): Pt => {
    const d = Math.hypot(x - hx, y - hy) || 1;
    return [hx + ((x - hx) / d) * r, hy + ((y - hy) / d) * r];
  };
  const [ax, ay] = at(cx, cy);
  const [bx, by] = at(ox, oy);
  const sweep = (cx - hx) * (oy - hy) - (cy - hy) * (ox - hx) > 0 ? 1 : 0;
  // Arrowhead at the open end, along the direction of travel (the tangent, pointing away from shut).
  let tx = -(by - hy);
  let ty = bx - hx;
  if (tx * (bx - ax) + ty * (by - ay) < 0) [tx, ty] = [-tx, -ty];
  const tl = Math.hypot(tx, ty) || 1;
  [tx, ty] = [tx / tl, ty / tl];
  const s = 6 * u;
  const head = `M${bx - tx * s - ty * s * 0.6} ${by - ty * s + tx * s * 0.6} L${bx} ${by} L${bx - tx * s + ty * s * 0.6} ${by - ty * s - tx * s * 0.6}`;
  return (
    <g className={`swing${swing.exact ? ' is-exact' : ''}`}>
      <circle cx={hx} cy={hy} r={2.6 * u} />
      <path d={`M${ax} ${ay} A${r} ${r} 0 0 ${sweep} ${bx} ${by}`} strokeWidth={1.4 * u} />
      <path d={head} strokeWidth={1.4 * u} />
    </g>
  );
}

/** Which way a window looks out: an arrow from the glass outwards, with the compass point if known. */
function FacingArrow({ plan, bbox, facing, u }: { plan: PlanInfo; bbox: [number, number, number, number]; facing: Facing; u: number }) {
  const mx = (bbox[0] + bbox[2]) / 2;
  const my = (bbox[1] + bbox[3]) / 2;
  const [x0, y0] = toOverlay(plan, mx, my);
  // The normal is in drawing coordinates; map a point along it to get the on-screen direction.
  const [x1, y1] = toOverlay(plan, mx + facing.normal[0], my + facing.normal[1]);
  const dl = Math.hypot(x1 - x0, y1 - y0) || 1;
  const [nx, ny] = [(x1 - x0) / dl, (y1 - y0) / dl];
  const start = 6 * u;
  const len = 22 * u;
  const [sx, sy] = [x0 + nx * start, y0 + ny * start];
  const [ex, ey] = [x0 + nx * len, y0 + ny * len];
  const s = 5 * u;
  return (
    <g className="facing">
      <path d={`M${sx} ${sy} L${ex} ${ey}`} strokeWidth={1.4 * u} />
      <path d={`M${ex - nx * s - ny * s * 0.7} ${ey - ny * s + nx * s * 0.7} L${ex} ${ey} L${ex - nx * s + ny * s * 0.7} ${ey - ny * s - nx * s * 0.7}`} strokeWidth={1.4 * u} />
      {facing.compass && (
        <text x={ex + nx * 8 * u} y={ey + ny * 8 * u + 3.5 * u} fontSize={10 * u}>
          {facing.compass}
        </text>
      )}
    </g>
  );
}
