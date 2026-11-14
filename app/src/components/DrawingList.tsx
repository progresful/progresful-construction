import { useState } from 'react';
import type { DrawingSummary, Kind } from '../api/types';
import { drawingSubtitle, drawingTitle, sourceLabel, statusLabel } from '../lib/format';

interface Props {
  drawings: DrawingSummary[] | null;
  error: string | null;
  selectedId: string | null;
  sourceFilter: string;
  onSourceFilter: (s: string) => void;
  onSelect: (id: string) => void;
  onPrepare: (id: string) => void;
}

const STATUS_ORDER: Record<DrawingSummary['status'], number> = { ready: 0, preparing: 1, not_extracted: 2, failed: 3 };

export function DrawingList({ drawings, error, selectedId, sourceFilter, onSourceFilter, onSelect, onPrepare }: Props) {
  const [search, setSearch] = useState('');
  const sources = [...new Set((drawings ?? []).map((d) => d.source))].sort();
  const needle = search.trim().toLowerCase();
  const shown = (drawings ?? [])
    .filter((d) => !sourceFilter || d.source === sourceFilter)
    .filter((d) => !needle || d.path.toLowerCase().includes(needle) || (d.title ?? '').toLowerCase().includes(needle))
    .map((d, i) => ({ d, i }))
    .sort((a, b) => STATUS_ORDER[a.d.status] - STATUS_ORDER[b.d.status] || a.i - b.i)
    .map(({ d }) => d);
  const readyCount = (drawings ?? []).filter((d) => d.status === 'ready').length;
  const firstNotReady = shown.findIndex((d) => d.status !== 'ready');

  return (
    <aside className="panel drawings">
      <div className="panel-head">
        <h2>Drawings</h2>
        <select className="select" value={sourceFilter} onChange={(e) => onSourceFilter(e.target.value)} aria-label="Filter by source">
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {sourceLabel(s)}
            </option>
          ))}
        </select>
      </div>
      <div className="drawing-search">
        <input
          type="search"
          className="input"
          placeholder="Search drawings…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search drawings"
        />
        {drawings && (
          <span className="muted small">
            {readyCount} of {drawings.length} ready to ask
          </span>
        )}
      </div>

      {error && <div className="notice notice-error">{error}</div>}
      {!drawings && !error && <div className="muted pad">Loading drawings…</div>}
      {drawings && shown.length === 0 && <div className="muted pad">No drawings match.</div>}

      <ul className="drawing-list">
        {shown.map((d, i) => (
          <li key={d.id}>
            {i === firstNotReady && firstNotReady > 0 && <div className="list-divider">Not prepared yet</div>}
            <button
              type="button"
              className={`drawing-item${d.id === selectedId ? ' is-selected' : ''}${d.status !== 'ready' ? ' is-dim' : ''}`}
              onClick={() => onSelect(d.id)}
              title={d.path}
            >
              <Thumb url={d.thumb_url ?? null} kind={d.read_from} />
              <span className="drawing-text">
                <span className="drawing-name">{drawingTitle(d)}</span>
                <span className="drawing-meta">{drawingSubtitle(d)}</span>
                {d.status !== 'ready' && (
                  <span className="drawing-foot">
                    <StatusBadge status={d.status} />
                    {d.status === 'not_extracted' && (
                      <span
                        role="button"
                        tabIndex={0}
                        className="btn btn-small"
                        onClick={(e) => {
                          e.stopPropagation();
                          onPrepare(d.id);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            e.stopPropagation();
                            onPrepare(d.id);
                          }
                        }}
                      >
                        Prepare
                      </span>
                    )}
                  </span>
                )}
                {d.status === 'failed' && d.error && (
                  <span className="drawing-error" title={d.error}>
                    {d.error}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function Thumb({ url, kind }: { url: string | null; kind: Kind }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="thumb" aria-hidden>
      {url && !failed ? (
        <img src={url} loading="lazy" alt="" onError={() => setFailed(true)} />
      ) : (
        <KindIcon kind={kind} />
      )}
    </span>
  );
}

function KindIcon({ kind }: { kind: Kind }) {
  const label = { ifc: 'IFC', dxf: 'DXF', pdf: 'PDF', raster: 'IMG', sheet: 'SHEET' }[kind] ?? kind.toUpperCase();
  return (
    <span className={`kind-icon kind-${kind}`}>
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6">
        {kind === 'ifc' ? (
          <path d="M4 8l8-4 8 4-8 4-8-4zm0 4l8 4 8-4M4 16l8 4 8-4" />
        ) : kind === 'raster' ? (
          <path d="M4 5h16v14H4zM4 15l5-5 4 4 3-3 4 4" />
        ) : (
          <path d="M5 4h14v16H5zM5 12h8v8M13 4v4" />
        )}
      </svg>
      <span>{label}</span>
    </span>
  );
}

export function StatusBadge({ status }: { status: DrawingSummary['status'] }) {
  return (
    <span className={`status status-${status}`}>
      {status === 'preparing' && <span className="spinner" aria-hidden />}
      {statusLabel(status)}
    </span>
  );
}
