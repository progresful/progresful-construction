import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { Answer, Element, Kind, NewElement, PlanInfo, Review, ReviewAction } from '../api/types';
import { ADDED_ID_BASE } from '../api/types';
import { elementsPixelBox, fitTransform, toOverlay, zoomAt } from '../lib/geometry';
import { areaProvenance, countNoun, formatValue, provenance, roomName, unitLabel } from '../lib/format';
import { computeMarks } from '../lib/marks';
import { PlanOverlay, numberMarks } from './PlanOverlay';
import { AddForm } from './AddForm';
import { Callout } from './Callout';
import { ShapeEditor, dragShape, type Pt, type Shape } from './ShapeEditor';

export interface Focus {
  /** Changes whenever the view should re-frame (new active card, clicked room, ...). */
  key: string;
  ids: number[];
}

interface Props {
  drawingKey: string;
  kind: Kind;
  plan: PlanInfo;
  imageUrl: string;
  elements: Element[];
  answer: Answer | null;
  /** Rooms highlighted from the overview table (hover or click). */
  highlightIds: number[];
  focus: Focus | null;
  reviews: Review[];
  credit: string;
  storeys: string[];
  storey: string | null;
  onStorey: (s: string) => void;
  showAll: boolean;
  onShowAll: (v: boolean) => void;
  /** Review is possible only on estimates. */
  reviewable: boolean;
  onReview: (el: Element, action: ReviewAction, type?: string) => Promise<void>;
  /** Dismiss the active answer (the evidence bar's close button). */
  onClearAnswer: () => void;
  /** Ask a follow-up question from an element's callout. */
  onAsk: (question: string) => void;
  /** Save an element the reviewer drew on the plan. */
  onAdd: (n: NewElement) => Promise<void>;
  /** Save a moved, resized or redrawn element. */
  onReshape: (el: Element, shape: { bbox?: [number, number, number, number]; polygon?: [number, number][] }) => Promise<void>;
}

type T = { scale: number; tx: number; ty: number };

export function PlanView(props: Props) {
  const { plan, imageUrl, elements, answer, reviews, showAll, reviewable, highlightIds, focus } = props;
  const viewport = useRef<HTMLDivElement>(null);
  const [t, setT] = useState<T>({ scale: 1, tx: 0, ty: 0 });
  const [animating, setAnimating] = useState(false);
  // The user zoomed or panned since the last automatic fit/frame: leave the view alone on resize.
  const userMoved = useRef(false);
  const drag = useRef<{ x: number; y: number; t: T; moved: boolean; pointer: number } | null>(null);
  const suppressClick = useRef(false);
  const lastDrawingKey = useRef<string | null>(null);
  const animTimer = useRef<number>();
  const [hover, setHover] = useState<{ id: number; x: number; y: number } | null>(null);
  const [popover, setPopover] = useState<{ id: number; x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  /** Add mode: dragging draws a box instead of panning. */
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [pending, setPending] = useState<{ bbox: [number, number, number, number]; x: number; y: number } | null>(null);
  /** Adjusting one element: its shape as edited so far, or the outline being redrawn point by point. */
  const [edit, setEdit] = useState<{ el: Element; shape: Shape; redraw: Pt[] | null } | null>(null);
  const editDrag = useRef<{ handle: string; start: Pt; shape: Shape; pointer: number } | null>(null);
  /** Index into the numbered evidence while stepping through it, else null. */
  const [step, setStep] = useState<number | null>(null);
  const [imgState, setImgState] = useState<'loading' | 'ok' | 'error'>('loading');

  const byId = useMemo(() => new Map(elements.map((e) => [e.id, e])), [elements]);
  const marks = useMemo(
    () => computeMarks(elements, answer, reviews, showAll, highlightIds),
    [elements, answer, reviews, showAll, highlightIds],
  );
  const reviewById = useMemo(() => new Map(reviews.map((r) => [r.id, r])), [reviews]);

  const go = useCallback((next: T, animate: boolean) => {
    window.clearTimeout(animTimer.current);
    setAnimating(animate);
    setT(next);
    if (animate) animTimer.current = window.setTimeout(() => setAnimating(false), 520);
  }, []);

  // Plan size: the server's PlanInfo, or the image's natural size if the server sent none.
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const pw = plan.width > 0 ? plan.width : (natural?.w ?? 0);
  const ph = plan.height > 0 ? plan.height : (natural?.h ?? 0);
  const sizedPlan = useMemo(() => ({ ...plan, width: pw, height: ph }), [plan, pw, ph]);

  // Latest inputs for applyView, so the ResizeObserver callback never sees stale props.
  const latest = useRef({ focus, byId, plan, pw, ph, t });
  latest.current = { focus, byId, plan, pw, ph, t };
  const retry = useRef<number>();

  /**
   * Fit the whole plan. Does nothing (and retries next frame) while the viewer or the plan has no
   * size yet, so we never fit into a 0-px box (that gave the "1 % zoom" bug).
   */
  const applyView = useCallback(
    (animate: boolean) => {
      const v = viewport.current;
      const { pw, ph } = latest.current;
      window.cancelAnimationFrame(retry.current ?? 0);
      if (!v || v.clientWidth < 80 || v.clientHeight < 80 || !(pw > 0) || !(ph > 0)) {
        retry.current = window.requestAnimationFrame(() => applyView(animate));
        return;
      }
      go(fitTransform(pw, ph, v.clientWidth, v.clientHeight), animate);
      userMoved.current = false;
    },
    [go],
  );

  /** The part of the plan (image pixels) on screen now, inset by `margin` screen pixels. */
  const onScreen = (box: { x0: number; y0: number; x1: number; y1: number }, margin = 40) => {
    const v = viewport.current;
    const cur = latest.current.t;
    if (!v) return true;
    const sx0 = box.x0 * cur.scale + cur.tx;
    const sy0 = box.y0 * cur.scale + cur.ty;
    const sx1 = box.x1 * cur.scale + cur.tx;
    const sy1 = box.y1 * cur.scale + cur.ty;
    return sx0 >= margin && sy0 >= margin && sx1 <= v.clientWidth - margin && sy1 <= v.clientHeight - margin;
  };
  useEffect(() => () => window.cancelAnimationFrame(retry.current ?? 0), []);

  const fit = useCallback(
    (animate = false) => {
      const v = viewport.current;
      if (!v || v.clientWidth < 80 || v.clientHeight < 80 || !(pw > 0)) return applyView(animate);
      go(fitTransform(pw, ph, v.clientWidth, v.clientHeight), animate);
      userMoved.current = false;
    },
    [pw, ph, go, applyView],
  );

  // Re-frame when the drawing/storey, the focus (active card or picked room) or the plan size changes.
  // Animate only within the same plan; jump when the plan itself changes.
  const focusKey = focus?.key ?? '';
  useLayoutEffect(() => {
    const samePlan = lastDrawingKey.current === props.drawingKey;
    lastDrawingKey.current = props.drawingKey;
    setPopover(null);
    if (!samePlan) setHover(null);
    // A new answer or picked room never zooms in: the plan stays as the user left it, and is only
    // fitted again when the evidence would be off screen.
    const els = (focus?.ids ?? []).map((id) => byId.get(id)).filter((e): e is Element => !!e);
    const box = els.length ? elementsPixelBox(sizedPlan, els) : null;
    if (!samePlan || !userMoved.current || (box && !onScreen(box, 0))) applyView(samePlan);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.drawingKey, focusKey, pw, ph, applyView]);

  useEffect(() => {
    setImgState('loading');
    setNatural(null);
  }, [imageUrl]);
  useEffect(() => {
    setPopover(null);
    setStep(null);
  }, [answer]);

  // Viewer resized (window resize, first layout): re-apply the automatic view unless the user moved it.
  useEffect(() => {
    const v = viewport.current;
    if (!v) return;
    const ro = new ResizeObserver(() => !userMoved.current && applyView(false));
    ro.observe(v);
    return () => ro.disconnect();
  }, [applyView]);

  // Wheel zoom around the cursor (non-passive so the page does not scroll).
  useEffect(() => {
    const v = viewport.current;
    if (!v) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = v.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015));
      userMoved.current = true;
      setAnimating(false);
      setT((cur) => zoomAt(cur, factor, e.clientX - r.left, e.clientY - r.top));
    };
    v.addEventListener('wheel', onWheel, { passive: false });
    return () => v.removeEventListener('wheel', onWheel);
  }, []);

  const zoomBy = (f: number) => {
    const v = viewport.current;
    if (!v) return;
    userMoved.current = true;
    go(zoomAt(t, f, v.clientWidth / 2, v.clientHeight / 2), true);
  };

  /** Viewport pixels -> drawing coordinates (the inverse of what the overlay draws). */
  const toDrawing = (x: number, y: number): [number, number] => {
    const [vx, vy, vw, vh] = plan.viewbox;
    const ox = vx + (((x - t.tx) / t.scale) / pw) * vw;
    const oy = vy + (((y - t.ty) / t.scale) / ph) * vh;
    return toOverlay(plan, ox, oy); // the y flip is its own inverse
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    if (edit) {
      const handle = (e.target as HTMLElement).closest?.('[data-handle]')?.getAttribute('data-handle');
      const p = localPoint(e);
      if (edit.redraw) {
        e.preventDefault();
        const pts = edit.redraw;
        // Clicking the first point closes the outline.
        if (handle === 'close' && pts.length >= 3) return finishRedraw();
        setEdit({ ...edit, redraw: [...pts, toDrawing(p.x, p.y)] });
        return;
      }
      if (handle) {
        e.preventDefault();
        e.stopPropagation();
        editDrag.current = { handle, start: toDrawing(p.x, p.y), shape: edit.shape, pointer: e.pointerId };
        viewport.current?.setPointerCapture(e.pointerId);
        return;
      }
      // Anywhere else: pan as usual.
    }
    if (adding) {
      // Nothing else may act on this press: no browser image drag, no text selection, no pan.
      e.preventDefault();
      e.stopPropagation();
      const p = localPoint(e);
      setPending(null);
      setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
      viewport.current?.setPointerCapture(e.pointerId);
      return;
    }
    drag.current = { x: e.clientX, y: e.clientY, t, moved: false, pointer: e.pointerId };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (editDrag.current && edit) {
      const p = localPoint(e);
      const [x, y] = toDrawing(p.x, p.y);
      const d = editDrag.current;
      setEdit({ ...edit, shape: dragShape(d.shape, d.handle, x - d.start[0], y - d.start[1]) });
      return;
    }
    if (draft) {
      const p = localPoint(e);
      setDraft({ ...draft, x1: p.x, y1: p.y });
      return;
    }
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    if (!d.moved) {
      d.moved = true;
      // Capture only once it is a drag, so plain clicks still reach the marks.
      viewport.current?.setPointerCapture(d.pointer);
      setHover(null);
      setAnimating(false);
    }
    userMoved.current = true;
    setT({ ...d.t, tx: d.t.tx + dx, ty: d.t.ty + dy });
  };
  const onPointerUp = () => {
    if (editDrag.current) {
      editDrag.current = null;
      suppressClick.current = true;
      setTimeout(() => (suppressClick.current = false), 0);
      return;
    }
    if (draft) {
      const { x0, y0, x1, y1 } = draft;
      setDraft(null);
      suppressClick.current = true;
      setTimeout(() => (suppressClick.current = false), 0);
      if (Math.abs(x1 - x0) < 6 || Math.abs(y1 - y0) < 6) return; // a click, not a box
      const [ax, ay] = toDrawing(x0, y0);
      const [bx, by] = toDrawing(x1, y1);
      const r = (v: number) => Math.round(v * 1000) / 1000;
      setPending({ bbox: [r(Math.min(ax, bx)), r(Math.min(ay, by)), r(Math.max(ax, bx)), r(Math.max(ay, by))], x: Math.max(x0, x1), y: Math.max(y0, y1) });
      return;
    }
    const d = drag.current;
    drag.current = null;
    if (d?.moved) {
      suppressClick.current = true;
      setTimeout(() => (suppressClick.current = false), 0);
    }
  };

  const startAdjust = (el: Element) => {
    setPopover(null);
    setAdding(false);
    setPending(null);
    const shape: Shape = el.polygon
      ? { bbox: null, polygon: el.polygon.map(([x, y]) => [x, y] as Pt) }
      : { bbox: el.bbox ? [...el.bbox] as [number, number, number, number] : null, polygon: null };
    setEdit({ el, shape, redraw: null });
  };
  const finishRedraw = () => {
    if (!edit?.redraw || edit.redraw.length < 3) return;
    setEdit({ ...edit, shape: { bbox: null, polygon: edit.redraw }, redraw: null });
  };
  const saveEdit = async () => {
    if (!edit) return;
    const r = (v: number) => Math.round(v * 1000) / 1000;
    const { bbox, polygon } = edit.shape;
    setBusy(true);
    try {
      if (polygon) await props.onReshape(edit.el, { polygon: polygon.map(([x, y]) => [r(x), r(y)]) });
      else if (bbox) {
        const [x0, y0, x1, y1] = bbox;
        await props.onReshape(edit.el, { bbox: [r(Math.min(x0, x1)), r(Math.min(y0, y1)), r(Math.max(x0, x1)), r(Math.max(y0, y1))] });
      }
      setEdit(null);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!edit) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setEdit(null);
      if (e.key === 'Enter' && edit.redraw) finishRedraw();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  });
  useEffect(() => setEdit(null), [props.drawingKey]);

  const saveAdd = async (v: { type: string; room_type?: string; label?: string }) => {
    if (!pending) return;
    setBusy(true);
    try {
      await props.onAdd({ ...v, bbox: pending.bbox, storey: props.storey ?? undefined });
      setPending(null);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!adding) return;
    const key = (e: KeyboardEvent) => e.key === 'Escape' && !pending && setAdding(false);
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [adding, pending]);
  useEffect(() => {
    setAdding(false);
    setPending(null);
  }, [props.drawingKey]);

  const localPoint = (e: { clientX: number; clientY: number }) => {
    const r = viewport.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onHover = (id: number | null, e?: React.PointerEvent) => {
    if (drag.current?.moved) return;
    if (id == null || !e) return setHover(null);
    setHover({ id, ...localPoint(e) });
  };

  const onMarkClick = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (suppressClick.current) return;
    if (!byId.get(id)) return;
    setHover(null);
    setPopover({ id, ...localPoint(e) });
  };

  const onAction = async (action: ReviewAction, type?: string) => {
    const el = popover && byId.get(popover.id);
    if (!el) return;
    setBusy(true);
    try {
      await props.onReview(el, action, type);
      setPopover(null);
    } finally {
      setBusy(false);
    }
  };

  // The counted marks in pin order: stepping walks them 1, 2, 3... and frames each one.
  const pinOrder = useMemo(() => {
    const pins = numberMarks(sizedPlan, marks);
    return [...pins.entries()].sort((a, b) => a[1].n - b[1].n).map(([id]) => id);
  }, [sizedPlan, marks]);
  const stepId = step != null ? (pinOrder[step] ?? null) : null;
  const goStep = (i: number | null) => {
    const v = viewport.current;
    setStep(i);
    setPopover(null);
    if (i == null || !v) return;
    const el = byId.get(pinOrder[i]);
    const box = el && elementsPixelBox(sizedPlan, [el]);
    if (!box) return;
    // Off screen: nudge the plan just far enough to show it (the check strip covers the bottom),
    // at the current zoom. Never zooms in.
    const m = 40;
    const bottom = 90;
    const sx0 = box.x0 * t.scale + t.tx;
    const sx1 = box.x1 * t.scale + t.tx;
    const sy0 = box.y0 * t.scale + t.ty;
    const sy1 = box.y1 * t.scale + t.ty;
    const dx = sx0 < m ? m - sx0 : sx1 > v.clientWidth - m ? v.clientWidth - m - sx1 : 0;
    const dy = sy0 < m ? m - sy0 : sy1 > v.clientHeight - bottom ? v.clientHeight - bottom - sy1 : 0;
    if (dx || dy) go({ ...t, tx: t.tx + dx, ty: t.ty + dy }, true);
  };
  useEffect(() => {
    if (!pinOrder.length) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest('input, textarea, select')) return;
      if (e.key === 'ArrowRight') goStep(step == null ? 0 : Math.min(pinOrder.length - 1, step + 1));
      if (e.key === 'ArrowLeft' && step != null) goStep(step === 0 ? null : step - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const hovered = hover ? byId.get(hover.id) : undefined;
  const popEl = popover ? byId.get(popover.id) : undefined;
  const tone = answer && !answer.exact ? 'estimate' : 'exact';
  const hasAnswer = !!answer && answer.value != null;

  return (
    <section className="stage">
      <div
        ref={viewport}
        className={`plan-viewport${adding ? ' is-adding' : ''}${edit ? ' is-editing' : ''}${edit?.redraw ? ' is-redrawing' : ''}`}
        onPointerDown={onPointerDown}
        onDragStart={(e) => e.preventDefault()}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onClick={() => !suppressClick.current && setPopover(null)}
      >
        <div
          className={`plan-canvas${animating ? ' is-animating' : ''}`}
          style={{
            width: pw || undefined,
            height: ph || undefined,
            transform: `translate(${t.tx}px, ${t.ty}px) scale(${t.scale})`,
          }}
        >
          <img
            src={imageUrl}
            width={pw || undefined}
            height={ph || undefined}
            alt="Rendered plan"
            draggable={false}
            onLoad={(e) => {
              setImgState('ok');
              const img = e.currentTarget;
              if (img.naturalWidth > 0) setNatural({ w: img.naturalWidth, h: img.naturalHeight });
              // The image only now has its final layout in some browsers: re-apply unless the user moved the view.
              if (!userMoved.current) applyView(false);
            }}
            onError={() => setImgState('error')}
          />
          {pw > 0 && ph > 0 && (
          <PlanOverlay
            plan={sizedPlan}
            marks={edit ? marks.filter((m) => m.el.id !== edit.el.id) : marks}
            scale={t.scale}
            tone={tone}
            selectedId={popover?.id ?? stepId}
            onHover={onHover}
            onMarkClick={onMarkClick}
            readBox={Array.isArray(answer?.params?.read_box) ? (answer!.params.read_box as [number, number, number, number]) : null}
          />
          )}
          {edit && pw > 0 && ph > 0 && <ShapeEditor plan={sizedPlan} shape={edit.shape} redraw={edit.redraw} u={plan.viewbox[2] / pw / t.scale} />}
        </div>

        {imgState === 'loading' && <div className="plan-status">Loading plan…</div>}
        {imgState === 'error' && <div className="plan-status plan-status-error">Could not load the plan image.</div>}

        {hovered && hover && !popover && <Tooltip el={hovered} kind={props.kind} x={hover.x} y={hover.y} review={reviewById.get(hovered.id)} />}

        {popEl && popover && (
          <Callout
            el={popEl}
            kind={props.kind}
            review={reviewById.get(popEl.id) ?? null}
            x={popover.x}
            y={popover.y}
            busy={busy}
            canReview={popEl.id >= ADDED_ID_BASE || (reviewable && !popEl.exact && !!answer && [...answer.evidence_ids, ...answer.uncertain_ids].includes(popEl.id))}
            added={popEl.id >= ADDED_ID_BASE}
            onAction={onAction}
            onAsk={(q) => {
              setPopover(null);
              props.onAsk(q);
            }}
            onAdjust={popEl.bbox || popEl.polygon ? () => startAdjust(popEl) : undefined}
            onClose={() => setPopover(null)}
            roomName={(id) => {
              const r = id == null ? undefined : byId.get(id);
              return r ? roomName(r) : null;
            }}
          />
        )}

        {edit && (
          <div className="float float-tc edit-bar" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
            <span className="edit-bar-what">
              {edit.redraw
                ? `Click round the ${edit.el.type}; click the first point or press Enter to close`
                : `Adjusting ${edit.el.type === 'wc' ? 'WC' : edit.el.type} · drag the handles or the shape`}
            </span>
            {(edit.el.type === 'room' || edit.el.type === 'apartment') && !edit.redraw && (
              <button type="button" onClick={() => setEdit({ ...edit, redraw: [] })}>
                Redraw outline
              </button>
            )}
            {edit.redraw && edit.redraw.length >= 3 && (
              <button type="button" onClick={finishRedraw}>
                Close outline
              </button>
            )}
            <button type="button" onClick={() => setEdit(null)}>
              Cancel
            </button>
            <button type="button" className="is-primary" disabled={busy || !!edit.redraw} onClick={saveEdit}>
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        )}
        {draft && (
          <div
            className="draft-box"
            style={{ left: Math.min(draft.x0, draft.x1), top: Math.min(draft.y0, draft.y1), width: Math.abs(draft.x1 - draft.x0), height: Math.abs(draft.y1 - draft.y0) }}
          />
        )}
        {pending && <AddForm x={pending.x} y={pending.y} busy={busy} onSave={saveAdd} onCancel={() => setPending(null)} />}

        {props.storeys.length > 0 && (
          <div className="float float-tc segmented" role="tablist" aria-label="Storey" onPointerDown={(e) => e.stopPropagation()}>
            {props.storeys.map((s) => (
              <button key={s} type="button" role="tab" aria-selected={s === props.storey} className={s === props.storey ? 'is-active' : ''} onClick={() => props.onStorey(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        <div className="float float-tr tools" onPointerDown={(e) => e.stopPropagation()}>
          <button
            type="button"
            className={`pill-toggle${adding ? ' is-on' : ''}`}
            aria-pressed={adding}
            onClick={() => {
              setAdding(!adding);
              setPending(null);
              setPopover(null);
            }}
            title="Draw a box around something the drawing missed, then say what it is"
          >
            <span aria-hidden>{adding ? '×' : '+'}</span>
            {adding ? 'Drag a box · Esc' : 'Add'}
          </button>
          <button type="button" className={`pill-toggle${showAll ? ' is-on' : ''}`} aria-pressed={showAll} onClick={() => props.onShowAll(!showAll)} title="Show every element the drawing was read into">
            <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
              <path d="M10 3l7 4-7 4-7-4 7-4zM3 11l7 4 7-4" />
            </svg>
            {showAll ? 'All layers' : 'Evidence only'}
          </button>
        </div>

        <div className="float float-br zoom" role="group" aria-label="Zoom" onPointerDown={(e) => e.stopPropagation()}>
          <button type="button" onClick={() => zoomBy(1 / 1.25)} aria-label="Zoom out">
            −
          </button>
          <span className="zoom-level">{Math.round(t.scale * 100)}%</span>
          <button type="button" onClick={() => zoomBy(1.25)} aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={() => fit(true)} aria-label="Fit plan" title="Fit plan">
            <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
              <path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4" />
            </svg>
          </button>
        </div>

        <div className="float float-bl credit" title={props.credit}>
          {props.credit}
        </div>

        {hasAnswer && (
          <EvidenceBar
            answer={answer!}
            count={pinOrder.length}
            step={step}
            onStep={goStep}
            onClose={props.onClearAnswer}
          />
        )}
        {!hasAnswer && highlightIds.length > 0 && (
          <div className="float float-bc evidence-bar is-room">
            <span className="swatch tone-highlight" /> Selected room
          </div>
        )}
      </div>
    </section>
  );
}

function EvidenceBar({
  answer,
  count,
  step,
  onStep,
  onClose,
}: {
  answer: Answer;
  count: number;
  step: number | null;
  onStep: (i: number | null) => void;
  onClose: () => void;
}) {
  const range = answer.range && answer.range[0] < answer.range[1] ? answer.range : null;
  const unit = answer.unit === 'count' ? countNoun(answer) : unitLabel(answer.unit);
  return (
    <div className={`float float-bc evidence-bar tone-${answer.exact ? 'exact' : 'estimate'}`} onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
      <div className="eb-answer">
        {typeof answer.value === 'string' ? (
          <>
            <strong>{count}</strong> marked
          </>
        ) : (
          <>
            <strong>{formatValue(answer)}</strong> {unit}
          </>
        )}
        <span className="eb-kind">{answer.params?.read_box ? 'read from plan' : answer.template === 'analyst' ? 'interpreted' : answer.exact ? 'exact' : range ? `est. ${range[0]}–${range[1]}` : 'estimate'}</span>
      </div>
      {count > 0 ? (
        <div className="eb-step">
          <button type="button" aria-label="Previous mark" disabled={step == null} onClick={() => onStep(step === 0 ? null : (step ?? 0) - 1)}>
            ‹
          </button>
          <button type="button" className="eb-step-label" onClick={() => onStep(step == null ? 0 : null)} title="Step through the marks one by one (← →)">
            {step == null ? `Check ${count} mark${count === 1 ? '' : 's'}` : `${String(step + 1).padStart(2, '0')} / ${String(count).padStart(2, '0')}`}
          </button>
          <button type="button" aria-label="Next mark" disabled={step === count - 1} onClick={() => onStep(step == null ? 0 : step + 1)}>
            ›
          </button>
        </div>
      ) : (
        <div className="eb-note">{answer.params?.read_box ? 'Read from the drawing · boxed on the plan' : answer.evidence_ids.length + answer.uncertain_ids.length === 0 ? 'No marks for this answer' : 'Marks shown'}</div>
      )}
      <button type="button" className="eb-close" aria-label="Clear answer" onClick={onClose}>
        ×
      </button>
    </div>
  );
}

function Tooltip({ el, kind, x, y, review }: { el: Element; kind: Kind; x: number; y: number; review?: Review }) {
  const isRoom = el.type === 'room' || el.type === 'apartment';
  const name = isRoom ? roomName(el) : el.label;
  const area = el.quantities?.area_m2;
  return (
    <div className="tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="tooltip-title">
        {name ? <strong>{name}</strong> : <strong className="cap">{el.type}</strong>}
        {name && <span className="tooltip-type"> · {el.type === 'room' && el.room_type ? el.room_type.replace(/_/g, ' ') : el.type}</span>}
      </div>
      {area != null && (
        <div>
          {area.toLocaleString('en-GB', { maximumFractionDigits: 2 })} m²
          {areaProvenance(el.quantity_source?.area_m2) && <span className="tooltip-muted"> · {areaProvenance(el.quantity_source?.area_m2)}</span>}
        </div>
      )}
      <div className="tooltip-muted">
        {provenance(el, kind)}
        {!el.exact && ` · ${Math.round(el.conf * 100)}% confident`}
      </div>
      {review && <div className="tooltip-muted">reviewed: {review.action === 'retype' ? `retyped to ${review.type}` : review.action}</div>}
      <div className="tooltip-id">
        #{el.id}
        {el.exact && el.source ? ` · ${el.source}` : ''}
      </div>
    </div>
  );
}

/** Shown instead of the plan when the server sends plan_note (e.g. NoDerivatives licences). */
export function PlanNote({ note, credit }: { note: string; credit: string }) {
  return (
    <section className="stage">
      <div className="plan-note">
        <div className="plan-note-card">
          <div className="plan-note-icon" aria-hidden>
            i
          </div>
          <div className="empty-title">Plan not shown</div>
          <p className="muted">{note}</p>
          <p className="muted small">Questions still work: answers are read from the model data.</p>
        </div>
      </div>
      <div className="float float-bl credit" title={credit}>
        {credit}
      </div>
    </section>
  );
}
