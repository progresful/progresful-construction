// The API client the app uses. Real HTTP (API.md) or the in-memory mock, chosen once:
//   VITE_MOCK=1  -> always mock
//   VITE_MOCK=0  -> always real
//   unset        -> real, falling back to mock if GET /api/drawings is unreachable.
import type { AskResponse, DrawingDetail, DrawingSummary, Overview, Review } from './types';
import * as mock from './mock';

export interface Api {
  listDrawings(): Promise<DrawingSummary[]>;
  getDrawing(id: string): Promise<DrawingDetail>;
  extractDrawing(id: string): Promise<void>;
  /** history: earlier questions and answers on this drawing, oldest first, for follow-ups. */
  ask(drawingId: string, question: string, history?: { question: string; answer: string }[]): Promise<AskResponse>;
  getReviews(id: string): Promise<Review[]>;
  getOverview(id: string): Promise<Overview>;
  /** Image plans: find the rooms again, more carefully. */
  redetectRooms(id: string): Promise<{ ok: true; rooms: number; with_outline: number }>;
  getSuggestions(id: string): Promise<string[]>;
  postReview(id: string, review: Omit<Review, 'id'> & { id?: number }): Promise<{ ok: true; id?: number; review?: Review }>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  });
  if (!res.ok) {
    // FastAPI errors are {"detail": "..."}; 409 means "not extracted yet".
    let detail = '';
    try {
      const body = await res.text();
      try {
        const j = JSON.parse(body);
        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
      } catch {
        detail = body.slice(0, 300);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(detail || `${res.status} ${res.statusText}`, res.status);
  }
  const ct = res.headers.get('content-type') ?? '';
  if (!ct.includes('json')) throw new ApiError(`Expected JSON from ${path}, got ${ct || 'nothing'}`, res.status);
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const realApi: Api = {
  listDrawings: () => http('/api/drawings'),
  getDrawing: (id) => http(`/api/drawings/${enc(id)}`),
  extractDrawing: async (id) => {
    await http(`/api/drawings/${enc(id)}/extract`, { method: 'POST' });
  },
  ask: (drawing_id, question, history) => http('/api/ask', { method: 'POST', body: JSON.stringify({ drawing_id, question, history }) }),
  getReviews: (id) => http(`/api/drawings/${enc(id)}/reviews`),
  getOverview: (id) => http(`/api/drawings/${enc(id)}/overview`),
  redetectRooms: (id) => http(`/api/drawings/${enc(id)}/rooms/redetect`, { method: 'POST' }),
  getSuggestions: (id) => http(`/api/drawings/${enc(id)}/suggestions`),
  postReview: (id, review) => http(`/api/drawings/${enc(id)}/reviews`, { method: 'POST', body: JSON.stringify(review) }),
};

export const mockApi: Api = mock;

export type ApiMode = 'real' | 'mock';

/** Pick the implementation once at startup. */
export async function connect(): Promise<{ api: Api; mode: ApiMode; reason?: string }> {
  const flag = import.meta.env.VITE_MOCK as string | undefined;
  if (flag === '1' || flag === 'true') return { api: mockApi, mode: 'mock', reason: 'VITE_MOCK=1' };
  if (flag === '0' || flag === 'false') return { api: realApi, mode: 'real' };
  try {
    await realApi.listDrawings();
    return { api: realApi, mode: 'real' };
  } catch (e) {
    return { api: mockApi, mode: 'mock', reason: `API unreachable (${e instanceof Error ? e.message.slice(0, 80) : e})` };
  }
}
