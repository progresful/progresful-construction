import type { AskResponse } from '../api/types';
import { RangeLine } from './RangeLine';
import { countNoun, formatCost, formatParams, formatValue, rangeText, unitLabel } from '../lib/format';

export interface Card {
  key: string;
  question: string;
  status: 'loading' | 'done' | 'error';
  answer?: AskResponse;
  error?: string;
  /** Re-asking after a review; the old answer stays visible meanwhile. */
  refreshing?: boolean;
  /** Every element id this card has ever shown, for the "reviewed" count. */
  seenIds: number[];
  /** Opened from the overview (answer came with it, not re-asked). */
  factKey?: string;
}

interface Props {
  card: Card;
  /** Note number, oldest first. */
  index: number;
  active: boolean;
  reviewedCount: number;
  onSelect: () => void;
  onRetry: () => void;
}

/** Notes that make the relation between the number and the marks on the plan explicit. */
export function evidenceNotes(a: AskResponse): string[] {
  const notes: string[] = [];
  if (a.value == null || a.unit !== 'count' || typeof a.value !== 'number') return notes;
  const nE = a.evidence_ids.length;
  const nU = a.uncertain_ids.length;
  if (!a.exact && nE === 0) {
    notes.push('No marks counted — estimate from the whole image.');
    if (nU > 0) notes.push(`${nU} mark${nU === 1 ? '' : 's'} shown for reference.`);
    return notes;
  }
  // A count that the marks cannot explain: lower than the counted marks, or above counted + uncertain.
  if (a.value < nE || a.value > nE + nU) {
    notes.push(`The count is ${a.value}; ${nE + nU} mark${nE + nU === 1 ? ' is' : 's are'} drawn on the plan.`);
  }
  return notes;
}

export function AnswerCard({ card, index, active, reviewedCount, onSelect, onRetry }: Props) {
  const a = card.answer;
  const answered = a && a.value != null;
  const kind = !a ? 'pending' : !answered ? 'none' : a.exact ? 'exact' : 'estimate';
  const notes = a && answered ? evidenceNotes(a) : [];
  const nMarks = a ? a.evidence_ids.length + a.uncertain_ids.length : 0;

  return (
    <article
      className={`note note-${kind}${active ? ' is-active' : ''}${card.refreshing ? ' is-refreshing' : ''}`}
      onClick={onSelect}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onSelect();
        }
      }}
      aria-current={active}
    >
      <div className="note-no">{String(index).padStart(2, '0')}</div>
      <div className="note-body">
        <div className="note-q">{card.question}</div>

        {card.status === 'loading' && !a && (
          <div className="note-loading" aria-live="polite">
            Reading the drawing<span className="dots" aria-hidden>…</span>
          </div>
        )}

        {card.status === 'error' && (
          <div className="note-error">
            <div>Could not answer: {card.error ?? 'unknown error'}.</div>
            <button
              type="button"
              className="link"
              onClick={(e) => {
                e.stopPropagation();
                onRetry();
              }}
            >
              Try again
            </button>
          </div>
        )}

        {a && !answered && (
          <div className="note-none">
            <span className="stamp stamp-void">Not on this drawing</span>
            <p>{a.text && !/can't answer this from the drawing yet/i.test(a.text) ? a.text : 'Nothing is guessed. The drawing does not hold this information, or no template asks it yet.'}</p>
          </div>
        )}

        {a && answered && (
          <>
            <div className="note-a">
              {Array.isArray(a.params.items) ? (
                <span className="note-value">{(a.params.items as BreakdownRow[]).length}</span>
              ) : (
                <span className={`note-value${typeof a.value === 'string' && a.value.length > 14 ? ' is-text' : ''}`}>{formatValue(a)}</span>
              )}
              <span className="note-unit">{Array.isArray(a.params.items) ? 'lines' : a.unit === 'count' ? countNoun(a) : unitLabel(a.unit)}</span>
              {a.template === 'analyst' ? (
                <span className="stamp stamp-interp" title={a.params.read_box ? 'Read off the drawing where it is boxed on the plan' : 'Gemini chose which elements answer this; the value is computed from them'}>
                  {a.params.read_box ? 'Read from plan' : 'Interpreted'}
                </span>
              ) : (
                <span className={`stamp stamp-${a.exact ? 'exact' : 'estimate'}`}>{a.exact ? 'Exact' : 'Estimate'}</span>
              )}
              {card.refreshing && <span className="note-refresh">re-checking…</span>}
            </div>
            {rangeText(a) && typeof a.value === 'number' && a.range && <RangeLine value={a.value} range={a.range} count={a.unit === 'count'} />}
            {Array.isArray(a.params.items) && <Breakdown items={a.params.items as BreakdownRow[]} />}
            {typeof a.params.expression === 'string' && a.params.aggregate === 'calculate' && <p className="note-working mono">= {a.params.expression}</p>}
            {a.template === 'analyst' && typeof a.params.reading === 'string' && a.params.reading && <p className="note-reading">{a.params.reading}</p>}
            {a.text && a.template !== 'analyst' && <p className="note-text">{a.text}</p>}
            {notes.map((n) => (
              <p key={n} className="note-warn">
                {n}
              </p>
            ))}
            <div className="note-foot">
              {nMarks > 0 && (
                <span>
                  {a.evidence_ids.length > 0 && `${a.evidence_ids.length} marked`}
                  {a.evidence_ids.length > 0 && a.uncertain_ids.length > 0 && ' · '}
                  {a.uncertain_ids.length > 0 && `${a.uncertain_ids.length} Δ uncertain`}
                </span>
              )}
              {reviewedCount > 0 && <span>{reviewedCount} reviewed</span>}
              {card.factKey && <span>from schedule</span>}
              <details onClick={(e) => e.stopPropagation()}>
                <summary>How</summary>
                <dl>
                  <dt>Template</dt>
                  <dd className="mono">
                    {a.template}
                    {Object.keys(a.params).length > 0 && `(${formatParams(a.params)})`}
                  </dd>
                  <dt>Cost</dt>
                  <dd>{a.cost_known ? `${formatCost(a.cost_usd)} for this question` : 'model calls not priced'}</dd>
                  {a.fallback && (
                    <>
                      <dt>Route</dt>
                      <dd>whole-image fallback</dd>
                    </>
                  )}
                </dl>
              </details>
            </div>
          </>
        )}
      </div>
    </article>
  );
}

interface BreakdownRow {
  label: string;
  value: number | string;
  unit: string;
  how: string;
  m2?: number;
}

/** A checked breakdown: each line with its value and how it was obtained (printed, counted or calculated). */
function Breakdown({ items }: { items: BreakdownRow[] }) {
  const show = (r: BreakdownRow) => {
    if (typeof r.value !== 'number') return r.value;
    const n = r.value.toLocaleString('en-GB', { maximumFractionDigits: 2 });
    if (r.unit === 'sqft') return `${n} SF${r.m2 != null ? ` · ${r.m2.toLocaleString('en-GB')} m²` : ''}`;
    return `${n}${r.unit === 'm2' ? ' m²' : r.unit === 'm' ? ' m' : ''}`;
  };
  return (
    <table className="sched breakdown">
      <tbody>
        {items.map((r, i) => (
          <tr key={i}>
            <td>{r.label}</td>
            <td className="num">{show(r)}</td>
            <td className="how mono">{r.how}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
