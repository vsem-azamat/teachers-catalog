import { retrieveRawInitData } from '@tma.js/sdk-react';

import type {
  ContactStart,
  FeedRequest,
  HelperDetail,
  HelperUpsert,
  HelpRequest,
  Home,
  Institution,
  IntroResult,
  LanguageOption,
  Me,
  MeUpdate,
  MyHelper,
  ParseResult,
  Placement,
  RequestCreate,
  RequestResponse,
  ResponseCreate,
  SearchParams,
  SearchResult,
  ServiceType,
  Subject,
} from './types';

/**
 * Base URL for the API.
 *
 * Empty by default, which makes every call same-origin and lets the Vite dev
 * proxy (and, in production, the FastAPI process serving the built app) handle
 * it. Since 20 July 2026 Telegram only allows Mini App API calls from the app's
 * own origin, so a cross-origin base is the exception, not the rule.
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const API_PREFIX = '/api/v1';

/** Thrown for any non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * The caller is not (or no longer) an authenticated Telegram user.
 *
 * initData carries a signature that Telegram time-limits, so a long-lived
 * session will eventually start failing. The only cure is a reload of the Mini
 * App, which is a decision for the UI, not for this module.
 */
export class UnauthorizedError extends ApiError {
  constructor(detail: unknown) {
    super(401, detail, 'Telegram init data was rejected');
    this.name = 'UnauthorizedError';
  }
}

/** Listeners notified once per 401, so the shell can prompt for a reload. */
const unauthorizedListeners = new Set<(error: UnauthorizedError) => void>();

export function onUnauthorized(
  listener: (error: UnauthorizedError) => void,
): VoidFunction {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/**
 * The `tma` scheme is the convention the Telegram SDKs and the API agree on.
 * initData must never travel as a query parameter — it would end up in proxy
 * and access logs.
 */
function authHeader(): Record<string, string> {
  let raw: string | undefined;
  try {
    raw = retrieveRawInitData();
  } catch {
    // Outside Telegram and without the dev mock there is nothing to send. Let
    // the request go out unauthenticated and surface the 401 honestly.
    raw = undefined;
  }
  return raw ? { Authorization: `tma ${raw}` } : {};
}

type QueryValue = string | number | boolean | null | undefined | (string | number)[];

function toQuery(params: Record<string, QueryValue> | undefined): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      // FastAPI reads repeated keys as a list; a comma-joined string is a
      // single value and would silently become one bogus language code.
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal } = options;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...authHeader(),
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(`${BASE_URL}${API_PREFIX}${path}${toQuery(query)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (response.status === 204) return undefined as T;

  const payload = await readBody(response);

  if (!response.ok) {
    if (response.status === 401) {
      const error = new UnauthorizedError(payload);
      for (const listener of unauthorizedListeners) listener(error);
      throw error;
    }
    throw new ApiError(response.status, payload, detailOf(payload));
  }

  return payload as T;
}

async function readBody(response: Response): Promise<unknown> {
  const type = response.headers.get('content-type') ?? '';
  if (!type.includes('application/json')) {
    const text = await response.text();
    return text || null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function detailOf(payload: unknown): string | undefined {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const { detail } = payload as { detail: unknown };
    if (typeof detail === 'string') return detail;
  }
  return undefined;
}

// ── endpoints ───────────────────────────────────────────────────────────
//
// Written by hand for now. `pnpm api:generate` will eventually produce these
// from the OpenAPI document; until then keep the signatures in step with
// apps/api/src/konnekt/api/v1/routes.py.

export const api = {
  /** The whole home screen in one response. */
  getHome: (signal?: AbortSignal) => request<Home>('/home', { signal }),

  getServiceTypes: (signal?: AbortSignal) =>
    request<ServiceType[]>('/taxonomy/service-types', { signal }),

  /** One level of the subject tree. Pass no parent for the roots. */
  getSubjects: (
    params: { parent_id?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) => request<Subject[]>('/taxonomy/subjects', { query: { ...params }, signal }),

  /** Fuzzy search over the subject tree — "matan" and "матан" both work. */
  searchSubjects: (q: string, limit?: number, signal?: AbortSignal) =>
    request<Subject[]>('/taxonomy/subjects', { query: { q, limit }, signal }),

  getInstitutions: (signal?: AbortSignal) =>
    request<Institution[]>('/taxonomy/institutions', { signal }),

  getLanguages: (signal?: AbortSignal) =>
    request<LanguageOption[]>('/taxonomy/languages', { signal }),

  /** Read a sentence and show back what we made of it. */
  parseQuery: (text: string, signal?: AbortSignal) =>
    request<ParseResult>('/search/parse', { method: 'POST', body: { text }, signal }),

  search: (params: SearchParams = {}, signal?: AbortSignal) =>
    request<SearchResult>('/search', { query: { ...params }, signal }),

  getHelper: (userId: number, signal?: AbortSignal) =>
    request<HelperDetail>(`/helpers/${userId}`, { signal }),

  /** Record that a conversation is starting, and get where to continue it. */
  startContact: (userId: number) =>
    request<ContactStart>(`/helpers/${userId}/contact`, { method: 'POST' }),

  getPlacements: (
    params: { slot: string; service_type?: string; subject_id?: number },
    signal?: AbortSignal,
  ) => request<Placement[]>('/placements', { query: { ...params }, signal }),

  registerPlacementClick: (placementId: number) =>
    request<void>(`/placements/${placementId}/click`, { method: 'POST' }),

  getMe: (signal?: AbortSignal) => request<Me>('/me', { signal }),

  patchMe: (payload: MeUpdate, signal?: AbortSignal) =>
    request<Me>('/me', { method: 'PATCH', body: payload, signal }),

  /** Alias with the name the mutation hooks read better with. */
  updateMe: (payload: MeUpdate) => request<Me>('/me', { method: 'PATCH', body: payload }),

  // ── requests ──────────────────────────────────────────────────────────

  getRequests: (signal?: AbortSignal) => request<HelpRequest[]>('/requests', { signal }),

  createRequest: (payload: RequestCreate) =>
    request<HelpRequest>('/requests', { method: 'POST', body: payload }),

  closeRequest: (requestId: number) =>
    request<HelpRequest>(`/requests/${requestId}/close`, { method: 'POST' }),

  /** Open requests worth answering. Helpers only; 403 for everyone else. */
  getRequestFeed: (signal?: AbortSignal) =>
    request<FeedRequest[]>('/requests/feed', { signal }),

  respondToRequest: (requestId: number, payload: ResponseCreate) =>
    request<RequestResponse>(`/requests/${requestId}/respond`, {
      method: 'POST',
      body: payload,
    }),

  /** Who answered. The author of the request only. */
  getResponses: (requestId: number, signal?: AbortSignal) =>
    request<RequestResponse[]>(`/requests/${requestId}/responses`, { signal }),

  acceptResponse: (responseId: number) =>
    request<RequestResponse>(`/responses/${responseId}/accept`, { method: 'POST' }),

  declineResponse: (responseId: number) =>
    request<RequestResponse>(`/responses/${responseId}/decline`, { method: 'POST' }),

  // ── becoming a helper ─────────────────────────────────────────────────

  /** Read a free-text introduction into a draft profile. Saves nothing. */
  readIntro: (text: string, signal?: AbortSignal) =>
    request<IntroResult>('/helper/intro', { method: 'POST', body: { text }, signal }),

  /** The caller's own profile, whatever state it is in. Never 404s. */
  getMyHelper: (signal?: AbortSignal) => request<MyHelper>('/helper', { signal }),

  saveHelper: (payload: HelperUpsert) =>
    request<Me>('/helper', { method: 'PUT', body: payload }),
};

export type Api = typeof api;
