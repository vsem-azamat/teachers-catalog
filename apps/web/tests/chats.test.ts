import assert from 'node:assert/strict';
import { test } from 'node:test';

import { chipFor, directory, type PublicChat, search } from '../src/lib/chats.ts';

function chat(
  title: string,
  group: string | null,
  over: Partial<PublicChat> = {},
): PublicChat {
  return {
    title,
    link: `https://t.me/${title.replace(/\W+/g, '_').toLowerCase()}`,
    group,
    activity: 'active',
    ...over,
  };
}

const CVUT = 'ČVUT | ЧВУТ';

// The shape production serves: one university with its faculties, one with a
// single chat, and chats that belong to nothing.
const SAMPLE: PublicChat[] = [
  chat('ČVUT | ЧВУТ', CVUT),
  chat('ČVUT FIT', CVUT),
  chat('ČVUT FEL', CVUT),
  chat('Masarykova univerzita', 'Masarykova univerzita'),
  chat('Strahov', null),
  chat('IT Чехия', null),
];

/** What the directory draws, reduced to titles. */
function shape(chats: PublicChat[]) {
  return directory(chats).entries.map((entry) =>
    entry.kind === 'section'
      ? { section: entry.name, chats: entry.chats.map((c) => c.title) }
      : { chat: entry.chat.title },
  );
}

test('chats that share a group form a section, in the order given', () => {
  assert.deepEqual(shape(SAMPLE)[0], {
    section: CVUT,
    chats: ['ČVUT | ЧВУТ', 'ČVUT FIT', 'ČVUT FEL'],
  });
});

test('a group with one chat is that chat, not a section', () => {
  assert.deepEqual(shape(SAMPLE), [
    { section: CVUT, chats: ['ČVUT | ЧВУТ', 'ČVUT FIT', 'ČVUT FEL'] },
    { chat: 'Masarykova univerzita' },
  ]);
});

test('chats without a group come apart, last, in the order given', () => {
  const { rest } = directory(SAMPLE);
  assert.deepEqual(
    rest.map((c) => c.title),
    ['Strahov', 'IT Чехия'],
  );
});

test('a group split by the server stays one section', () => {
  const split = [chat('ČVUT FIT', CVUT), chat('Strahov', null), chat('ČVUT FEL', CVUT)];
  assert.deepEqual(shape(split), [{ section: CVUT, chats: ['ČVUT FIT', 'ČVUT FEL'] }]);
});

test('search ignores case and diacritics', () => {
  assert.deepEqual(
    search(SAMPLE, 'cvut fit').map((c) => c.title),
    ['ČVUT FIT'],
  );
  assert.deepEqual(
    search(SAMPLE, 'strahov').map((c) => c.title),
    ['Strahov'],
  );
});

test('search matches the group too, so a university finds its faculties', () => {
  assert.equal(search(SAMPLE, 'ЧВУТ').length, 3);
});

test('every word has to match, in any order', () => {
  assert.deepEqual(
    search(SAMPLE, 'fel čvut').map((c) => c.title),
    ['ČVUT FEL'],
  );
});

test('an empty query finds nothing to narrow, so it returns everything', () => {
  assert.equal(search(SAMPLE, '   ').length, SAMPLE.length);
});

test('activity is a chip only when supervisor measured it', () => {
  assert.equal(chipFor('busy'), 'busy');
  assert.equal(chipFor('active'), 'active');
  assert.equal(chipFor('quiet'), 'quiet');
  assert.equal(chipFor('unknown'), null);
});

test('a tile takes its letters from the first of two names', async () => {
  const { initials } = await import('../src/lib/chats.ts');
  assert.equal(initials('ČVUT | ЧВУТ'), 'ČV');
  assert.equal(initials('Fyzika v ČR'), 'FV');
  assert.equal(initials('Strahov'), 'ST');
});

test('a faculty shows its own abbreviation, not its university one', async () => {
  const { initials } = await import('../src/lib/chats.ts');
  assert.equal(initials('ČVUT FIT'), 'FIT');
  assert.equal(initials('ČVUT FSv'), 'FSV');
  assert.equal(initials('Kolej Hvězda'), 'KH');
  assert.equal(initials('IT Чехия | Опыт, работа, новости'), 'IЧ');
});
