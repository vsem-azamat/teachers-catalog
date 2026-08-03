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
  // Opened straight away when the search screen sent somebody here because it
  // found nobody: the button there said «Оставить заявку», and landing on an
  // empty list with the sheet still shut would be that promise unkept.
  const [asking, setAsking] = useState(params.get('ask') === '1');

  // The words behind the chips. A link somebody was sent may carry only the
  // ids, in which case the sheet opens on an empty field rather than not at
  // all — the request is the person's own sentence either way.
  const words = params.get('q') ?? '';

  // A subject the parser guessed at and would not search by. It never touches
  // the query above — the list stays the search the person asked for — and this
  // is a second, ordinary search shown under its own heading.
  const guess = Number(params.get('also_subject_id')) || null;

  // The same reading of the query string the search screen used to count and
  // preview this list, so the number it showed is the number that arrives here.
  const { filters, isError: filtersFailed } = useSearchFilters(params);

  // Nothing to filter on and only a guess to go by. There is no list to show
  // above the guess then, and running the search anyway would count the whole
  // catalog under somebody's question — which is exactly what `/ask` refuses to
  // do — and then subtract every one of those people from the guess's own list,
  // leaving it empty. So the guess is the screen.
  const onlyGuess =
    guess !== null &&
    filters !== null &&
    !filters.subject_id &&
    !filters.institution_id &&
    !filters.service_type_id &&
    !filters.max_price;

  // `filters` and not `{...filters}`: spread onto an object, a null — the
  // service code has not been resolved yet — becomes the same key as a search
  // with no filters at all. A warm cache from an unfiltered visit would then be
  // handed over as this query's answer, and the screen would show the whole
  // catalog under one person's query before quietly swapping it out.
  const { data, isPending, isError } = useQuery({
    queryKey: ['search', filters, sort],
    queryFn: ({ signal }) => api.search({ ...filters, sort }, signal),
    enabled: filters !== null && !onlyGuess,
  });

  const also = useQuery({
    queryKey: ['search-also', filters, guess, sort],
    // Every filter the parse *was* sure about still applies: the guess replaces
    // the subject and nothing else. A query that named a school and a budget
    // means them in this list too.
    queryFn: ({ signal }) =>
      api.search({ ...filters, subject_id: guess ?? undefined, sort }, signal),
    enabled: guess !== null && filters !== null,
  });

  // Unknown filters are still loading, not loaded. The error takes precedence,
  // or a failed lookup would keep the skeleton up for ever.
  const failed = isError || filtersFailed;
  const loading = (isPending || filters === null) && !failed && !onlyGuess;

  // Everything the section needs except who is already on screen above it,
  // which is the only thing that differs between the two branches below.
  const alsoProps = {
    cards: also.data?.results ?? [],
    named: also.data?.chips.find((chip) => chip.kind === 'subject')?.label ?? null,
    locale: i18n.locale,
    onOpen: (id: number) => navigate(`/helper/${id}`),
  };

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

        {onlyGuess ? (
          <>
            <AlsoSection {...alsoProps} alone exclude={new Set()} />
            <AskInstead onClick={() => setAsking(true)} found={0} />
          </>
        ) : loading ? (
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
            <AlsoSection {...alsoProps} exclude={new Set()} />
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
            <AlsoSection
              {...alsoProps}
              exclude={new Set(data.results.map((card) => card.user_id))}
            />
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

/**
 * The guess, under its own heading.
 *
 * Below the confidence the parser needs to *filter* by a subject, and above the
 * confidence at which it is noise. Drawn apart from the results and named, so
 * the screen says "this might be what you meant" rather than quietly mixing it
 * into an answer.
 *
 * People already in the list above are left out: the same card twice reads as a
 * bug, and the second appearance says nothing the first did not.
 */
function AlsoSection({
  cards,
  named,
  exclude,
  alone = false,
  locale,
  onOpen,
}: {
  cards: HelperCard[];
  /** The subject it guessed, as the server named it in the reader's language. */
  named: string | null;
  exclude: Set<number>;
  /** Nothing above it, because the query gave nothing else to search by. */
  alone?: boolean;
  locale: string;
  onOpen: (id: number) => void;
}) {
  const rest = cards.filter((card) => !exclude.has(card.user_id));
  if (rest.length === 0) {
    return alone ? (
      <Empty
        title={<Trans>Не поняли запрос</Trans>}
        body={<Trans>Напиши иначе — или оставь заявку, и найдут тебя.</Trans>}
      />
    ) : null;
  }

  return (
    <>
      {/* Named, or the section is a shrug: «Также» alone leaves the reader to
          work out why these people are here, and the answer is that we guessed
          this is what they meant. With nothing above it the word changes —
          "also" beside nothing reads as a missing list. */}
      <Label aside={named}>
        {alone ? <Trans>Похоже, речь о</Trans> : <Trans>Также</Trans>}
      </Label>
      <Cards>
        {rest.map((card) => (
          <HelperCardView
            key={card.user_id}
            card={card}
            locale={locale}
            onClick={() => onOpen(card.user_id)}
          />
        ))}
      </Cards>
    </>
  );
}
