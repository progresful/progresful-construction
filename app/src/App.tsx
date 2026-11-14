import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Api, ApiMode } from './api/client';
import { connect } from './api/client';
import type { DrawingDetail, DrawingSummary, Element, NewElement, Overview, OverviewFact, OverviewRoom, Review, ReviewAction } from './api/types';
import { ADDED_ID_BASE, addedElement, planFor, reshaped, reviewGroup } from './api/types';
import { AnswerCard, type Card } from './components/AnswerCard';
import { StatusBadge } from './components/DrawingList';
import { Library } from './components/Library';
import { SheetIndex } from './components/SheetIndex';
import { OverviewPanel } from './components/OverviewPanel';
import { PlanNote, PlanView, type Focus } from './components/PlanView';
import { QuestionBox } from './components/QuestionBox';
import { drawingTitle } from './lib/format';
import { basis, dwgNo, formatName } from './lib/sheet';

const POLL_MS = 1000;
let cardSeq = 0;

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function App() {
  const [conn, setConn] = useState<{ api: Api; mode: ApiMode; reason?: string } | null>(null);
  const [drawings, setDrawings] = useState<DrawingSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadedDetail, setDetail] = useState<DrawingDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [storey, setStorey] = useState<string | null>(null);
  const [cards, setCards] = useState<Record<string, Card[]>>({});
  const cardsRef = useRef(cards);
  cardsRef.current = cards;
  const [activeCard, setActiveCard] = useState<Record<string, string | null>>({});
  const [reviews, setReviews] = useState<Record<string, Review[]>>({});
  const [showAll, setShowAll] = useState(false);
  const [overviews, setOverviews] = useState<Record<string, Overview | { error: string }>>({});
  const [suggestions, setSuggestions] = useState<Record<string, string[]>>({});
  const [hoverRoom, setHoverRoom] = useState<number | null>(null);
  const [pinnedRoom, setPinnedRoom] = useState<number | null>(null);
  /** Narrow screens show one panel at a time. */
  const [pane, setPane] = useState<'plan' | 'ask'>('plan');
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [tab, setTab] = useState<'notes' | 'schedule' | 'rooms'>('notes');
  /** Bumped to reload the open drawing after its rooms were re-detected. */
  const [reloadKey, setReloadKey] = useState(0);
  const [redetecting, setRedetecting] = useState<string | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);
  const api = conn?.api;

  // Connect once (real API or mock).
  useEffect(() => {
    connect().then(setConn);
  }, []);

  const refreshList = useCallback(async () => {
    if (!api) return;
    try {
      const list = await api.listDrawings();
      setDrawings(list);
      setListError(null);
    } catch (e) {
      setListError(`Could not load drawings: ${errText(e)}`);
    }
  }, [api]);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  // Select the first ready drawing on first load.
  useEffect(() => {
    if (!selectedId && drawings?.length) setSelectedId((drawings.find((d) => d.status === 'ready') ?? drawings[0]).id);
  }, [drawings, selectedId]);

  // Poll while anything is preparing.
  const anyPreparing = drawings?.some((d) => d.status === 'preparing') ?? false;
  useEffect(() => {
    if (!anyPreparing) return;
    const h = setInterval(refreshList, POLL_MS);
    return () => clearInterval(h);
  }, [anyPreparing, refreshList]);

  const summary = drawings?.find((d) => d.id === selectedId) ?? null;
  const ready = summary?.status === 'ready';
  const detail = loadedDetail?.id === selectedId ? loadedDetail : null;
  const plan = detail ? planFor(detail, storey) : null;

  // Load the selected drawing once it is ready.
  useEffect(() => {
    if (!api || !selectedId || !ready) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetail(null);
    setDetailError(null);
    api
      .getDrawing(selectedId)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        setStorey(d.storeys[0] ?? null);
      })
      .catch((e) => live && setDetailError(`Could not load drawing: ${errText(e)}`));
    api
      .getReviews(selectedId)
      .then((r) => live && setReviews((m) => ({ ...m, [selectedId]: r })))
      .catch(() => {});
    api
      .getOverview(selectedId)
      .then((o) => setOverviews((m) => ({ ...m, [selectedId]: o })))
      .catch((e) => setOverviews((m) => ({ ...m, [selectedId]: { error: errText(e) } })));
    api
      .getSuggestions(selectedId)
      .then((q) => setSuggestions((m) => ({ ...m, [selectedId]: q })))
      .catch(() => setSuggestions((m) => ({ ...m, [selectedId]: [] })));
    return () => {
      live = false;
    };
  }, [api, selectedId, ready, reloadKey]);

  useEffect(() => {
    setTab('notes');
    setHoverRoom(null);
    setPinnedRoom(null);
    // only on drawing change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const drawingCards = (selectedId && cards[selectedId]) || [];
  const activeKey = selectedId ? (activeCard[selectedId] ?? null) : null;
  const active = drawingCards.find((c) => c.key === activeKey) ?? null;
  const drawingReviews = (selectedId && reviews[selectedId]) || [];

  const elements = useMemo(() => {
    if (!detail) return [];
    // What the reviewer added is shown and clickable like everything the extractor found.
    const rs = (selectedId && reviews[selectedId]) || [];
    const added = rs.filter((r) => r.action === 'add').map(addedElement);
    const shapes = new Map(rs.filter((r) => r.action === 'reshape').map((r) => [r.id, r]));
    const els = [...detail.drawing.elements.map((e) => (shapes.has(e.id) ? reshaped(e, shapes.get(e.id)!, detail.drawing) : e)), ...added];
    return detail.storeys.length && storey ? els.filter((e) => e.storey == null || e.storey === storey) : els;
  }, [detail, storey, reviews, selectedId]);

  const updateCard = (drawingId: string, key: string, patch: (c: Card) => Card) =>
    setCards((m) => ({ ...m, [drawingId]: (m[drawingId] ?? []).map((c) => (c.key === key ? patch(c) : c)) }));

  /** Show the storey holding the evidence (IFC), so selecting a card always shows something. */
  const focusEvidence = useCallback(
    (ids: number[]) => {
      if (!detail?.storeys.length || !ids.length) return;
      const idSet = new Set(ids);
      const on = new Set(detail.drawing.elements.filter((e) => idSet.has(e.id) && e.storey).map((e) => e.storey!));
      if (on.size && storey && !on.has(storey)) setStorey(detail.storeys.find((s) => on.has(s)) ?? storey);
    },
    [detail, storey],
  );

  const runAsk = async (drawingId: string, key: string, question: string, refreshing: boolean) => {
    if (!api) return;
    updateCard(drawingId, key, (c) => (refreshing ? { ...c, refreshing: true } : { ...c, status: 'loading', error: undefined }));
    try {
      // The notes before this one, oldest first: lets Gemini read follow-ups in context.
      const notes = [...(cardsRef.current[drawingId] ?? [])].reverse();
      const upTo = notes.findIndex((c) => c.key === key);
      const history = notes
        .slice(0, upTo < 0 ? notes.length : upTo)
        .filter((c) => c.answer?.text)
        .slice(-4)
        .map((c) => ({ question: c.question, answer: c.answer!.text }));
      const answer = await api.ask(drawingId, question, history);
      updateCard(drawingId, key, (c) => ({
        ...c,
        status: 'done',
        answer,
        refreshing: false,
        seenIds: [...new Set([...c.seenIds, ...answer.evidence_ids, ...answer.uncertain_ids])],
      }));
      return answer;
    } catch (e) {
      updateCard(drawingId, key, (c) => ({ ...c, status: 'error', refreshing: false, error: errText(e) }));
    }
  };

  const ask = async (question: string) => {
    if (!selectedId) return;
    const key = `c${++cardSeq}`;
    const drawingId = selectedId;
    setCards((m) => ({ ...m, [drawingId]: [{ key, question, status: 'loading', seenIds: [] }, ...(m[drawingId] ?? [])] }));
    setActiveCard((m) => ({ ...m, [drawingId]: key }));
    setTab('notes');
    setPinnedRoom(null);
    const a = await runAsk(drawingId, key, question, false);
    if (a) focusEvidence([...a.evidence_ids, ...a.uncertain_ids]);
  };

  const selectCard = (c: Card) => {
    if (!selectedId) return;
    setPinnedRoom(null);
    setActiveCard((m) => ({ ...m, [selectedId]: c.key }));
    if (c.answer) focusEvidence([...c.answer.evidence_ids, ...c.answer.uncertain_ids]);
    setPane('plan');
  };

  /** A fact from the overview opens as an answer card, exactly like asking it (no re-ask: the answer came with it). */
  const openFact = (f: OverviewFact) => {
    if (!selectedId) return;
    const drawingId = selectedId;
    const existing = (cards[drawingId] ?? []).find((c) => c.factKey === f.key);
    const key = existing?.key ?? `c${++cardSeq}`;
    if (!existing) {
      const card: Card = {
        key,
        question: f.question,
        status: 'done',
        answer: f.answer,
        factKey: f.key,
        seenIds: [...f.answer.evidence_ids, ...f.answer.uncertain_ids],
      };
      setCards((m) => ({ ...m, [drawingId]: [card, ...(m[drawingId] ?? [])] }));
    }
    setActiveCard((m) => ({ ...m, [drawingId]: key }));
    setPinnedRoom(null);
    setTab('notes');
    focusEvidence([...f.answer.evidence_ids, ...f.answer.uncertain_ids]);
    setPane('plan');
  };

  const clickRoom = (r: OverviewRoom) => {
    if (!selectedId) return;
    setActiveCard((m) => ({ ...m, [selectedId]: null }));
    setPinnedRoom((cur) => (cur === r.id ? null : r.id));
  };

  // Esc clears the active card and any picked room (the popover handles its own Esc).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !selectedId || document.querySelector('.popover')) return;
      setActiveCard((m) => ({ ...m, [selectedId]: null }));
      setPinnedRoom(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedId]);

  const prepare = async (id: string) => {
    if (!api) return;
    setDrawings((list) => list?.map((d) => (d.id === id ? { ...d, status: 'preparing' } : d)) ?? list);
    setSelectedId(id);
    try {
      await api.extractDrawing(id);
    } catch (e) {
      setListError(`Could not start extraction: ${errText(e)}`);
    }
    refreshList();
  };

  /** After any edit: re-ask the open question and refresh the schedule, so both include it. */
  const afterEdit = async (drawingId: string) => {
    // Every note on this drawing, not just the open one: an edit can change any count.
    await Promise.all((cards[drawingId] ?? []).filter((c) => c.status === 'done').map((c) => runAsk(drawingId, c.key, c.question, true)));
    api
      ?.getOverview(drawingId)
      .then((o) => setOverviews((m) => ({ ...m, [drawingId]: o })))
      .catch(() => {});
  };

  const review = async (el: Element, action: ReviewAction, type?: string) => {
    if (!api || !selectedId) return;
    const drawingId = selectedId;
    const r: Review = action === 'retype' ? { id: el.id, action, type } : { id: el.id, action };
    await api.postReview(drawingId, r);
    const wasAdded = el.id >= ADDED_ID_BASE;
    setReviews((m) => {
      const list = m[drawingId] ?? [];
      if (wasAdded && action === 'reject') return { ...m, [drawingId]: list.filter((x) => x.id !== el.id) }; // take the addition back
      if (wasAdded) return { ...m, [drawingId]: list.map((x) => (x.id === el.id && action === 'retype' ? { ...x, type } : x)) };
      return { ...m, [drawingId]: [...list.filter((x) => !(x.id === el.id && reviewGroup(x) === reviewGroup(r))), r] };
    });
    await afterEdit(drawingId);
  };

  /** Image plans: find the rooms again, then reload the drawing and re-ask its notes. */
  const redetectRooms = async () => {
    if (!api || !selectedId) return;
    const drawingId = selectedId;
    setRedetecting('Finding the rooms again…');
    try {
      const r = await api.redetectRooms(drawingId);
      setReloadKey((k) => k + 1);
      await afterEdit(drawingId);
      setRedetecting(`Done: ${r.with_outline} of ${r.rooms} rooms outlined.`);
    } catch (e) {
      setRedetecting(`Could not re-detect: ${errText(e)}`);
    }
    window.setTimeout(() => setRedetecting(null), 5000);
  };

  /** Move, resize or redraw a found or added element. */
  const reshape = async (el: Element, shape: { bbox?: [number, number, number, number]; polygon?: [number, number][] }) => {
    if (!api || !selectedId) return;
    const drawingId = selectedId;
    const r: Review = { id: el.id, action: 'reshape', ...shape };
    await api.postReview(drawingId, r);
    setReviews((m) => {
      const list = m[drawingId] ?? [];
      if (el.id >= ADDED_ID_BASE) return { ...m, [drawingId]: list.map((x) => (x.id === el.id ? { ...x, ...shape, ...(shape.bbox ? { polygon: undefined } : {}) } : x)) };
      return { ...m, [drawingId]: [...list.filter((x) => !(x.id === el.id && x.action === 'reshape')), r] };
    });
    await afterEdit(drawingId);
  };

  const addElement = async (n: NewElement) => {
    if (!api || !selectedId) return;
    const drawingId = selectedId;
    const res = await api.postReview(drawingId, { action: 'add', ...n, storey: n.storey ?? storey ?? undefined });
    if (res.review) setReviews((m) => ({ ...m, [drawingId]: [...(m[drawingId] ?? []), res.review!] }));
    await afterEdit(drawingId);
  };

  const reviewedCount = (c: Card) => {
    const seen = new Set(c.seenIds);
    return drawingReviews.filter((r) => seen.has(r.id)).length;
  };

  const activeAnswer = active?.answer && active.answer.value != null ? active.answer : null;
  const overviewEntry = selectedId ? overviews[selectedId] : undefined;
  const overview = overviewEntry && !('error' in overviewEntry) ? overviewEntry : null;
  const overviewError = overviewEntry && 'error' in overviewEntry ? overviewEntry.error : null;
  const highlightIds = pinnedRoom != null ? [pinnedRoom] : hoverRoom != null ? [hoverRoom] : [];
  const focus: Focus | null =
    pinnedRoom != null
      ? { key: `room:${pinnedRoom}`, ids: [pinnedRoom] }
      : activeAnswer && active
        ? { key: `card:${active.key}`, ids: [...activeAnswer.evidence_ids, ...activeAnswer.uncertain_ids] }
        : null;

  const title = summary ? drawingTitle(summary) : '';
  const stepRef = useRef<(by: number) => void>(() => {});
  const thread = [...drawingCards].reverse(); // oldest first, like a conversation
  const clearAnswer = () => {
    if (!selectedId) return;
    setActiveCard((m) => ({ ...m, [selectedId]: null }));
    setPinnedRoom(null);
  };

  // Keep the newest answer in view.
  // Keep the newest note in view, also when its answer arrives and the note grows.
  const threadState = drawingCards.map((c) => `${c.key}:${c.status}`).join(',');
  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [threadState, selectedId]);

  // [ and ] turn the sheet, as in a drawing viewer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest('input, textarea, select') || libraryOpen) return;
      if (e.key === '[' || e.key === ']') {
        e.preventDefault();
        stepRef.current(e.key === ']' ? 1 : -1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [libraryOpen]);

  const sheetNo = summary && drawings ? drawings.findIndex((d) => d.id === summary.id) + 1 : 0;
  stepRef.current = (by: number) => step(by);
  /** Previous or next sheet in the register order. */
  const step = (by: number) => {
    if (!drawings?.length) return;
    const i = drawings.findIndex((d) => d.id === selectedId);
    setSelectedId(drawings[(i + by + drawings.length) % drawings.length].id);
  };
  const kindBasis = summary ? basis(summary.read_from) : null;

  return (
    <div className="sheet">
      <Zones />
      <main className={`board pane-${pane}`}>
        <SheetIndex drawings={drawings} selectedId={selectedId} onSelect={setSelectedId} onOpenRegister={() => setLibraryOpen(true)} />
        <section className="field">
          {summary && detail && ready && !plan ? (
            <PlanNote note={detail.plan_note ?? 'No plan image is available for this drawing.'} credit={detail.credit ?? summary.credit} />
          ) : summary && detail && ready && plan ? (
            <PlanView
              drawingKey={`${detail.id}|${storey ?? ''}`}
              kind={detail.drawing.kind}
              plan={plan}
              imageUrl={plan.url}
              elements={elements}
              answer={activeAnswer}
              highlightIds={highlightIds}
              focus={focus}
              reviews={drawingReviews}
              credit={detail.credit ?? summary.credit}
              storeys={detail.storeys}
              storey={storey}
              onStorey={(s) => {
                setStorey(s);
                setPinnedRoom(null);
              }}
              showAll={showAll}
              onShowAll={setShowAll}
              reviewable={!!activeAnswer && !activeAnswer.exact}
              onReview={review}
              onClearAnswer={clearAnswer}
              onAsk={(q) => ask(q)}
              onAdd={addElement}
              onReshape={reshape}
            />
          ) : (
            <section className="stage stage-empty">
              {!conn || !drawings ? (
                <p className="field-msg">Connecting…</p>
              ) : !summary ? (
                <button type="button" className="ink-btn" onClick={() => setLibraryOpen(true)}>
                  Open the drawing register
                </button>
              ) : summary.status === 'ready' ? (
                <p className="field-msg">{detailError ?? 'Loading drawing…'}</p>
              ) : (
                <div className="field-card">
                  <div className="field-card-title">{title}</div>
                  <StatusBadge status={summary.status} />
                  {summary.status === 'not_extracted' ? (
                    <>
                      <p>Not read yet. Reading happens once; after that every question is a lookup.</p>
                      <button type="button" className="ink-btn ink-btn-solid" onClick={() => prepare(summary.id)}>
                        Read this drawing
                      </button>
                    </>
                  ) : summary.status === 'failed' ? (
                    <>
                      <p>This drawing can't be read yet.</p>
                      {summary.error && <p className="mono small">{summary.error}</p>}
                      <button type="button" className="ink-btn" onClick={() => prepare(summary.id)}>
                        Try again
                      </button>
                    </>
                  ) : (
                    <p>Reading elements, rooms and quantities. This happens once.</p>
                  )}
                </div>
              )}
            </section>
          )}
        </section>

        <aside className="strip">
          <div className="strip-tabs" role="tablist" aria-label="Sheet notes">
            {(
              [
                ['notes', 'Notes', thread.length],
                ['schedule', 'Schedule', overview?.facts.length ?? 0],
                ['rooms', 'Rooms', overview?.rooms.length ?? 0],
              ] as const
            ).map(([key, label, n]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'is-active' : ''} onClick={() => setTab(key)}>
                {label}
                {n > 0 && <sup>{n}</sup>}
              </button>
            ))}
          </div>

          <div className="strip-scroll">
            {!detail ? (
              <p className="sched-empty">{summary && !ready ? 'Schedules and notes appear once the drawing is read.' : ''}</p>
            ) : tab === 'notes' ? (
              <section className="notes">
                {thread.length === 0 ? (
                  <div className="notes-start">
                    <p className="notes-lede">Ask this drawing a question. The answer is marked on the plan, so you can check it.</p>
                    {(suggestions[selectedId ?? ''] ?? []).length > 0 && (
                      <ol className="starters">
                        {(suggestions[selectedId ?? ''] ?? []).map((q) => (
                          <li key={q}>
                            <button type="button" onClick={() => ask(q)}>
                              {q}
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                ) : (
                  thread.map((c, i) => (
                    <AnswerCard
                      key={c.key}
                      card={c}
                      index={i + 1}
                      active={c.key === activeKey}
                      reviewedCount={reviewedCount(c)}
                      onSelect={() => selectCard(c)}
                      onRetry={() => selectedId && runAsk(selectedId, c.key, c.question, false)}
                    />
                  ))
                )}
                <div ref={threadEnd} />
              </section>
            ) : (
              <OverviewPanel
                onRedetect={detail.drawing.kind === 'raster' ? redetectRooms : undefined}
                redetecting={redetecting}
                part={tab === 'schedule' ? 'quantities' : 'rooms'}
                overview={overview}
                error={overviewError}
                activeFactKey={active?.factKey ?? null}
                highlightedRoom={pinnedRoom ?? hoverRoom}
                storey={detail.storeys.length ? storey : null}
                onFact={openFact}
                onRoomHover={setHoverRoom}
                onRoomClick={clickRoom}
              />
            )}
          </div>

          <QuestionBox
            disabled={!detail || !ready}
            disabledReason={summary?.status === 'failed' ? 'Not available for this drawing yet' : summary && !ready ? 'Read this drawing first' : 'Pick a drawing first'}
            suggestions={[]}
            nextNo={thread.length + 1}
            onAsk={(q) => ask(q)}
          />

          <TitleBlock
            title={title}
            no={summary ? dwgNo(summary) : '—'}
            basis={kindBasis}
            format={summary ? formatName(summary.read_from) : '—'}
            sheet={sheetNo}
            of={drawings?.length ?? 0}
            onPrev={() => step(-1)}
            onNext={() => step(1)}
            onRegister={() => setLibraryOpen(true)}
          />
        </aside>
      </main>

      <nav className="pane-nav" aria-label="Panels">
        {(
          [
            ['plan', 'Drawing'],
            ['ask', thread.length ? `Notes ${thread.length}` : 'Notes'],
          ] as const
        ).map(([key, label]) => (
          <button key={key} type="button" className={pane === key ? 'is-active' : ''} aria-pressed={pane === key} onClick={() => setPane(key)}>
            {label}
          </button>
        ))}
        <button type="button" onClick={() => setLibraryOpen(true)}>
          Register
        </button>
      </nav>

      {libraryOpen && (
        <Library
          drawings={drawings}
          error={listError}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id);
            setPane('plan');
          }}
          onPrepare={prepare}
          onClose={() => setLibraryOpen(false)}
        />
      )}
    </div>
  );
}

/** Zone letters and numbers along the sheet border, as on any drawing sheet. */
function Zones() {
  const letters = 'ABCDEFGH'.split('');
  const numbers = [1, 2, 3, 4, 5, 6];
  return (
    <div className="zones" aria-hidden>
      {(['top', 'bottom'] as const).map((side) => (
        <div key={side} className={`zone-row zone-${side}`}>
          {letters.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      ))}
      {(['left', 'right'] as const).map((side) => (
        <div key={side} className={`zone-col zone-${side}`}>
          {numbers.map((n) => (
            <span key={n}>{n}</span>
          ))}
        </div>
      ))}
    </div>
  );
}

/** The sheet's title block, kept to what identifies the sheet and how far to trust it. */
function TitleBlock(p: {
  title: string;
  no: string;
  basis: 'exact' | 'estimate' | 'text' | null;
  format: string;
  sheet: number;
  of: number;
  onPrev: () => void;
  onNext: () => void;
  onRegister: () => void;
}) {
  const basisText = p.basis === 'exact' ? 'Exact' : p.basis === 'estimate' ? 'Estimate' : p.basis === 'text' ? 'Text only' : '—';
  return (
    <div className="tb">
      <div className="tb-cell tb-title">
        <span className="tb-k">Drawing</span>
        <button type="button" className="tb-v tb-name" onClick={p.onRegister} title="Open the full register">
          {p.title || 'No drawing'}
        </button>
      </div>
      <div className="tb-cell tb-nav">
        <button type="button" onClick={p.onPrev} aria-label="Previous sheet" title="Previous sheet  [">
          ‹
        </button>
        <span className="mono">
          {p.sheet ? String(p.sheet).padStart(3, '0') : '—'}
          <span className="tb-of">/{p.of}</span>
        </span>
        <button type="button" onClick={p.onNext} aria-label="Next sheet" title="Next sheet  ]">
          ›
        </button>
      </div>
      <div className="tb-cell">
        <span className="tb-k">Dwg no.</span>
        <span className="tb-v mono">{p.no}</span>
      </div>
      <div className="tb-cell">
        <span className="tb-k">Read from</span>
        <span className="tb-v">{p.format}</span>
      </div>
      <div className={`tb-cell tb-basis basis-${p.basis === 'exact' ? 'exact' : 'est'}`}>
        <span className="tb-k">Basis</span>
        <span className="tb-v">{basisText}</span>
      </div>
    </div>
  );
}
