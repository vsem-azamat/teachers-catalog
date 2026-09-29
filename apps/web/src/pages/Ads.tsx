import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { AdsContact } from '@/components/AdsContact';
import { AppHeader } from '@/components/AppHeader';
import { ChatIcon, DocumentIcon } from '@/components/icons';
import { Chevron, Label, Row, Rows, Screen, Sub, Tile, Title, ui } from '@/components/Ui';
import { api } from '@/lib/api';
import { reachFigures } from '@/lib/reach';

/** Reach is recounted hourly by supervisor; an hour here costs nothing. */
export const reachQuery = {
  queryKey: ['reach'] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getReach(signal),
  staleTime: 60 * 60_000,
};

/**
 * Advertising, for a business that wants students to see it.
 *
 * A showcase and not a shop: two formats, how far they reach, and a person to
 * write to. Never a price. See docs/architecture.md, «The ads page is a
 * showcase, not a shop».
 */
export default function AdsPage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const { data } = useQuery(reachQuery);
  const figures = data ? reachFigures(data) : null;

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Реклама для студентов</Trans>
      </Title>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            Студенты чешских вузов в чатах и в этом приложении. Чаты модерируются каждый
            день, поэтому чужой спам не перебивает ваш пост.
          </Trans>
        </Sub>
      </div>

      {figures ? (
        <div className={ui.stats}>
          <div className={ui.stat}>
            <b>{figures.chats}</b>
            <span>
              <Plural
                value={figures.chats}
                one="чат"
                few="чата"
                many="чатов"
                other="чата"
              />
            </span>
          </div>
          {figures.members ? (
            <div className={ui.stat}>
              <b>
                {figures.members.approximate ? '≈' : ''}
                {figures.members.value.toLocaleString(i18n.locale)}
              </b>
              <span>
                <Plural
                  value={figures.members.value}
                  one="участник"
                  few="участника"
                  many="участников"
                  other="участника"
                />
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      <Label>
        <Trans>Форматы</Trans>
      </Label>
      <Rows>
        <Row
          leading={
            <Tile tone={3}>
              <ChatIcon size={19} />
            </Tile>
          }
          title={<Trans>Пост в чатах</Trans>}
          hint={<Trans>по вузам и факультетам</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/ads/chats')}
        />
        <Row
          leading={
            <Tile tone={1}>
              <DocumentIcon size={19} />
            </Tile>
          }
          title={<Trans>Карточка в приложении</Trans>}
          hint={<Trans>рядом с нужной услугой</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/ads/app')}
        />
      </Rows>

      <Label>
        <Trans>Что не размещаем</Trans>
      </Label>
      <Sub>
        <Trans>
          Займы, ставки, дипломы под ключ. Модерация чистит такое каждый день, и продавать
          то же самое сверху было бы странно.
        </Trans>
      </Sub>

      <AdsContact />
    </Screen>
  );
}
