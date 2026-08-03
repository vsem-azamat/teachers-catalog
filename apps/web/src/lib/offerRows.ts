/**
 * The rows behind the prices screen, and the one rule that is not obvious.
 *
 * Here rather than in the page because it is behaviour and not layout: what
 * survives when a row goes is a decision about somebody's saved answers, and a
 * decision like that should be provable without rendering a screen.
 */

import type { PriceUnit } from './types';

/**
 * One offer while it is being edited. The price is a string: an input
 * mid-typing legitimately holds "" and "4", and parsing on every keystroke
 * turns both into something the field then has to render back.
 */
export interface Draft {
  key: string;
  service_type_id: number;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  institution_name: string | null;
  option_ids: number[];
  note: string;
  // `null` is «договоримся», which is an answer, so the field is never absent.
  turnaround_days: number | null;
  price: string;
  unit: PriceUnit;
  langs: string[];
}

/**
 * What a new row of a service starts from.
 *
 * A second subject added to a service inherits what the person already said
 * about that service, for the reason the screen writes a toggled option to
 * every row: asking the same price four times is asking three times too many,
 * and a row added after the ticks were set would otherwise save an empty
 * checklist. Empty when the service has no row yet.
 */
export function serviceAnswers(rows: Draft[], serviceTypeId: number): Partial<Draft> {
  const sibling = rows.find((row) => row.service_type_id === serviceTypeId);
  if (!sibling) return {};
  const { price, option_ids, note, turnaround_days } = sibling;
  return { price, option_ids, note, turnaround_days };
}

/** The two axes a row can carry. `offers` is unique on both of them. */
export type Axis = 'subject' | 'institution';

const without = (row: Draft, axis: Axis): Draft =>
  axis === 'subject'
    ? { ...row, subject_id: null, subject_name: null }
    : { ...row, institution_id: null, institution_name: null };

/**
 * The rows left after one axis chip is removed.
 *
 * The tapped chip is the whole of what is being taken back, and two things
 * follow from that.
 *
 * One row can carry both axes — a school picked first and a subject after it
 * fill the same row — and it appears in both chip lists. Removing the subject
 * there leaves the school, rather than taking a school the person never touched.
 *
 * And a service whose last axis goes keeps its row, because the person ticked
 * the service: one with no axis is a service search cannot reach yet, not one
 * they withdrew. The row keeps everything else it held — the checklist, the
 * note and the turnaround belong to the service type and not to one of its
 * rows, which is what `docs/data-model.md` says of those columns and why the
 * screen writes a toggled option to every row of a service. A fresh blank row
 * here would answer «I do these five things, in three days, for 500» with
 * silence, because a chip was tapped off.
 */
export function dropRow(rows: Draft[], row: Draft, axis: Axis): Draft[] {
  const left = without(row, axis);
  const others = rows.filter((other) => other.key !== row.key);
  const bare = left.subject_id === null && left.institution_id === null;
  if (bare && others.some((other) => other.service_type_id === row.service_type_id)) {
    return others;
  }
  // In place, so the row keeps its position among its neighbours, and re-keyed
  // from what it now holds. Keeping the old key would leave a row named after
  // an axis it no longer has, which `addAxis` could then mint a second time.
  return rows.map((other) =>
    other.key === row.key ? { ...left, key: keyOf(left) } : other,
  );
}

/**
 * A row's key, from its axes.
 *
 * Unique by construction: `offers` is unique on the same four columns, so two
 * rows of one service cannot hold the same pair. The other places that mint a
 * key — a row read from the server, a row a picker just added — name the same
 * pair, and a row with no axis left is the one blank row its service is
 * allowed.
 */
function keyOf(row: Draft): string {
  return `${row.service_type_id}:${row.subject_id}:${row.institution_id}`;
}
