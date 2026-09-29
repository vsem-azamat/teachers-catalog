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
  /** `retried`: the last attempt did not get through, and the screen says so. */
  | { phase: 'ready'; initData: string; queryId: string; retried: boolean }
  | { phase: 'sending'; initData: string; queryId: string }
  | { phase: 'passed' }
  /** Supervisor refused: the request expired or is somebody else's. */
  | { phase: 'failed' };

export type JoinEvent =
  | { type: 'press' }
  | { type: 'approved' }
  | { type: 'refused' }
  /** Anything that is not supervisor's answer: the network, the proxy, a 5xx. */
  | { type: 'unreachable' };

export function joinStart(
  initData: string | undefined,
  queryId: string | null | undefined,
): JoinState {
  if (!initData || !queryId) return { phase: 'unavailable' };
  return { phase: 'ready', initData, queryId, retried: false };
}

/**
 * The next state, or the same object when the event does not apply.
 *
 * The same object, not a copy: the screen sends the request only when a press
 * moved the state to `sending`, so a second press while one is in flight, or
 * after it settled, cannot send a second one.
 */
export function joinStep(state: JoinState, event: JoinEvent): JoinState {
  if (event.type === 'press') {
    return state.phase === 'ready'
      ? { phase: 'sending', initData: state.initData, queryId: state.queryId }
      : state;
  }
  if (state.phase !== 'sending') return state;
  if (event.type === 'approved') return { phase: 'passed' };
  if (event.type === 'refused') return { phase: 'failed' };
  return {
    phase: 'ready',
    initData: state.initData,
    queryId: state.queryId,
    retried: true,
  };
}
