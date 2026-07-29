/**
 * Contiguous runs of items that share a key.
 *
 * Two screens show kinds of help under their group heading — the grid of
 * tiles and the screen where prices are set — and both take the order the
 * server chose rather than sorting again here. Runs, not a lookup: a group
 * that came back split shows up as two headings instead of silently merging
 * into one, which is the honest rendering of a server that has gone wrong.
 */
export function groupRuns<T, K>(
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
