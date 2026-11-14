import { useState } from 'react';

interface Props {
  disabled: boolean;
  disabledReason?: string;
  suggestions: string[];
  /** The number the next note will get. */
  nextNo: number;
  onAsk: (q: string) => void;
}

/** The next note on the sheet, waiting to be written. */
export function QuestionBox({ disabled, disabledReason, suggestions, nextNo, onAsk }: Props) {
  const [q, setQ] = useState('');

  const submit = (text = q) => {
    const t = text.trim();
    if (!t || disabled) return;
    onAsk(t);
    setQ('');
  };

  return (
    <div className="ask-line">
      {suggestions.length > 0 && !disabled && (
        <div className="try" aria-label="Suggested questions">
          <span>Try</span>
          {suggestions.map((s) => (
            <button key={s} type="button" onClick={() => submit(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="ask-row">
        <span className="ask-no">{String(nextNo).padStart(2, '0')}</span>
        <textarea
          value={q}
          rows={1}
          placeholder={disabled ? disabledReason : 'Ask the drawing, in any language'}
          disabled={disabled}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          aria-label="Question"
        />
        <button type="button" className="ink-btn ink-btn-solid" disabled={disabled || !q.trim()} onClick={() => submit()}>
          Ask ↵
        </button>
      </div>
    </div>
  );
}
