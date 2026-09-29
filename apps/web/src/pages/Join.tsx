import { Trans } from '@lingui/react/macro';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ChatIcon, CheckIcon, PersonIcon } from '@/components/icons';
import {
  Action,
  Actions,
  Chevron,
  Hint,
  Row,
  Rows,
  Screen,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { ApiError, api, rawInitData } from '@/lib/api';
import { type JoinState, joinStart, joinStep } from '@/lib/join';

/**
 * «Я не бот», for a join request to a moderated chat.
 *
 * Supervisor sends the button; this page proves the person pressing it is the
 * one who asked to join. After it passes it stays open and shows the way on.
 * See docs/architecture.md, «The join check answers one question».
 */
export default function JoinPage() {
  const [params] = useSearchParams();
  const [state, setState] = useState<JoinState>(() =>
    joinStart(rawInitData(), params.get('q')),
  );

  const press = () => {
    const next = joinStep(state, { type: 'press' });
    // The step decides whether anything is sent: the same state back means a
    // request is already out, or the question is settled.
    if (next === state || next.phase !== 'sending') return;
    hapticSelection();
    setState(next);
    api.passJoinCheck(next.initData, next.queryId).then(
      () => setState((current) => joinStep(current, { type: 'approved' })),
      (error: unknown) =>
        setState((current) =>
          joinStep(current, {
            // Only supervisor's 403 is a refusal. Anything else is ours or
            // Telegram's to fix, and the person may simply try again.
            type:
              error instanceof ApiError && error.status === 403
                ? 'refused'
                : 'unreachable',
          }),
        ),
    );
  };

  return (
    <Screen>
      <AppHeader />
      <div className={ui.center}>
        {state.phase === 'passed' ? (
          <>
            <Tile tone={0}>
              <CheckIcon size={22} />
            </Tile>
            <Title>
              <Trans>Готово, ты в чате</Trans>
            </Title>
            <Sub>
              <Trans>Можно возвращаться в Telegram.</Trans>
            </Sub>
            <WayOn />
          </>
        ) : state.phase === 'unavailable' ? (
          <>
            <Title>
              <Trans>Открой из заявки</Trans>
            </Title>
            <Sub>
              <Trans>
                Эта проверка открывается кнопкой из заявки на вступление в чат.
              </Trans>
            </Sub>
            <WayOn />
          </>
        ) : state.phase === 'failed' ? (
          <>
            <Title>
              <Trans>Проверка не прошла</Trans>
            </Title>
            <Sub>
              <Trans>
                Заявка устарела или открыта не тем аккаунтом. Подай её заново.
              </Trans>
            </Sub>
            <WayOn />
          </>
        ) : (
          <>
            <Tile tone={3}>
              <ChatIcon size={22} />
            </Tile>
            <Title>
              <Trans>Вступление в чат</Trans>
            </Title>
            <Sub>
              <Trans>
                Нажми кнопку, чтобы подтвердить, что ты не бот. Заявка одобрится сразу.
              </Trans>
            </Sub>
            <div className={ui.centerRows}>
              <Actions>
                <Action onClick={press} disabled={state.phase === 'sending'}>
                  {state.phase === 'sending' ? (
                    <Trans>Проверяем…</Trans>
                  ) : (
                    <Trans>Я не бот</Trans>
                  )}
                </Action>
              </Actions>
              {state.phase === 'ready' && state.retried ? (
                <div style={{ marginTop: 10 }}>
                  <Hint>
                    <Trans>Не получилось связаться. Попробуй ещё раз.</Trans>
                  </Hint>
                </div>
              ) : null}
            </div>
          </>
        )}
      </div>
    </Screen>
  );
}

/**
 * Where to go from here. `replace`, not a push: going back must not return to
 * a check that has already been spent, which would offer the button again.
 */
function WayOn() {
  const navigate = useNavigate();
  return (
    <div className={ui.centerRows}>
      <Rows>
        <Row
          leading={
            <Tile tone={3}>
              <ChatIcon size={19} />
            </Tile>
          }
          title={<Trans>Студенческие чаты</Trans>}
          hint={<Trans>факультеты, общежития, общие</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/chats', { replace: true })}
        />
        <Row
          leading={
            <Tile tone={0}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Помощь с учёбой</Trans>}
          hint={<Trans>репетиторы, přijímačky, нострификация</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/', { replace: true })}
        />
      </Rows>
    </div>
  );
}
