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
  | { phase: 'sending'; initData: string; queryId: string; retried: boolean }
  | { phase: 'passed' }
  /**
   * Supervisor refused. `afterRetry`: an earlier attempt may have gone
   * through, since supervisor spends the check before it asks Telegram.
   */
  | { phase: 'failed'; afterRetry: boolean };

export type JoinEvent =
  | { type: 'press' }
  | { type: 'approved' }
  | { type: 'refused' }
  /** Anything that is not supervisor's refusal: the network, the proxy, a 5xx. */
  | { type: 'unreachable' };

/** How a check can already have ended in this session. */
export type Settled = 'passed' | 'failed';

export function joinStart(
  initData: string | undefined,
  queryId: string | null | undefined,
  settled?: Settled | null,
): JoinState {
  // A settled check stays settled, whatever route led back here: offering
  // the button again for a spent check can only end in a false refusal.
  if (settled === 'passed') return { phase: 'passed' };
  if (settled === 'failed') return { phase: 'failed', afterRetry: false };
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
    return state.phase === 'ready' ? { ...state, phase: 'sending' } : state;
  }
  if (state.phase !== 'sending') return state;
  if (event.type === 'approved') return { phase: 'passed' };
  if (event.type === 'refused') return { phase: 'failed', afterRetry: state.retried };
  return { ...state, phase: 'ready', retried: true };
}

/** What a failed request means. Only supervisor's 403 is a refusal. */
export function joinEventFor(error: unknown): JoinEvent {
  const status = (error as { status?: unknown } | null)?.status;
  return status === 403 ? { type: 'refused' } : { type: 'unreachable' };
}

/** Whether supervisor's answer is an approval: `{status: "approved"}` and nothing else. */
export function isApproval(answer: unknown): boolean {
  return (
    answer !== null &&
    typeof answer === 'object' &&
    (answer as { status?: unknown }).status === 'approved'
  );
}
