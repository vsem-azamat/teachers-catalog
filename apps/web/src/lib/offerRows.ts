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

/**
 * The rows left after one axis chip is removed.
 *
 * Removing the last subject — or the last school — must not remove the
 * service: the person ticked it, and a service with no axis is one search
 * cannot reach yet, not one they withdrew. So the last row of a service stays,
 * and only its axes are cleared.
 *
 * It keeps everything else it held. The checklist, the note and the turnaround
 * belong to the service type and not to one of its rows — that is what
 * `docs/data-model.md` says of those columns, and it is why the screen writes a
 * toggled option to every row of a service. A fresh blank row here would answer
 * «I do these five things, in three days, for 500» with silence, because a
 * subject chip was tapped off.
 */
export function dropRow(rows: Draft[], row: Draft): Draft[] {
  const left = rows.filter((other) => other.key !== row.key);
  if (left.some((other) => other.service_type_id === row.service_type_id)) return left;
  return [
    ...left,
    {
      ...row,
      // The key a fresh row of this service would have: nothing else of this
      // service is left to collide with it, and the chip that carried the old
      // one is gone.
      key: `${row.service_type_id}:new`,
      subject_id: null,
      subject_name: null,
      institution_id: null,
      institution_name: null,
    },
  ];
}
