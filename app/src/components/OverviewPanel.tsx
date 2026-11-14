import type { Overview, OverviewFact, OverviewRoom } from '../api/types';
import { formatValue, roomName, unitLabel } from '../lib/format';

interface Props {
  overview: Overview | null;
  error: string | null;
  activeFactKey: string | null;
  highlightedRoom: number | null;
  /** IFC: only the selected storey's rooms are listed. */
  storey: string | null;
  onFact: (f: OverviewFact) => void;
  onRoomHover: (id: number | null) => void;
  onRoomClick: (r: OverviewRoom) => void;
  /** Which schedule to show: one per sidebar tab. */
  part: 'quantities' | 'rooms';
  /** Image plans: find the rooms again (button above the room schedule). */
  onRedetect?: () => void;
  /** Progress or result of the last re-detect, shown beside the button. */
  redetecting?: string | null;
}

/** What the app already read from the drawing, laid out as the schedules on a drawing sheet. */
export function OverviewPanel({ overview, error, activeFactKey, highlightedRoom, storey, onFact, onRoomHover, onRoomClick, part, onRedetect, redetecting }: Props) {
  if (error) return <p className="sched-empty">No schedule for this drawing: {error}</p>;
  if (!overview) return <p className="sched-empty">Reading schedule…</p>;

  const hasApartments = overview.rooms.some((r) => r.apartment);
  const rooms = storey ? overview.rooms.filter((r) => r.storey === storey) : overview.rooms;
  // Image plans often have no room areas: a column of dashes says nothing, so show room types instead.
  const hasAreas = rooms.some((r) => r.area_m2 != null && r.has_area !== false);
  const hasTypes = rooms.some((r) => r.room_type);

  return (
    <>
      {part === 'quantities' && overview.sheet && (
        <table className="sched">
          <caption>Title block</caption>
          <tbody>
            {(
              [
                ['Sheet', overview.sheet.sheet_id],
                ['Title', overview.sheet.title],
                ['Discipline', overview.sheet.discipline],
                ['Scale', overview.sheet.printed],
                ['Units', overview.sheet.units],
              ] as const
            )
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <tr key={k}>
                  <td className="use">{k}</td>
                  <td>{v}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {part === 'quantities' && overview.sheet?.summary && <p className="sheet-summary">{overview.sheet.summary}</p>}
      {part === 'quantities' && overview.facts.length === 0 && !overview.sheet && <p className="sched-empty">No standard quantities for this drawing. Ask a question instead.</p>}
      {part === 'quantities' && overview.facts.length > 0 && (
        <table className="sched">
          <caption>Schedule of quantities</caption>
          <thead>
            <tr>
              <th>Item</th>
              <th className="num">Qty</th>
              <th>Basis</th>
            </tr>
          </thead>
          <tbody>
            {overview.facts.map((f) => {
              const r = f.answer.range && f.answer.range[0] < f.answer.range[1] ? f.answer.range : null;
              return (
                <tr
                  key={f.key}
                  className={`${activeFactKey === f.key ? 'is-active' : ''}${f.answer.value === 0 ? ' is-zero' : ''}`}
                  onClick={() => onFact(f)}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && onFact(f)}
                  title={f.question}
                >
                  <td>{f.label}</td>
                  <td className="num">
                    {formatValue(f.answer)}
                    {f.answer.unit !== 'count' && <span className="u"> {unitLabel(f.answer.unit)}</span>}
                  </td>
                  <td className={f.answer.exact ? 'basis-exact' : 'basis-est'}>{f.answer.exact ? 'exact' : r ? `est. ${r[0]}–${r[1]}` : 'est.'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {part === 'rooms' && onRedetect && (
        <div className="redetect">
          <button type="button" className="ink-btn" onClick={onRedetect} disabled={!!redetecting && redetecting.endsWith('…')}>
            {redetecting?.endsWith('…') ? 'Re-detecting…' : 'Re-detect rooms'}
          </button>
          <span>{redetecting ?? 'Outlines off? Find the rooms again, more carefully. Your edits are kept.'}</span>
        </div>
      )}
      {part === 'rooms' && rooms.length === 0 && <p className="sched-empty">No rooms were read from this drawing{storey ? ` on ${storey}` : ''}.</p>}
      {part === 'rooms' && rooms.length > 0 && (
        <table className="sched" onMouseLeave={() => onRoomHover(null)}>
          <caption>
            Room schedule{storey ? `, ${storey}` : ''} <span>({rooms.length})</span>
          </caption>
          <thead>
            <tr>
              <th>Room</th>
              {hasApartments && <th>Apt</th>}
              {hasTypes && <th>Use</th>}
              {hasAreas && <th className="num">Area m²</th>}
            </tr>
          </thead>
          <tbody>
            {rooms.map((r) => (
              <tr
                key={r.id}
                className={highlightedRoom === r.id ? 'is-active' : ''}
                onMouseEnter={() => onRoomHover(r.id)}
                onClick={() => onRoomClick(r)}
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && onRoomClick(r)}
              >
                <td>{roomName(r)}</td>
                {hasApartments && <td>{r.apartment ?? ''}</td>}
                {hasTypes && <td className="use">{r.room_type?.replace(/_/g, ' ') ?? ''}</td>}
                {hasAreas && (
                  <td className="num">
                    {r.area_m2 != null && r.has_area !== false && (
                      <>
                        {r.area_m2.toLocaleString('en-GB', { maximumFractionDigits: 2 })}
                        {!r.exact && <span className="basis-est"> ~</span>}
                      </>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
