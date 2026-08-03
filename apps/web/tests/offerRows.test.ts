import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type Draft, dropRow, serviceAnswers } from '../src/lib/offerRows.ts';

/** A row of the service the tests use, with everything filled in. */
function row(over: Partial<Draft> = {}): Draft {
  return {
    key: '7:12:null',
    service_type_id: 7,
    subject_id: 12,
    subject_name: 'Математический анализ',
    institution_id: null,
    institution_name: null,
    option_ids: [3, 4],
    note: 'Разбираю задачи с прошлых экзаменов',
    turnaround_days: 3,
    price: '500',
    unit: 'hour',
    langs: ['ru'],
    ...over,
  };
}

test('a second subject starts from what the service already says', () => {
  // Every answer that belongs to the service, the turnaround included: a
  // person who set «за 3 дня» and then added a second subject would otherwise
  // publish one row promising three days and one promising nothing.
  assert.deepEqual(serviceAnswers([row()], 7), {
    price: '500',
    option_ids: [3, 4],
    note: 'Разбираю задачи с прошлых экзаменов',
    turnaround_days: 3,
  });
});

test('a service with no row yet inherits nothing', () => {
  assert.deepEqual(serviceAnswers([row()], 9), {});
});

test('a service with other rows left simply loses the one removed', () => {
  const kept = row({
    key: '7:13:null',
    subject_id: 13,
    subject_name: 'Линейная алгебра',
  });
  assert.deepEqual(dropRow([row(), kept], row()), [kept]);
});

test('the last row of a service stays, with its axes cleared', () => {
  const [last, ...rest] = dropRow([row()], row());
  assert.equal(rest.length, 0);
  assert.equal(last?.service_type_id, 7);
  assert.equal(last?.subject_id, null);
  assert.equal(last?.subject_name, null);
});

test('and keeps what the person said about the service itself', () => {
  // The checklist, the note, the turnaround and the price belong to the
  // service type, not to one of its rows — see docs/data-model.md. Tapping a
  // subject chip off is not an answer to any of those questions.
  const [last] = dropRow([row()], row());
  assert.deepEqual(last?.option_ids, [3, 4]);
  assert.equal(last?.note, 'Разбираю задачи с прошлых экзаменов');
  assert.equal(last?.turnaround_days, 3);
  assert.equal(last?.price, '500');
  assert.deepEqual(last?.langs, ['ru']);
});
