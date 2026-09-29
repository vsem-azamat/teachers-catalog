/**
 * The join check's states, apart from the screen that draws them.
 *
 * A person arrives from a join request to a moderated chat with a query id in
 * the address. Supervisor approves the request when it gets that id together
 * with the signed initData of the person it was issued to. See
 * docs/architecture.md, «The join check answers one question».
 */

export type JoinState =
  /** Opened without initData or a query id: nothing here can work. */
  | { phase: 'unavailable' }
  | { phase: 'ready'; queryId: string }
  | { phase: 'working'; queryId: string }
  | { phase: 'passed' }
  | { phase: 'failed' };

export type JoinEvent = { type: 'press' } | { type: 'approved' } | { type: 'refused' };

export function joinStart(
  initData: string | undefined,
  queryId: string | null | undefined,
): JoinState {
  if (!initData || !queryId) return { phase: 'unavailable' };
  return { phase: 'ready', queryId };
}

/**
 * The next state, or the same object when the event does not apply.
 *
 * The same object, not a copy: a second press while the request is in flight
 * or after it has settled must change nothing, and returning the input is how
 * the screen can tell.
 */
export function joinStep(state: JoinState, event: JoinEvent): JoinState {
  if (event.type === 'press') {
    return state.phase === 'ready' ? { phase: 'working', queryId: state.queryId } : state;
  }
  if (state.phase !== 'working') return state;
  return event.type === 'approved' ? { phase: 'passed' } : { phase: 'failed' };
}
