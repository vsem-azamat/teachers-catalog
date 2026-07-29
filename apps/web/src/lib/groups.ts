/**
 * Contiguous runs of items that share a key.
 *
 * Kinds of help appear under their group heading in two components — the
 * grid of tiles, which draws the home screen and the screen where a service
 * is offered, and the screen where prices are set. All of them take the
 * order the server chose rather than sorting again here.
 *
 * Runs, not a lookup: a group
 * that came back split shows up as two headings instead of silently merging
 * into one, which is the honest rendering of a server that has gone wrong.
 *
 * That is also why callers key the list by position and not by the group:
 * a split group would otherwise hand React the same key twice, and the two
 * honest headings would collapse back into a warning.
 */
// The key is compared with ===, so it has to be something that compares by
// value. An object would give one run per item and no complaint.
export function groupRuns<T, K extends PropertyKey>(
  items: T[],
  keyOf: (item: T) => K,
): { key: K; items: T[] }[] {
  const runs: { key: K; items: T[] }[] = [];
  for (const item of items) {
    const key = keyOf(item);
    const last = runs.at(-1);
    if (last && last.key === key) last.items.push(item);
    else runs.push({ key, items: [item] });
  }
  return runs;
}
