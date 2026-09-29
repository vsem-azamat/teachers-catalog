import assert from 'node:assert/strict';
import { test } from 'node:test';

import { joinStart, joinStep } from '../src/lib/join.ts';

test('with initData and a query id the check can be taken', () => {
  assert.deepEqual(joinStart('user=...&hash=...', 'q-123'), {
    phase: 'ready',
    queryId: 'q-123',
  });
});

test('without initData there is nothing to sign with', () => {
  assert.deepEqual(joinStart(undefined, 'q-123'), { phase: 'unavailable' });
});

test('without a query id there is no request to approve', () => {
  assert.deepEqual(joinStart('user=...&hash=...', null), { phase: 'unavailable' });
  assert.deepEqual(joinStart('user=...&hash=...', ''), { phase: 'unavailable' });
});

test('a press sends it, once', () => {
  const ready = joinStart('x', 'q');
  const working = joinStep(ready, { type: 'press' });
  assert.equal(working.phase, 'working');
  assert.equal(
    joinStep(working, { type: 'press' }),
    working,
    'a second press does nothing',
  );
});

test('approval passes and refusal fails, and neither can be pressed again', () => {
  const working = joinStep(joinStart('x', 'q'), { type: 'press' });
  const passed = joinStep(working, { type: 'approved' });
  const failed = joinStep(working, { type: 'refused' });
  assert.equal(passed.phase, 'passed');
  assert.equal(failed.phase, 'failed');
  assert.equal(joinStep(passed, { type: 'press' }), passed);
  assert.equal(joinStep(failed, { type: 'press' }), failed);
});

test('an answer that arrives without a press is ignored', () => {
  const ready = joinStart('x', 'q');
  assert.equal(joinStep(ready, { type: 'approved' }), ready);
});
