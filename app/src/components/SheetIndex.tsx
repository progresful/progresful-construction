import { useEffect, useMemo, useRef, useState } from 'react';
import type { DrawingSummary } from '../api/types';
import { drawingTitle, sourceLabel } from '../lib/format';
import { basis, dwgNo } from '../lib/sheet';
import { Thumb } from './DrawingList';
import { useIncremental } from '../lib/useIncremental';

interface Props {
  drawings: DrawingSummary[] | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpenRegister: () => void;
}

/** Short set codes, as on a sheet index. */
const SET_CODE: Record<string, string> = {
  challenge: '★',
  cubicasa5k: 'CC',
  swiss_dwellings: 'SD',
  ifc_models: 'IFC',
  ifc_bench: 'IB',
  opening_design: 'OD',
};

/** The sheet index down the left edge: every drawing one click away, the current one marked. */
export function SheetIndex({ drawings, selectedId, onSelect, onOpenRegister }: Props) {
  const [search, setSearch] = useState('');
  const [set, setSet] = useState('');
  const current = useRef<HTMLButtonElement>(null);

  const sets = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of drawings ?? []) m.set(d.source, (m.get(d.source) ?? 0) + 1);
    // The challenge sheets first: they are what the owners want to see.
    return [...m.entries()].sort((a, b) => (a[0] === 'challenge' ? -1 : b[0] === 'challenge' ? 1 : b[1] - a[1]));
  }, [drawings]);

  const needle = search.trim().toLowerCase();
  const rows = (drawings ?? []).filter(
    (d) =>
      (!set || d.source === set) &&
      (!needle || dwgNo(d).toLowerCase().includes(needle) || drawingTitle(d).toLowerCase().includes(needle) || d.path.toLowerCase().includes(needle)),
  );

  // Thousands of sheets: render a page at a time; the current one is always included.
  const { shown, more, sentinel } = useIncremental(rows, `${set}|${needle}`);
  const visible = selectedId && !shown.some((d) => d.id === selectedId) ? [...shown, ...rows.filter((d) => d.id === selectedId)] : shown;

  // Keep the current sheet in view when it changes (also via [ and ]).
  useEffect(() => {
    current.current?.scrollIntoView({ block: 'nearest' });
  }, [selectedId]);

  return (
    <nav className="index" aria-label="Sheet index">
      <div className="index-head">
        <span className="index-logo">Constructor</span>
        <span className="index-kicker">Sheet index</span>
      </div>
      <div className="index-tools">
        <input type="search" placeholder="Find a sheet" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Find a sheet" />
        <div className="index-sets" role="tablist" aria-label="Set">
          <button type="button" role="tab" aria-selected={!set} className={!set ? 'is-active' : ''} onClick={() => setSet('')} title="All sets">
            All
          </button>
          {sets.map(([s, n]) => (
            <button key={s} type="button" role="tab" aria-selected={set === s} className={set === s ? 'is-active' : ''} onClick={() => setSet(s)} title={`${sourceLabel(s)}, ${n} sheets`}>
              {SET_CODE[s] ?? s.slice(0, 3).toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <ol className="index-list">
        {visible.map((d) => (
          <li key={d.id}>
            <button
              ref={d.id === selectedId ? current : undefined}
              type="button"
              className={`index-row${d.id === selectedId ? ' is-current' : ''}${d.status !== 'ready' ? ' is-dim' : ''}`}
              onClick={() => onSelect(d.id)}
              title={d.path}
              aria-current={d.id === selectedId ? 'page' : undefined}
            >
              <Thumb url={d.thumb_url ?? null} kind={d.read_from} />
              <span className="index-text">
                <span className="index-no">
                  {dwgNo(d)}
                  <span className={`index-basis basis-${basis(d.read_from) === 'exact' ? 'exact' : 'est'}`}>{basis(d.read_from) === 'exact' ? 'EX' : basis(d.read_from) === 'text' ? 'TXT' : 'EST'}</span>
                </span>
                <span className="index-title">{drawingTitle(d)}</span>
              </span>
            </button>
          </li>
        ))}
        {drawings && rows.length === 0 && <li className="index-empty">No sheet matches.</li>}
        {more > 0 && (
          <li className="index-empty" ref={(n) => (sentinel.current = n)}>
            {more} more…
          </li>
        )}
      </ol>
      <button type="button" className="index-foot" onClick={onOpenRegister}>
        Full register · {drawings?.length ?? 0} sheets ▸
      </button>
    </nav>
  );
}
