import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ChatRow } from '@/components/ChatRow';
import { SearchIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import {
  Chevron,
  Count,
  Empty,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { api } from '@/lib/api';
import { directory, initials, search } from '@/lib/chats';

/** Six tile tones, handed out by position: a group's name is never read. */
const TONES = 6;

/**
 * The chat directory: supervisor-telegram's chats, read as places to go.
 *
 * How entries are built is in docs/architecture.md, «The chat directory
 * reads the order it is given», and in `lib/chats.ts`.
 */
export default function ChatsPage() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['chats'],
    queryFn: ({ signal }) => api.getChats(signal),
    // The directory changes when a moderator publishes a chat, not while
    // somebody is looking at it.
    staleTime: 5 * 60_000,
  });

  const found = useMemo(() => (data ? search(data, query) : []), [data, query]);
  const { entries, rest } = useMemo(() => directory(data ?? []), [data]);
  const searching = query.trim() !== '';

  return (
    <>
      <Screen withTabs>
        <AppHeader />
        <Title>
          <Trans>Найди свой чат</Trans>
        </Title>
        <div style={{ marginTop: 6 }}>
          <Sub>
            <Trans>Факультеты, общежития, общие. Модерируются, спам вычищается.</Trans>
          </Sub>
        </div>

        <div className={ui.field} style={{ marginTop: 16 }}>
          <SearchIcon size={18} className={ui.fieldIcon} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t`ČVUT, FIT, Strahov…`}
            aria-label={t`Поиск чата`}
            maxLength={100}
            style={{ all: 'unset', flex: 1, minWidth: 0 }}
          />
        </div>

        {isPending ? (
          <>
            <Label>
              <Trans>Загружаем</Trans>
            </Label>
            <SkeletonRows count={6} />
          </>
        ) : isError ? (
          <Rows>
            <Row
              title={<Trans>Не удалось загрузить чаты</Trans>}
              hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
              onClick={() => void refetch()}
            />
          </Rows>
        ) : searching ? (
          found.length === 0 ? (
            <Empty
              title={<Trans>Такого чата нет</Trans>}
              body={<Trans>Попробуй название вуза или факультета латиницей.</Trans>}
            />
          ) : (
            <>
              <Label>
                <Trans>Нашлось</Trans>
              </Label>
              <Rows>
                {found.map((chat, index) => (
                  <ChatRow key={chat.link} chat={chat} tone={index % TONES} />
                ))}
              </Rows>
            </>
          )
        ) : entries.length === 0 && rest.length === 0 ? (
          <Empty title={<Trans>Чатов пока нет</Trans>} />
        ) : (
          <>
            {entries.length > 0 ? (
              <>
                <Label>
                  <Trans>Вузы</Trans>
                </Label>
                <Rows>
                  {entries.map((entry, index) =>
                    entry.kind === 'section' ? (
                      <Row
                        key={`section:${entry.name}`}
                        leading={<Tile tone={index % TONES}>{initials(entry.name)}</Tile>}
                        title={entry.name}
                        hint={entry.chats
                          .slice(1, 4)
                          .map((chat) => chat.title)
                          .join(', ')}
                        trailing={
                          <>
                            <Count>{entry.chats.length}</Count>
                            <Chevron />
                          </>
                        }
                        onClick={() =>
                          navigate(`/chats/${encodeURIComponent(entry.name)}`)
                        }
                      />
                    ) : (
                      <ChatRow
                        key={entry.chat.link}
                        chat={entry.chat}
                        tone={index % TONES}
                      />
                    ),
                  )}
                </Rows>
              </>
            ) : null}
            {rest.length > 0 ? (
              <>
                <Label>
                  <Trans>Другие чаты</Trans>
                </Label>
                <Rows>
                  {rest.map((chat, index) => (
                    <ChatRow
                      key={chat.link}
                      chat={chat}
                      tone={(entries.length + index) % TONES}
                    />
                  ))}
                </Rows>
              </>
            ) : null}
          </>
        )}
      </Screen>
      <TabBar />
    </>
  );
}
