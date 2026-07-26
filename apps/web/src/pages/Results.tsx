import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { PhraseView, PriceUnitLabel } from '@/components/Phrase';
import { TabBar } from '@/components/TabBar';
import {
  AvatarView,
  Card,
  Cards,
  Empty,
  Free,
  Label,
  PriceView,
  Reason,
  Screen,
  Segmented,
  SkeletonRows,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { HelperCard, SearchSort } from '@/lib/types';

/**
 * The results list.
 *
 * Every card carries the reason the person is on it. When that reason is
 * "cheaper than the rest, but has never seen your exam", it says so — which is
 * what makes the rows above it worth believing.
 */
export default function ResultsPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { t, i18n } = useLingui();
  const [sort, setSort] = useState<SearchSort>('relevance');

  const filters = useMemo(
    () => ({
      subject_id: numeric(params.get('subject_id')),
      institution_id: numeric(params.get('institution_id')),
      service_type_id: numeric(params.get('service_type_id')),
      max_price: numeric(params.get('max_price')),
      sort,
    }),
    [params, sort],
  );

  // The clarifying answer arrives as a service code; the id it maps to lives
  // in the reference list this screen would load anyway.
  const serviceCode = params.get('service');
  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    enabled: Boolean(serviceCode) && !filters.service_type_id,
    staleTime: 60 * 60 * 1000,
  });
  const serviceTypeId =
    filters.service_type_id ??
    serviceTypes?.find((type) => type.code === serviceCode)?.id;

  const waitingForServiceId = Boolean(serviceCode) && serviceTypeId === undefined;

  const { data, isPending, isError } = useQuery({
    queryKey: ['search', { ...filters, service_type_id: serviceTypeId }],
    queryFn: ({ signal }) =>
      api.search({ ...filters, service_type_id: serviceTypeId }, signal),
    enabled: !waitingForServiceId,
  });

  const loading = isPending || waitingForServiceId;

  return (
    <>
      <Screen withTabs>
        <div style={{ height: 8 }} />
        <Segmented
          value={sort}
          onChange={(next) => {
            hapticSelection();
            setSort(next);
          }}
          options={[
            { value: 'relevance', label: t`Подходят` },
            { value: 'price', label: t`Дешевле` },
            { value: 'available', label: t`Свободны` },
          ]}
        />

        {loading ? (
          <>
            <Label>
              <Trans>Ищем…</Trans>
            </Label>
            <SkeletonRows count={4} />
          </>
        ) : isError ? (
          <Empty
            title={<Trans>Не получилось загрузить</Trans>}
            body={<Trans>Проверь соединение и попробуй ещё раз.</Trans>}
          />
        ) : data.total === 0 ? (
          <Empty
            title={<Trans>Пока никого</Trans>}
            body={
              <Trans>
                По этому запросу ещё нет никого. Создай заявку — тогда найдут тебя.
              </Trans>
            }
          />
        ) : (
          <>
            <Label aside={<Trans>всего {data.total}</Trans>}>
              <Trans>Кто может помочь</Trans>
            </Label>
            <Cards>
              {data.results.map((card) => (
                <HelperCardView
                  key={card.user_id}
                  card={card}
                  locale={i18n.locale}
                  onClick={() => navigate(`/helper/${card.user_id}`)}
                />
              ))}
            </Cards>
          </>
        )}
        <div style={{ height: 20 }} />
      </Screen>
      <TabBar />
    </>
  );
}

function HelperCardView({
  card,
  locale,
  onClick,
}: {
  card: HelperCard;
  locale: string;
  onClick: () => void;
}) {
  // "Cheaper but unproven" is the one reason that should not wear the same
  // confident green dot as the others.
  const weak = card.reason?.code === 'reason.cheapest_but_unproven';

  return (
    <Card onClick={onClick}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <AvatarView avatar={card.avatar} size={40} square />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 680, letterSpacing: '-0.015em' }}>
            {card.name}
          </div>
          {card.affiliation ? (
            <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
              {card.affiliation}
            </div>
          ) : null}
        </div>
        {card.price ? (
          <PriceView
            price={card.price}
            unitLabel={<PriceUnitLabel unit={card.price.unit} />}
          />
        ) : null}
      </div>

      {card.reason ? (
        <Reason weak={weak}>
          <PhraseView phrase={card.reason} locale={locale} />
        </Reason>
      ) : null}

      {card.availability ? (
        <Free>
          <PhraseView phrase={card.availability} locale={locale} />
        </Free>
      ) : null}
    </Card>
  );
}

function numeric(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
