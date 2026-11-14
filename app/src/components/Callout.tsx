import { useEffect, useRef, useState } from 'react';
import type { Element, Kind, Review, ReviewAction } from '../api/types';
import { ELEMENT_TYPES } from '../api/types';
import { areaProvenance, provenance, roomName } from '../lib/format';

interface Props {
  el: Element;
  kind: Kind;
  review: Review | null;
  x: number;
  y: number;
  busy: boolean;
  /** The element is part of the active estimate: it can be accepted, rejected or retyped. */
  canReview: boolean;
  onAction: (action: ReviewAction, type?: string) => void;
  onAsk: (question: string) => void;
  onClose: () => void;
  /** Move, resize or redraw this element on the plan. */
  onAdjust?: () => void;
  /** Drawn by the reviewer: offer Remove instead of Accept/Reject. */
  added?: boolean;
  /** Name of a room by element id, for "opens into" and "lights". */
  roomName: (id: number | null) => string | null;
}

const COMPASS_NAME: Record<string, string> = {
  N: 'north',
  NE: 'north-east',
  E: 'east',
  SE: 'south-east',
  S: 'south',
  SW: 'south-west',
  W: 'west',
  NW: 'north-west',
};

const ROOM_PLURAL: Record<string, string> = {
  bedroom: 'bedrooms',
  bathroom: 'bathrooms',
  kitchen: 'kitchens',
  sauna: 'saunas',
  wc_room: 'separate WC rooms',
  balcony: 'balconies',
};
const ELEMENT_QUESTION: Record<string, [string, string]> = {
  window: ['windows', 'How many windows are there?'],
  door: ['doors', 'How many doors are there?'],
  wc: ['toilets', 'How many toilets (WC seats) are there?'],
  sink: ['sinks', 'How many sinks are there?'],
  shower: ['showers and bathtubs', 'How many showers and bathtubs are there in total?'],
  bathtub: ['showers and bathtubs', 'How many showers and bathtubs are there in total?'],
  wall: ['walls', 'How many walls are there?'],
  column: ['columns', 'How many columns are there?'],
  beam: ['beams', 'How many beams are there?'],
  stair: ['stairs', 'How many stairs are there?'],
};

/** The follow-up question an element suggests: "count all of these". */
export function followUp(el: Element): { label: string; question: string } | null {
  if (el.type === 'room') {
    const plural = el.room_type && ROOM_PLURAL[el.room_type];
    return plural ? { label: `Count all ${plural}`, question: `How many ${plural} are there?` } : null;
  }
  const q = ELEMENT_QUESTION[el.type];
  return q ? { label: `Count all ${q[0]}`, question: q[1] } : null;
}

/** A callout on the plan: what an element is and where that comes from, without asking a question. */
export function Callout({ el, kind, review, x, y, busy, canReview, onAction, onAsk, onClose, roomName: nameOf, added, onAdjust }: Props) {
  const [retype, setRetype] = useState(el.type);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setRetype(el.type), [el.id, el.type]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  // Keep the callout inside the drawing field.
  const [pos, setPos] = useState({ left: x + 14, top: y + 14 });
  useEffect(() => {
    const node = ref.current;
    const parent = node?.offsetParent as HTMLElement | null;
    if (!node || !parent) return;
    const left = Math.min(x + 14, parent.clientWidth - node.offsetWidth - 10);
    const top = y + 14 + node.offsetHeight > parent.clientHeight - 10 ? Math.max(10, y - node.offsetHeight - 14) : y + 14;
    setPos({ left: Math.max(10, left), top });
  }, [x, y, el.id]);

  const isRoom = el.type === 'room' || el.type === 'apartment';
  const name = isRoom ? roomName(el) : el.label;
  const area = el.quantities?.area_m2;
  const more = followUp(el);
  const rows: [string, string][] = [];
  if (isRoom && el.room_type) rows.push(['Use', el.room_type.replace(/_/g, ' ')]);
  if (el.number) rows.push(['No.', el.number]);
  if (el.apartment) rows.push(['Apartment', el.apartment]);
  if (el.storey) rows.push(['Storey', el.storey]);
  if (area != null) rows.push(['Area', `${area.toLocaleString('en-GB', { maximumFractionDigits: 2 })} m²${areaProvenance(el.quantity_source?.area_m2) ? ` · ${areaProvenance(el.quantity_source?.area_m2)}` : ''}`]);
  const len = el.quantities?.length_m;
  if (len != null) rows.push(['Length', `${len.toLocaleString('en-GB', { maximumFractionDigits: 2 })} m`]);
  const vol = el.quantities?.volume_m3;
  if (vol != null) rows.push(['Volume', `${vol.toLocaleString('en-GB', { maximumFractionDigits: 2 })} m³`]);
  if (el.outdoor) rows.push(['Outdoor', 'yes']);
  if (el.swing) {
    const into = nameOf(el.swing.into);
    rows.push(['Opens into', `${into ?? 'unlabelled space or outside'}${el.swing.exact ? '' : ' · read from the symbol'}`]);
  }
  if (el.facing) {
    const side = `${el.facing.sheet} of the sheet`;
    rows.push(['Faces', el.facing.compass ? `${COMPASS_NAME[el.facing.compass] ?? el.facing.compass} (${side})` : `${side}${kind === 'raster' ? ' · no north arrow' : ''}`]);
    const lit = nameOf(el.facing.room);
    if (lit) rows.push(['Lights', lit]);
  }
  rows.push(['Source', provenance(el, kind)]);
  if (!el.exact && !added) rows.push(['Confidence', `${Math.round(el.conf * 100)}%`]);

  return (
    <div
      ref={ref}
      className="callout"
      style={pos}
      role="dialog"
      aria-label={`Details of ${name ?? el.type}`}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="callout-head">
        <span className="callout-type">{el.type === 'wc' ? 'WC' : el.type}</span>
        <span className="callout-id mono">#{el.id}</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {name && <div className="callout-name">{name}</div>}
      <dl className="callout-rows">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {review && !added && (
        <div className="callout-reviewed">
          Reviewed: {review.action}
          {review.action === 'retype' && review.type ? ` → ${review.type}` : ''}
        </div>
      )}
      {canReview && (
        <div className="callout-review">
          <div className="callout-actions">
            {added ? (
              <button type="button" className="btn btn-reject" disabled={busy} onClick={() => onAction('reject')}>
                Remove
              </button>
            ) : (
              <>
                <button type="button" className="btn btn-accept" disabled={busy} onClick={() => onAction('accept')}>
                  Accept
                </button>
                <button type="button" className="btn btn-reject" disabled={busy} onClick={() => onAction('reject')}>
                  Reject
                </button>
              </>
            )}
          </div>
          <div className="callout-actions">
            <select className="select" value={retype} onChange={(e) => setRetype(e.target.value)} disabled={busy} aria-label="New type">
              {ELEMENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button type="button" className="btn" disabled={busy || retype === el.type} onClick={() => onAction('retype', retype)}>
              Retype
            </button>
          </div>
          {busy && <div className="callout-busy">Saving and re-asking…</div>}
        </div>
      )}
      {onAdjust && (
        <button type="button" className="callout-ask" onClick={onAdjust}>
          {el.type === 'room' ? 'Adjust or redraw outline' : 'Adjust shape'} <span aria-hidden>⤡</span>
        </button>
      )}
      {more && (
        <button type="button" className="callout-ask" onClick={() => onAsk(more.question)}>
          {more.label} <span aria-hidden>↵</span>
        </button>
      )}
    </div>
  );
}
