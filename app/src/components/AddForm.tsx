import { useEffect, useRef, useState } from 'react';

interface Props {
  x: number;
  y: number;
  busy: boolean;
  onSave: (v: { type: string; room_type?: string; label?: string }) => void;
  onCancel: () => void;
}

const TYPES: [string, string][] = [
  ['door', 'Door'],
  ['window', 'Window'],
  ['wc', 'WC'],
  ['sink', 'Sink'],
  ['shower', 'Shower'],
  ['bathtub', 'Bathtub'],
  ['stair', 'Stair'],
  ['column', 'Column'],
  ['room', 'Room'],
];
const ROOM_USES: [string, string][] = [
  ['bedroom', 'Bedroom'],
  ['bathroom', 'Bathroom'],
  ['wc_room', 'WC room'],
  ['kitchen', 'Kitchen'],
  ['sauna', 'Sauna'],
  ['balcony', 'Balcony'],
  ['living_room', 'Living room'],
  ['hall', 'Hall'],
  ['storage', 'Storage'],
  ['', 'Other'],
];

/** After drawing a box: say what it is. Saved as a reviewer's addition, counted from then on. */
export function AddForm({ x, y, busy, onSave, onCancel }: Props) {
  const [type, setType] = useState('door');
  const [use, setUse] = useState('bedroom');
  const [label, setLabel] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onCancel]);

  // Keep the form inside the drawing field.
  const [pos, setPos] = useState({ left: x + 12, top: y + 12 });
  useEffect(() => {
    const node = ref.current;
    const parent = node?.offsetParent as HTMLElement | null;
    if (!node || !parent) return;
    const left = Math.min(x + 12, parent.clientWidth - node.offsetWidth - 10);
    const top = y + 12 + node.offsetHeight > parent.clientHeight - 10 ? Math.max(10, y - node.offsetHeight - 12) : y + 12;
    setPos({ left: Math.max(10, left), top });
  }, [x, y, type]);

  const save = () =>
    onSave(type === 'room' ? { type, room_type: use || undefined, label: label.trim() || undefined } : { type });

  return (
    <div ref={ref} className="callout add-form" style={pos} role="dialog" aria-label="Add to the drawing" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
      <div className="callout-head">
        <span className="callout-type">Add to drawing</span>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Cancel">
          ×
        </button>
      </div>
      <div className="add-types" role="radiogroup" aria-label="What is it">
        {TYPES.map(([t, name]) => (
          <button key={t} type="button" role="radio" aria-checked={type === t} className={type === t ? 'is-active' : ''} onClick={() => setType(t)}>
            {name}
          </button>
        ))}
      </div>
      {type === 'room' && (
        <div className="add-room">
          <label>
            <span>Use</span>
            <select className="select" value={use} onChange={(e) => setUse(e.target.value)}>
              {ROOM_USES.map(([v, n]) => (
                <option key={v} value={v}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Name</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="as written, e.g. MH" />
          </label>
        </div>
      )}
      <button type="button" className="callout-ask add-save" disabled={busy} onClick={save}>
        {busy ? 'Saving…' : 'Save to drawing'} <span aria-hidden>↵</span>
      </button>
    </div>
  );
}
