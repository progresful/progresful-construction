// In-memory mock of the API in API.md. Same function signatures as client.ts's real implementation.
import type { Answer, AskResponse, DrawingDetail, DrawingSummary, Element, Overview, OverviewFact, Review } from './types';
import { createMockEntries, type MockEntry } from './mockData';
import { applyReviews, countAnswer, sumAnswer } from '../lib/estimate';

const entries: MockEntry[] = createMockEntries();
const details = new Map<string, DrawingDetail>();
const reviews = new Map<string, Review[]>();
const EXTRACT_MS = 3000;

const delay = <T>(v: T, ms = 250 + Math.random() * 250) => new Promise<T>((res) => setTimeout(() => res(v), ms));
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

function entry(id: string): MockEntry {
  const e = entries.find((x) => x.summary.id === id);
  if (!e) throw new Error(`404: no drawing ${id}`);
  return e;
}

function detail(id: string): DrawingDetail {
  const e = entry(id);
  if (e.summary.status !== 'ready') throw new Error('Drawing is not extracted yet; POST /extract first');
  let d = details.get(id);
  if (!d) {
    d = e.build();
    details.set(id, d);
  }
  return d;
}

const TITLES: Record<string, [string, string]> = {
  ifc_models__demo_house: ['Demo house · two storeys', 'IFC models · IFC · exact'],
  'cubicasa5k__colorful-demo': ['CubiCasa-style plan (demo)', 'CubiCasa5K · image · estimate'],
  swiss_dwellings__site0001_bldg0001_floor0001: ['Swiss apartment floor · site 0001', 'Swiss Dwellings · DXF · exact'],
  ifc_bench__nd_demo: ['NoDerivatives model (demo)', 'IFC-Bench · IFC · exact'],
  'cubicasa5k__high_quality-demo': ['CubiCasa-style plan 2 (demo)', 'CubiCasa5K · image · estimate'],
};

export async function listDrawings(): Promise<DrawingSummary[]> {
  return delay(
    entries.map((e) => {
      const s = clone(e.summary);
      [s.title, s.subtitle] = TITLES[s.id] ?? [null, null];
      // Thumbnail only once extracted and when a plan may be shown (API.md).
      s.thumb_url = s.status === 'ready' ? (detail(s.id).plan?.url ?? null) : null;
      return s;
    }),
    120,
  );
}

const STANDARD: [string, string, string][] = [
  ['window', 'Windows', 'How many windows are shown on this floor plan?'],
  ['door', 'Doors', 'How many doors are shown on this floor plan?'],
  ['room', 'Rooms', 'How many rooms are there?'],
  ['bedroom', 'Bedrooms', 'How many bedrooms are there?'],
  ['wc', 'Toilets', 'How many toilets (WC) are there?'],
  ['sink', 'Sinks', 'How many sinks are there?'],
  ['shower', 'Showers', 'How many showers are there?'],
  ['storey', 'Storeys', 'How many storeys does the building have?'],
  ['total_area', 'Total area', 'What is the total area?'],
  ['apartment_area:A', 'Apartment A', 'What is the area of apartment A?'],
  ['apartment_area:B', 'Apartment B', 'What is the area of apartment B?'],
];

export async function getOverview(id: string): Promise<Overview> {
  const det = detail(id);
  const d = applyReviews(det.drawing, reviews.get(id) ?? []);
  const facts: OverviewFact[] = [];
  for (const [key, label, question] of STANDARD) {
    const a = answerQuestion(d.elements, question);
    if (a.value == null) continue;
    if (a.unit === 'count' && a.value === 0) continue;
    facts.push({ key, label, question, answer: { ...a, text: sentence(a, question, d.elements), cost_known: true } });
  }
  const rooms = d.elements
    .filter((e) => e.type === 'room')
    .map((e) => ({
      id: e.id,
      label: e.label,
      number: e.number,
      type: e.type,
      room_type: e.room_type,
      area_m2: e.quantities?.area_m2 ?? null,
      storey: e.storey,
      exact: e.exact && ['quantity_set', 'label'].includes(e.quantity_source?.area_m2 ?? ''),
    }));
  return delay({ kind: det.drawing.kind, exact: d.elements.every((e) => e.exact), facts, rooms }, 500);
}

export async function getSuggestions(id: string): Promise<string[]> {
  const kind = detail(id).drawing.kind;
  const s: Record<string, string[]> = {
    ifc: ['How many storeys?', 'Area of the Kitchen?', 'Doors on the ground floor?', 'Wie viele Fenster?'],
    raster: ['How many windows?', 'Kuinka monta ikkunaa?', 'How many bedrooms?', 'Area of the sauna?', 'How many stairs?'],
    dxf: ['How many windows?', 'Area of apartment B?', 'Wie viele Zimmer hat Wohnung A?', 'Combien de portes ?'],
  };
  return delay(s[kind] ?? s.ifc, 200);
}

export async function getDrawing(id: string): Promise<DrawingDetail> {
  return delay(clone(detail(id)));
}

export async function extractDrawing(id: string): Promise<void> {
  const e = entry(id);
  if (e.summary.status === 'not_extracted' || e.summary.status === 'failed') {
    e.summary.status = 'preparing';
    e.summary.error = null;
    setTimeout(() => {
      e.summary.status = e.failWith ? 'failed' : 'ready';
      e.summary.error = e.failWith ?? null;
    }, e.failWith ? EXTRACT_MS / 2 : EXTRACT_MS);
  }
  return delay(undefined, 150);
}

export async function getReviews(id: string): Promise<Review[]> {
  return delay(clone(reviews.get(id) ?? []), 80);
}

export async function postReview(id: string, review: Omit<Review, 'id'> & { id?: number }): Promise<{ ok: true; id?: number; review?: Review }> {
  entry(id);
  const existing = reviews.get(id) ?? [];
  if (review.action === 'add') {
    const r = { ...clone(review), id: Math.max(999_999, ...existing.filter((x) => x.action === 'add').map((x) => x.id)) + 1 } as Review;
    reviews.set(id, [...existing, r]);
    return delay({ ok: true as const, id: r.id, review: r }, 150);
  }
  const list = existing.filter((r) => r.id !== review.id);
  if (!(review.action === 'reject' && existing.some((r) => r.id === review.id && r.action === 'add'))) list.push(clone(review) as Review);
  reviews.set(id, list);
  return delay({ ok: true as const }, 150);
}

export async function ask(drawingId: string, question: string): Promise<AskResponse> {
  const d = applyReviews(detail(drawingId).drawing, reviews.get(drawingId) ?? []);
  const answer = answerQuestion(d.elements, question);
  return delay({ ...answer, text: sentence(answer, question, d.elements), cost_known: true }, 450 + Math.random() * 400);
}

// ---------------------------------------------------------------------------------------------
// A toy question mapper (the real one is constructor/mapper.py). Keyword based, multilingual-ish.
// ---------------------------------------------------------------------------------------------

type Lang = 'en' | 'fi' | 'de' | 'fr';

const ELEMENT_WORDS: [string, RegExp][] = [
  ['window', /window|ikkun|fenster|fen[eê]tre|finestr|vindue|aken/],
  ['door', /door|\bov(i|ea|ia|et)\b|t[üu]r(e|en)?\b|porte|\bport[ae]\b|d[øo]r(e|en)?\b|uks/],
  ['wc', /\bwc\b|toilet|vessa|wc-istuin/],
  ['sink', /sink|allas|altaa|lavabo|waschbecken|lavandino/],
  ['shower', /shower|suihku|dusche|douche|doccia/],
  ['bathtub', /bath ?tub|kylpyamme|badewanne|baignoire|vasca/],
];

const ROOM_TYPE_WORDS: [string, RegExp][] = [
  ['bedroom', /bedroom|makuuhuone|schlafzimmer|chambre/],
  ['sauna', /sauna/],
  ['kitchen', /kitchen|keitti|küche|kuche|cuisine/],
  ['bathroom', /bathroom|kylpyhuone|badezimmer/],
  ['balcony', /balcon|parveke|balkon/],
];

function lang(q: string): Lang {
  if (/kuinka|montako|onko|mikä|paljonko|ikkun|huone|pinta-ala|pohjapiir/.test(q)) return 'fi';
  if (/\bwie\b|viele|gibt es|fläche|wohnung|zimmer/.test(q)) return 'de';
  if (/combien|quelle|surface|y a-t-il/.test(q)) return 'fr';
  return 'en';
}

const NONE: Answer = {
  template: null,
  value: null,
  unit: null,
  exact: false,
  params: {},
  range: null,
  evidence_ids: [],
  uncertain_ids: [],
  cost_usd: 0,
  fallback: false,
};

function answerQuestion(elements: Element[], question: string): Answer {
  const q = question.toLowerCase();
  const cost = 0.00018;
  const withCost = (a: Answer | null): Answer => ({ ...(a ?? NONE), cost_usd: a?.cost_usd || cost });

  const storeyNames = [...new Set(elements.filter((e) => e.type === 'storey').map((e) => e.storey).filter(Boolean))] as string[];
  const storey = storeyNames.find((s) => q.includes(s.toLowerCase()));
  const apartment = /(?:apartment|wohnung|asunto|appartement)\s+([a-z])\b/.exec(q)?.[1]?.toUpperCase();
  const inScope = (e: Element) =>
    (!storey || e.storey === storey) && (!apartment || e.apartment === apartment) && e.type !== 'storey';
  const params: Record<string, unknown> = {};
  if (storey) params.storey = storey;
  if (apartment) params.apartment = apartment;

  const isArea = /\barea\b|pinta-ala|neliö|fläche|surface|superficie|m2|m²|how big|how large/.test(q);
  const isCount = /how many|number of|count|kuinka monta|montako|wie viele|anzahl|combien|quanti|hvor mange|mitu/.test(q);

  if (isArea) {
    const rooms = elements.filter((e) => e.type === 'room' && inScope(e));
    // A named room: label as written, then room type keyword.
    const byLabel = rooms.filter((r) => r.label && r.label.length >= 2 && new RegExp(`\\b${escapeRe(r.label.toLowerCase())}\\b`).test(q));
    const rt = ROOM_TYPE_WORDS.find(([, re]) => re.test(q))?.[0];
    const named = byLabel.length ? byLabel : rt ? rooms.filter((r) => r.room_type === rt) : [];
    if (byLabel.length || rt) {
      if (named.length !== 1) return withCost(null); // ambiguous: refuse rather than guess
      const p = { ...params, ...(byLabel.length ? { name: named[0].label } : { room_type: rt }) };
      return withCost(sumAnswer(named, 'area_m2', 'm2', 'room_area', p));
    }
    if (apartment) return withCost(sumAnswer(rooms, 'area_m2', 'm2', 'apartment_area', params));
    return withCost(sumAnswer(rooms.filter((r) => !r.outdoor), 'area_m2', 'm2', 'total_area', params));
  }

  // Whole-image estimate (no marks), like the vision fallback on raster drawings.
  if (/stair|portaat|portai|treppe|escalier/.test(q) && isCount && !elements.some((e) => e.type === 'stair') && elements.some((e) => e.source.includes('vlm'))) {
    return withCost({ ...NONE, template: 'count_elements', params: { element: 'stair' }, value: 1, unit: 'count', range: [1, 2], cost_usd: 0.0021 });
  }
  const element = ELEMENT_WORDS.find(([, re]) => re.test(q))?.[0];
  if (element && (isCount || /\bis there|are there|onko|gibt es|y a-t-il/.test(q))) {
    return withCost(countAnswer(elements.filter((e) => e.type === element && inScope(e)), 'count_elements', { ...params, element }));
  }
  if (isCount && /storey|stories|floors|levels|kerro|geschoss|stockwerk|étage|etage|piani|etager|korrus/.test(q)) {
    const storeys = elements.filter((e) => e.type === 'storey');
    if (!storeys.length) return withCost(null);
    return withCost(countAnswer(storeys, 'count_storeys', params));
  }
  const rt = ROOM_TYPE_WORDS.find(([, re]) => re.test(q))?.[0];
  if (isCount && rt) {
    return withCost(countAnswer(elements.filter((e) => e.type === 'room' && e.room_type === rt && inScope(e)), 'count_rooms', { ...params, room_type: rt }));
  }
  if (isCount && /room|huone|zimmer|pièce|piece|stanz|værelse|rum/.test(q)) {
    return withCost(countAnswer(elements.filter((e) => e.type === 'room' && !e.outdoor && inScope(e)), 'count_rooms', { ...params, scope: 'numbered_indoor' }));
  }
  return withCost(null);
}

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ---------------------------------------------------------------------------------------------
// The ready-made sentence, in the language of the question.
// ---------------------------------------------------------------------------------------------

const NOUNS: Record<Lang, Record<string, [string, string]>> = {
  en: {
    window: ['window', 'windows'],
    door: ['door', 'doors'],
    wc: ['WC', 'WCs'],
    sink: ['sink', 'sinks'],
    shower: ['shower', 'showers'],
    bathtub: ['bathtub', 'bathtubs'],
    storey: ['storey', 'storeys'],
    room: ['room', 'rooms'],
    bedroom: ['bedroom', 'bedrooms'],
    stair: ['stair', 'stairs'],
  },
  fi: {
    window: ['ikkuna', 'ikkunaa'],
    door: ['ovi', 'ovea'],
    wc: ['WC', 'WC:tä'],
    sink: ['allas', 'allasta'],
    shower: ['suihku', 'suihkua'],
    bathtub: ['kylpyamme', 'kylpyammetta'],
    storey: ['kerros', 'kerrosta'],
    room: ['huone', 'huonetta'],
    bedroom: ['makuuhuone', 'makuuhuonetta'],
  },
  de: {
    window: ['Fenster', 'Fenster'],
    door: ['Tür', 'Türen'],
    storey: ['Geschoss', 'Geschosse'],
    room: ['Zimmer', 'Zimmer'],
    bedroom: ['Schlafzimmer', 'Schlafzimmer'],
  },
  fr: {
    window: ['fenêtre', 'fenêtres'],
    door: ['porte', 'portes'],
    storey: ['étage', 'étages'],
    room: ['pièce', 'pièces'],
    bedroom: ['chambre', 'chambres'],
  },
};

function noun(l: Lang, key: string, n: number): string {
  const pair = NOUNS[l][key] ?? NOUNS.en[key] ?? [key, key + 's'];
  return n === 1 ? pair[0] : pair[1];
}

function sentence(a: Answer, question: string, elements: Element[]): string {
  const l = lang(question.toLowerCase());
  if (a.value == null) {
    return {
      en: "I can't answer this from the drawing yet.",
      fi: 'En pysty vielä vastaamaan tähän piirustuksen perusteella.',
      de: 'Das kann ich aus der Zeichnung noch nicht beantworten.',
      fr: 'Je ne peux pas encore répondre à cela à partir du plan.',
    }[l];
  }
  const nC = a.evidence_ids.length;
  const nU = a.uncertain_ids.length;
  if (a.unit === 'count') {
    if (a.evidence_ids.length === 0 && a.uncertain_ids.length === 0 && !a.exact) {
      return `About ${a.value} ${noun(l, String(a.params.element), Number(a.value))}, estimated from the whole image (no marks).`;
    }
    const key = a.template === 'count_storeys' ? 'storey' : a.template === 'count_rooms' ? (a.params.room_type === 'bedroom' ? 'bedroom' : 'room') : String(a.params.element);
    const v = Number(a.value);
    const what = `${v} ${noun(l, key, v)}`;
    if (a.exact) {
      return {
        en: `${what}${a.params.storey ? ` on ${a.params.storey}` : ''}, read from the model. Highlighted on the plan.`,
        fi: `${what}, luettu mallista. Korostettu piirustuksessa.`,
        de: `${what}, aus dem Modell gelesen. Im Plan markiert.`,
        fr: `${what}, lu dans le modèle. Surligné sur le plan.`,
      }[l];
    }
    const [lo, hi] = a.range ?? [nC, nC + nU];
    if (lo === hi) {
      return {
        en: `${what} (estimate, all ${nC} confirmed or reviewed). Marked on the plan.`,
        fi: `${what} (arvio, kaikki ${nC} varmistettu). Merkitty piirustukseen.`,
        de: `${what} (Schätzung, alle ${nC} bestätigt). Im Plan markiert.`,
        fr: `${what} (estimation, ${nC} confirmés). Marqués sur le plan.`,
      }[l];
    }
    return {
      en: `${what} (estimate, ${lo} to ${hi}). ${nC} confirmed, ${nU} uncertain, marked on the plan.`,
      fi: `${what} (arvio, ${lo}–${hi}). ${nC} varmaa, ${nU} epävarmaa, merkitty piirustukseen.`,
      de: `${what} (Schätzung, ${lo} bis ${hi}). ${nC} sicher, ${nU} unsicher, im Plan markiert.`,
      fr: `${what} (estimation, ${lo} à ${hi}). ${nC} confirmés, ${nU} incertains, marqués sur le plan.`,
    }[l];
  }
  const v = Number(a.value).toLocaleString(l === 'en' ? 'en-GB' : l, { maximumFractionDigits: 2 });
  const ids = new Set([...a.evidence_ids, ...a.uncertain_ids]);
  const rooms = elements.filter((e) => ids.has(e.id));
  const subject =
    a.template === 'room_area' && rooms.length === 1
      ? rooms[0].label ?? 'The room'
      : a.template === 'apartment_area'
        ? `Apartment ${a.params.apartment}`
        : `${rooms.length} rooms${a.params.storey ? ` on ${a.params.storey}` : ''}`;
  const src = a.exact ? 'from the model quantity set' : rooms.some((r) => r.quantity_source?.area_m2 === 'geometry') ? 'computed from the drawn outline' : 'read from the labels printed on the plan';
  if (l === 'fi') return `${subject}: ${v} m²${a.exact ? '' : ' (arvio)'}.`;
  if (l === 'de') return `${subject}: ${v} m²${a.exact ? '' : ' (Schätzung)'}.`;
  return `${subject}: ${v} m²${a.exact ? '' : ' (estimate)'}, ${src}.`;
}

export async function redetectRooms(id: string): Promise<{ ok: true; rooms: number; with_outline: number }> {
  entry(id);
  return delay({ ok: true as const, rooms: 0, with_outline: 0 }, 400);
}
