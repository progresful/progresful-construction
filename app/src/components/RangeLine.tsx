interface Props {
  value: number;
  range: [number, number];
  count: boolean;
}

/**
 * The likely range drawn as an architectural dimension line: extension lines and 45° ticks at
 * the two ends, the figures above, and the answer marked on the line.
 */
export function RangeLine({ value, range, count }: Props) {
  const W = 300;
  const lo = Math.min(range[0], value);
  const hi = Math.max(range[1], value);
  const pad = Math.max(count ? 1 : 0, (hi - lo) * 0.15);
  const min = Math.max(0, lo - pad);
  const max = hi + pad;
  const x = (v: number) => 12 + ((v - min) / (max - min || 1)) * (W - 24);
  const fmt = (v: number) => v.toLocaleString('en-GB', { maximumFractionDigits: count ? 0 : 1 });
  const [a, b, v] = [x(range[0]), x(range[1]), x(value)];
  const y = 28;
  return (
    <figure className="dim" aria-label={`Value ${fmt(value)}, likely between ${fmt(range[0])} and ${fmt(range[1])}`}>
      <svg viewBox={`0 0 ${W} 44`} role="img">
        <line className="dim-ext" x1={a} y1={18} x2={a} y2={38} />
        <line className="dim-ext" x1={b} y1={18} x2={b} y2={38} />
        <line className="dim-line" x1={a - 6} y1={y} x2={b + 6} y2={y} />
        <line className="dim-tick" x1={a - 4} y1={y + 4} x2={a + 4} y2={y - 4} />
        <line className="dim-tick" x1={b - 4} y1={y + 4} x2={b + 4} y2={y - 4} />
        <text className="dim-fig" x={a - 6} y={y - 8} textAnchor="end">
          {fmt(range[0])}
        </text>
        <text className="dim-fig" x={b + 6} y={y - 8} textAnchor="start">
          {fmt(range[1])}
        </text>
        <path className="dim-value" d={`M${v} ${y - 1} l-4 9 h8 z`} />
      </svg>
      <figcaption>Likely range · from how far such counts missed on training plans</figcaption>
    </figure>
  );
}
