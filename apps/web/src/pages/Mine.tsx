import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { DocumentIcon, iconForService } from '@/components/icons';
import { formatDay } from '@/components/Phrase';
import { TabBar } from '@/components/TabBar';
import {
  AvatarStack,
  Card,
  Cards,
  Empty,
  Head,
  Label,
  Reason,
  Screen,
  SkeletonRows,
  Tile,
  Title,
} from '@/components/Ui';
import { api } from '@/lib/api';
import type { HelpRequest } from '@/lib/types';

/**
 * The other direction: what you asked for, and who answered.
 *
 * A catalog only works once it is full. Until then this is the side that does
 * work — you post what you need and helpers come to you.
 */
export default function MinePage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();

  const { data, isPending, isError } = useQuery({
    queryKey: ['requests'],
    queryFn: ({ signal }) => api.getRequests(signal),
  });

  return (
    <>
      <Screen withTabs>
        <Head />
        <Title>
          <Trans>Мои</Trans>
        </Title>

        <Label>
          <Trans>Заявки</Trans>
        </Label>

        {isPending ? (
          <SkeletonRows count={2} />
        ) : isError ? (
          <Empty title={<Trans>Не получилось загрузить</Trans>} />
        ) : data.length === 0 ? (
          <Empty
            title={<Trans>Заявок пока нет</Trans>}
            body={
              <Trans>
                Опиши, что нужно, и получай отклики — вместо того чтобы искать самому.
              </Trans>
            }
          />
        ) : (
          <Cards>
            {data.map((request) => (
              <RequestCard
                key={request.id}
                request={request}
                locale={i18n.locale}
                onClick={() => navigate(`/ask?from=${request.id}`)}
              />
            ))}
          </Cards>
        )}
        <div style={{ height: 20 }} />
      </Screen>
      <TabBar />
    </>
  );
}

function RequestCard({
  request,
  locale,
  onClick,
}: {
  request: HelpRequest;
  locale: string;
  onClick: () => void;
}) {
  const Icon = request.service_type ? iconForService('tutoring') : DocumentIcon;
  const title =
    [request.subject, request.institution].filter(Boolean).join(', ') || request.text;

  return (
    <Card onClick={onClick}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <Tile tone={request.id % 6}>
          <Icon size={19} />
        </Tile>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 680, letterSpacing: '-0.015em' }}>
            {title}
          </div>
          <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
            {request.deadline_on ? (
              <Trans>до {formatDay(request.deadline_on, locale)}</Trans>
            ) : (
              <Trans>без срока</Trans>
            )}
          </div>
        </div>
      </div>

      {request.responses_count > 0 ? (
        <>
          <Reason>
            <Plural
              value={request.responses_count}
              one="# отклик"
              few="# отклика"
              many="# откликов"
              other="# отклика"
            />
          </Reason>
          {request.responders.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              <AvatarStack avatars={request.responders} />
            </div>
          ) : null}
        </>
      ) : (
        <Reason weak>
          <Trans>Пока без откликов</Trans>
        </Reason>
      )}
    </Card>
  );
}
