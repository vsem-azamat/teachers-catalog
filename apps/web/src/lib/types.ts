/**
 * Hand-written mirrors of the API's Pydantic schemas.
 *
 * These are a stopgap. `pnpm api:generate` will replace them with types
 * generated from the live OpenAPI document (see `openapi-ts.config.ts`), at
 * which point this file should shrink to whatever the generator cannot express.
 *
 * Two conventions carried over from the API and worth remembering:
 *
 * - **Data is localised server-side, chrome is not.** Subject, faculty and
 *   service-type names arrive already in the caller's language. Sentences the
 *   interface composes arrive as a {@link Phrase} — a code plus params — and
 *   this app renders them, because plural agreement in Czech, Russian and
 *   Ukrainian belongs in the presentation layer.
 * - **Screens are assembled server-side.** `/home` returns the whole home
 *   screen in one response rather than making a phone on mobile data issue six
 *   requests.
 */

export type UiLang = 'ru' | 'cs' | 'en' | 'uk';

export type WorkFormat = 'online' | 'offline' | 'both';

export type PriceUnit =
  | 'hour'
  | 'lesson'
  | 'work'
  | 'day'
  | 'week'
  | 'month'
  | 'semester'
  | 'item'
  | 'negotiable';

/** A sentence for the client to render, not a sentence. */
export interface Phrase {
  code: string;
  params: Record<string, string | number>;
}

export interface Price {
  amount: number | null;
  currency: string;
  unit: PriceUnit;
}

/**
 * Enough to draw the little circle without fetching anything. Telegram avatar
 * URLs expire, so the monogram is the fallback rather than a broken image.
 */
export interface Avatar {
  /** The user this face belongs to; a stable React key for a list of them. */
  id: number;
  initials: string;
  /** 0-5, derived from the user id so a person keeps their colour. */
  tone: number;
  photo_url: string | null;
}

// ── taxonomy ────────────────────────────────────────────────────────────

export interface ServiceType {
  id: number;
  code: string;
  name: string;
  hint: string | null;
  requires_subject: boolean;
  requires_institution: boolean;
}

export interface Subject {
  id: number;
  slug: string;
  name: string;
  parent_id: number | null;
  has_children: boolean;
  external_code: string | null;
  offers_count: number;
}

export interface Institution {
  id: number;
  code: string;
  name: string;
  short_name: string | null;
  city: string | null;
  parent_id: number | null;
  faculties: Institution[];
}

export interface LanguageOption {
  code: string;
  name: string;
}

// ── catalog ─────────────────────────────────────────────────────────────

export interface Offer {
  id: number;
  service_type: string;
  service_type_name: string;
  subject: string | null;
  institution: string | null;
  price: Price;
  langs: string[];
  work_format: WorkFormat;
}

/** One row in the results list. */
export interface HelperCard {
  user_id: number;
  name: string;
  avatar: Avatar;
  affiliation: string | null;
  price: Price | null;
  /** Why this person is in the list. Sometimes it says the match is weak. */
  reason: Phrase | null;
  availability: Phrase | null;
  rating: number | null;
  deals_count: number;
  langs: string[];
}

export interface Stat {
  code: string;
  value: string;
}

export interface Review {
  author: string;
  /** ISO date, `YYYY-MM-DD`. */
  created_on: string;
  text: string;
}

export interface HelperDetail {
  user_id: number;
  name: string;
  avatar: Avatar;
  affiliation: string | null;
  about: string | null;
  headline: string | null;
  stats: Stat[];
  offers: Offer[];
  langs: string[];
  work_format: WorkFormat;
  place_note: string | null;
  /** ISO datetimes. */
  free_slots: string[];
  reviews: Review[];
  /** Facts for composing the prefilled first message. The wording is ours. */
  intro_context: Record<string, string | number>;
  telegram_url: string | null;
}

// ── search ──────────────────────────────────────────────────────────────

export type ChipKind =
  | 'subject'
  | 'institution'
  | 'service_type'
  | 'deadline'
  | 'budget'
  | 'lang';

/** One piece of what the parser understood, shown back for correction. */
export interface Chip {
  kind: ChipKind | string;
  label: string;
  value: string | number | null;
  confidence: number;
}

export interface ClarifyOption {
  code: string;
  tone: number;
}

/** One question, asked only when the answer changes the result set. */
export interface Clarify {
  code: string;
  options: ClarifyOption[];
}

export interface ParseResult {
  chips: Chip[];
  clarify: Clarify | null;
  matches: number;
  /** Set when nothing was recognised, so the screen can say so plainly. */
  note: Phrase | null;
}

export interface SearchFilters {
  subject_id: number | null;
  institution_id: number | null;
  service_type_id: number | null;
  max_price: number | null;
  langs: string[];
  work_format: WorkFormat | null;
}

export interface SearchResult {
  total: number;
  filters: SearchFilters;
  chips: Chip[];
  results: HelperCard[];
}

export type SearchSort = 'relevance' | 'price' | 'available';

export interface SearchParams {
  subject_id?: number;
  institution_id?: number;
  service_type_id?: number;
  max_price?: number;
  langs?: string[];
  sort?: SearchSort;
  limit?: number;
  offset?: number;
}

// ── home ────────────────────────────────────────────────────────────────

export interface HomeSection {
  kind: 'service_type' | 'item_category' | string;
  code: string;
  name: string;
  hint: string | null;
  tone: number;
  count: number;
  live_count: number | null;
  avatars: Avatar[];
}

export interface Home {
  people: HomeSection[];
  things: HomeSection[];
}

// ── partners ────────────────────────────────────────────────────────────

export interface Placement {
  id: number;
  title: string;
  subtitle: string | null;
  price_text: string | null;
  context_note: string | null;
  logo_text: string | null;
  logo_bg: string | null;
  url: string;
}

// ── user ────────────────────────────────────────────────────────────────

export interface Me {
  id: number;
  tg_id: number;
  name: string;
  username: string | null;
  avatar: Avatar;
  ui_lang: UiLang;
  spoken_langs: string[];
  city: string | null;
  institution: Institution | null;
  is_helper: boolean;
  helper_status: string | null;
}

export interface MeUpdate {
  ui_lang?: UiLang;
  spoken_langs?: string[];
  city?: string | null;
  institution_id?: number | null;
}

// ── requests: the catalog read backwards ────────────────────────────────

export type RequestStatus = 'draft' | 'open' | 'closed' | 'expired';

export interface HelpRequest {
  id: number;
  text: string;
  subject: string | null;
  institution: string | null;
  service_type: string | null;
  deadline_on: string | null;
  status: RequestStatus;
  responses_count: number;
  responders: Avatar[];
  created_at: string;
}

export interface RequestCreate {
  text: string;
  subject_id?: number;
  institution_id?: number;
  service_type_id?: number;
  deadline_on?: string;
  budget_max?: number;
  langs?: string[];
}

// ── becoming a helper ───────────────────────────────────────────────────

export interface IntroResult {
  chips: Chip[];
  price: Price | null;
  work_format: WorkFormat | null;
  institution_id: number | null;
  subject_ids: number[];
  /** What the text did not say, so the screen can ask for exactly that. */
  missing: string[];
}

export interface OfferInput {
  service_type_id: number;
  subject_id?: number | null;
  institution_id?: number | null;
  price_amount?: number | null;
  price_unit?: PriceUnit;
  langs?: string[];
}

export interface HelperUpsert {
  headline?: string | null;
  about?: string | null;
  raw_intro?: string | null;
  work_format?: WorkFormat;
  city?: string | null;
  place_note?: string | null;
  offers?: OfferInput[];
  publish?: boolean;
}
