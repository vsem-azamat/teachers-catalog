import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { HelperCardView } from '@/components/HelperCard';
import { RequestSheet } from '@/components/RequestSheet';
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
  ui,
} from '@/components/Ui';
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
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
  // Opened straight away when the search screen sent somebody here because it
  // found nobody: the button there said «Оставить заявку», and landing on an
  // empty list with the sheet still shut would be that promise unkept.
  const [asking, setAsking] = useState(params.get('ask') === '1');

  // The words behind the chips. A link somebody was sent may carry only the
  // ids, in which case the sheet opens on an empty field rather than not at
  // all — the request is the person's own sentence either way.
  const words = params.get('q') ?? '';

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
                <ChipView key={chipKey(chip)} active>
                  {chipLabel(chip, i18n.locale)}
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
          <>
            <Empty
              title={<Trans>Пока никого</Trans>}
              body={<Trans>Никто пока не предлагает то, что ты ищешь.</Trans>}
            />
            <AskInstead onClick={() => setAsking(true)} found={0} />
          </>
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
            {/* Not only when the search failed. Choosing from a list and
                letting the list choose you are two ways of doing the same
                thing, and the second one is the whole other half of the
                product. */}
            <AskInstead onClick={() => setAsking(true)} found={data.total} />
          </>
        )}
      </Screen>
      {asking ? (
        <RequestSheet
          text={words}
          chips={data?.chips ?? []}
          // `ask=1` opens the sheet on the first render, before the search has
          // answered — and after it fails. Neither is "this query filters on
          // nothing", which is what an empty list would otherwise say.
          known={data !== undefined}
          onClose={() => setAsking(false)}
        />
      ) : null}
      <TabBar />
    </>
  );
}

/**
 * The other way out of a search.
 *
 * A dashed row rather than a card: it is not one of the results, and drawn
 * like one it would be read as a person. The wording changes with the count
 * because "nobody suits you" makes no sense on an empty list and "leave a
 * request" alone makes none under twelve.
 */
function AskInstead({ onClick, found }: { onClick: () => void; found: number }) {
  return (
    <button type="button" className={ui.instead} onClick={onClick}>
      <span>
        <b>
          {found > 0 ? (
            <Trans>Никто не подошёл?</Trans>
          ) : (
            <Trans>Пусть найдут тебя</Trans>
          )}
        </b>
        <Trans>Оставь заявку — ответят сами</Trans>
      </span>
      <span className={ui.insteadGo}>
        <Trans>Оставить</Trans>
      </span>
    </button>
  );
}
