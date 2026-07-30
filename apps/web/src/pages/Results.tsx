import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { HelperCardView } from '@/components/HelperCard';
import { TabBar } from '@/components/TabBar';
import {
  Cards,
  Chips,
  ChipView,
  Empty,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
} from '@/components/Ui';
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { SearchSort } from '@/lib/types';

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

  // The same reading of the query string the search screen used to count and
  // preview this list, so the number it showed is the number that arrives here.
  const { filters, isError: filtersFailed } = useSearchFilters(params);

  // `filters` and not `{...filters}`: spread onto an object, a null — the
  // service code has not been resolved yet — becomes the same key as a search
  // with no filters at all. A warm cache from an unfiltered visit would then be
  // handed over as this query's answer, and the screen would show the whole
  // catalog under one person's query before quietly swapping it out.
  const { data, isPending, isError } = useQuery({
    queryKey: ['search', filters, sort],
    queryFn: ({ signal }) => api.search({ ...filters, sort }, signal),
    enabled: filters !== null,
  });

  // Unknown filters are still loading, not loaded. The error takes precedence,
  // or a failed lookup would keep the skeleton up for ever.
  const failed = isError || filtersFailed;
  const loading = (isPending || filters === null) && !failed;

  return (
    <>
      <Screen withTabs>
        {data && data.chips.length > 0 ? (
          <div style={{ marginBottom: 12 }}>
            <Chips>
              {data.chips.map((chip) => (
                <ChipView key={`${chip.kind}:${chip.value}`} active>
                  {chip.kind === 'budget' ? `≤ ${chip.label} Kč` : chip.label}
                </ChipView>
              ))}
              <ChipView ghost onClick={() => navigate('/ask')}>
                <Trans>изменить</Trans>
              </ChipView>
            </Chips>
          </div>
        ) : (
          <div style={{ height: 8 }} />
        )}
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
        ) : failed || !data ? (
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
      </Screen>
      <TabBar />
    </>
  );
}
