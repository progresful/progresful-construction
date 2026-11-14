import { useEffect, useMemo, useRef, useState } from 'react';
import type { DrawingSummary } from '../api/types';
import { drawingTitle, sourceLabel, statusLabel } from '../lib/format';
import { basis, dwgNo, formatName } from '../lib/sheet';
import { Thumb } from './DrawingList';
import { useIncremental } from '../lib/useIncremental';

interface Props {
  drawings: DrawingSummary[] | null;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPrepare: (id: string) => void;
  onClose: () => void;
}

/** What each set is, in one line, so a first-time visitor knows what they are picking. */
const SET_NOTE: Record<string, string> = {
  challenge: 'Example sheets from the challenge owners: slab areas by type, floor areas, baseboards, doors and windows, piping.',
  cubicasa5k: 'Finnish apartment plans, scanned. Answers are estimates, each mark shown for checking.',
  swiss_dwellings: 'Swiss apartment floors, CAD. Exact counts and areas.',
  ifc_models: 'Building models, IFC. Exact quantities read from the model.',
  ifc_bench: 'IFC models with free-form questions.',
  opening_design: 'Door and finish schedules, PDF.',
};

/** The drawing register: every sheet in the set, one row each, filed by dataset. */
export function Library({ drawings, error, selectedId, onSelect, onPrepare, onClose }: Props) {
  const [search, setSearch] = useState('');
  const [set, setSet] = useState('');
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    const key = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  const sets = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of drawings ?? []) m.set(d.source, (m.get(d.source) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => (a[0] === 'challenge' ? -1 : b[0] === 'challenge' ? 1 : b[1] - a[1]));
  }, [drawings]);

  const needle = search.trim().toLowerCase();
  const rows = (drawings ?? []).filter(
    (d) =>
      (!set || d.source === set) &&
      (!needle || d.path.toLowerCase().includes(needle) || drawingTitle(d).toLowerCase().includes(needle) || dwgNo(d).toLowerCase().includes(needle)),
  );

  const { shown, more, sentinel } = useIncremental(rows, `${set}|${needle}`);

  const pick = (d: DrawingSummary) => {
    onSelect(d.id);
    if (d.status === 'not_extracted') onPrepare(d.id);
    onClose();
  };

  return (
    <div className="register" role="dialog" aria-modal="true" aria-label="Drawing register">
      <header className="register-head">
        <div>
          <div className="register-kicker">Constructor · Drawing register</div>
          <h1>
            {drawings ? drawings.length : '…'} sheets, {sets.length} sets
          </h1>
        </div>
        <button type="button" className="ink-btn" onClick={onClose}>
          Close <kbd>Esc</kbd>
        </button>
      </header>

      <div className="register-tools">
        <label className="field-line">
          <span>Find</span>
          <input ref={input} type="search" placeholder="drawing no., name or number" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <div className="sets" role="tablist" aria-label="Set">
          <button type="button" role="tab" aria-selected={!set} className={!set ? 'is-active' : ''} onClick={() => setSet('')}>
            All<sup>{drawings?.length ?? 0}</sup>
          </button>
          {sets.map(([s, n]) => (
            <button key={s} type="button" role="tab" aria-selected={set === s} className={set === s ? 'is-active' : ''} onClick={() => setSet(s)}>
              {sourceLabel(s)}
              <sup>{n}</sup>
            </button>
          ))}
        </div>
        {set && <p className="set-note">{SET_NOTE[set]}</p>}
      </div>

      <div className="register-body">
        {error && <p className="register-error">{error}</p>}
        <table className="reg">
          <thead>
            <tr>
              <th className="col-thumb" aria-label="Preview" />
              <th>Dwg no.</th>
              <th>Title</th>
              <th>Set</th>
              <th>Format</th>
              <th>Basis</th>
              <th className="num">Qs</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id} className={`${d.id === selectedId ? 'is-current' : ''}${d.status !== 'ready' ? ' is-dim' : ''}`} onClick={() => pick(d)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && pick(d)} title={d.path}>
                <td className="col-thumb">
                  <Thumb url={d.thumb_url ?? null} kind={d.read_from} />
                </td>
                <td className="mono">{dwgNo(d)}</td>
                <td className="title">{drawingTitle(d)}</td>
                <td>{sourceLabel(d.source)}</td>
                <td>{formatName(d.read_from)}</td>
                <td className={`basis-${basis(d.read_from) === 'exact' ? 'exact' : 'est'}`}>{basis(d.read_from)}</td>
                <td className="num mono">{d.question_count}</td>
                <td>{d.id === selectedId ? 'on the board' : statusLabel(d.status).toLowerCase()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {drawings && rows.length === 0 && <p className="register-empty">No sheet matches “{search}”.</p>}
        {more > 0 && (
          <p className="register-empty" ref={(n) => (sentinel.current = n)}>
            {more} more sheets…
          </p>
        )}
      </div>
    </div>
  );
}
