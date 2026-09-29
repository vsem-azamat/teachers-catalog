/**
 * The chat directory, as the Chats tab reads it.
 *
 * The chats are supervisor-telegram's (`GET /api/public/catalog`), served on
 * this origin by the router. What may be read and why is in
 * docs/architecture.md, «Two backends, one origin»; how the directory is
 * built from it is the paragraph after.
 */

/** Supervisor's own words for how much a chat talks. `unknown` is an answer. */
export type Activity = 'unknown' | 'quiet' | 'active' | 'busy';

/** One chat as supervisor publishes it: four fields, no ids, no counts. */
export interface PublicChat {
  title: string;
  link: string;
  /** The parent chat's title. Supervisor's grouping; never matched on by name. */
  group: string | null;
  activity: Activity;
}

/** A line of the directory: a group with its own screen, or a chat. */
export type Entry =
  | { kind: 'section'; name: string; chats: PublicChat[] }
  | { kind: 'chat'; chat: PublicChat };

export interface Directory {
  entries: Entry[];
  /** Chats without a group, shown last under their own heading. */
  rest: PublicChat[];
}

/**
 * Entries in the order supervisor gave, with one exception each way.
 *
 * A group with a single chat is that chat: a screen with one line behind it
 * is a tap for nothing. A group the server returned in two runs is still one
 * group, since the directory is a list of places, not a transcript of rows.
 */
export function directory(chats: PublicChat[]): Directory {
  const groups = new Map<string, PublicChat[]>();
  const rest: PublicChat[] = [];
  for (const chat of chats) {
    if (chat.group === null) {
      rest.push(chat);
      continue;
    }
    const members = groups.get(chat.group);
    if (members) members.push(chat);
    else groups.set(chat.group, [chat]);
  }

  const entries: Entry[] = [];
  for (const [name, members] of groups) {
    const [only] = members;
    entries.push(
      members.length === 1 && only
        ? { kind: 'chat', chat: only }
        : { kind: 'section', name, chats: members },
    );
  }
  return { entries, rest };
}

/** Lower case, without diacritics: «ČVUT» and «cvut» are the same word here. */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
}

/**
 * The chats every word of the query appears in, title or group, in any order.
 *
 * Flat on purpose: somebody who typed «fit» wants the chat, not the section
 * it sits in. An empty query narrows nothing.
 */
export function search(chats: PublicChat[], query: string): PublicChat[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return chats;
  return chats.filter((chat) => {
    const haystack = fold(`${chat.title} ${chat.group ?? ''}`);
    return words.every((word) => haystack.includes(word));
  });
}

/** Which chip a chat wears. None for `unknown`: an empty space is the honest answer. */
export function chipFor(activity: Activity): Exclude<Activity, 'unknown'> | null {
  return activity === 'unknown' ? null : activity;
}

/**
 * A tile's letters, from the name before any «|»: chats name themselves
 * twice, «ČVUT | ЧВУТ», and the two halves' initials read as one name.
 */
export function initials(title: string): string {
  const [name = title] = title.split('|');
  const words = name
    .replace(/[^\p{L}\p{N} ]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean);
  const [first = '#', second] = words;
  // «ČVUT FIT»: a university's abbreviation, then the faculty's. The
  // faculty's is what tells it from its neighbours. «Fyzika v ČR» ends in an
  // abbreviation too, but does not start with one.
  const last = words.at(-1) ?? '';
  const isAbbreviation = (word: string) =>
    word.length <= 5 && (word.match(/\p{Lu}/gu)?.length ?? 0) >= 2;
  if (
    words.length > 1 &&
    isAbbreviation(first) &&
    isAbbreviation(last) &&
    last.length <= 4
  ) {
    return last.toUpperCase();
  }
  if (second) return (first.charAt(0) + second.charAt(0)).toUpperCase();
  return first.slice(0, 2).toUpperCase();
}
