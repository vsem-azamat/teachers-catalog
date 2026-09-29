import assert from 'node:assert/strict';
import { test } from 'node:test';

import { joinStart, joinStep } from '../src/lib/join.ts';

test('with initData and a query id the check can be taken', () => {
  assert.deepEqual(joinStart('user=...&hash=...', 'q-123'), {
    phase: 'ready',
    initData: 'user=...&hash=...',
    queryId: 'q-123',
    retried: false,
  });
});

test('without initData there is nothing to sign with', () => {
  assert.deepEqual(joinStart(undefined, 'q-123'), { phase: 'unavailable' });
});

test('without a query id there is no request to approve', () => {
  assert.deepEqual(joinStart('user=...&hash=...', null), { phase: 'unavailable' });
  assert.deepEqual(joinStart('user=...&hash=...', ''), { phase: 'unavailable' });
});

test('a press moves to sending, and a second press is not a second request', () => {
  const ready = joinStart('x', 'q');
  const sending = joinStep(ready, { type: 'press' });
  assert.equal(sending.phase, 'sending');
  // The screen sends only when the step changed the state; the same object
  // back means "do nothing".
  assert.equal(joinStep(sending, { type: 'press' }), sending);
});

test('approval passes and a refusal fails, and neither can be pressed again', () => {
  const sending = joinStep(joinStart('x', 'q'), { type: 'press' });
  const passed = joinStep(sending, { type: 'approved' });
  const failed = joinStep(sending, { type: 'refused' });
  assert.equal(passed.phase, 'passed');
  assert.equal(failed.phase, 'failed');
  assert.equal(joinStep(passed, { type: 'press' }), passed);
  assert.equal(joinStep(failed, { type: 'press' }), failed);
});

test('a failure that is not a refusal keeps the button, marked as a retry', () => {
  const sending = joinStep(joinStart('x', 'q'), { type: 'press' });
  const again = joinStep(sending, { type: 'unreachable' });
  assert.deepEqual(again, { phase: 'ready', initData: 'x', queryId: 'q', retried: true });
  assert.equal(joinStep(again, { type: 'press' }).phase, 'sending');
});

test('an answer that arrives without a press is ignored', () => {
  const ready = joinStart('x', 'q');
  assert.equal(joinStep(ready, { type: 'approved' }), ready);
  assert.equal(joinStep(ready, { type: 'unreachable' }), ready);
});
