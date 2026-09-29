import { Trans } from '@lingui/react/macro';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { ChatIcon, CheckIcon, PersonIcon } from '@/components/icons';
import {
  Action,
  Actions,
  Chevron,
  Row,
  Rows,
  Screen,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api, rawInitData } from '@/lib/api';
import { joinStart, joinStep } from '@/lib/join';

/**
 * «Я не бот», for a join request to a moderated chat.
 *
 * Supervisor sends the button; this page proves the person pressing it is the
 * one who asked to join. After it passes it stays open and shows the way on.
 * See docs/architecture.md, «The join check answers one question».
 */
export default function JoinPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [state, setState] = useState(() => joinStart(rawInitData(), params.get('q')));

  const press = () => {
    if (state.phase !== 'ready') return;
    const initData = rawInitData();
    hapticSelection();
    setState((current) => joinStep(current, { type: 'press' }));
    if (!initData) {
      setState((current) => joinStep(current, { type: 'refused' }));
      return;
    }
    api.passJoinCheck(initData, state.queryId).then(
      () => setState((current) => joinStep(current, { type: 'approved' })),
      () => setState((current) => joinStep(current, { type: 'refused' })),
    );
  };

  return (
    <Screen>
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
            <div className={ui.centerRows}>
              <Rows>
                <Row
                  leading={
                    <Tile tone={3}>
                      <ChatIcon size={19} />
                    </Tile>
                  }
                  title={<Trans>Другие студенческие чаты</Trans>}
                  hint={<Trans>факультеты, общежития, общие</Trans>}
                  trailing={<Chevron />}
                  onClick={() => navigate('/chats')}
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
                  onClick={() => navigate('/')}
                />
              </Rows>
            </div>
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
                <Action onClick={press} disabled={state.phase === 'working'}>
                  {state.phase === 'working' ? (
                    <Trans>Проверяем…</Trans>
                  ) : (
                    <Trans>Я не бот</Trans>
                  )}
                </Action>
              </Actions>
            </div>
          </>
        )}
      </div>
    </Screen>
  );
}
