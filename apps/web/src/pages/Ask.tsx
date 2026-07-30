import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { HelperCardView } from '@/components/HelperCard';
import {
  CheckIcon,
  ClockIcon,
  iconForService,
  PlusIcon,
  SearchIcon,
} from '@/components/icons';
import { ClarifyOptionLabel, formatDay, PhraseView } from '@/components/Phrase';
import {
  Cards,
  Chevron,
  Chips,
  ChipView,
  Count,
  Empty,
  Hint,
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
import { useSearchFilters } from '@/hooks/useSearchFilters';
import { useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { Chip, ParseResult, SearchResult } from '@/lib/types';

const OPTION_ICON: Record<string, typeof CheckIcon> = {
  exam_prep: CheckIcon,
  exam_live_help: ClockIcon,
  both: PlusIcon,
};

/**
 * How much text counts as a query.
 *
 * Shared by the parse and by the empty state below it, which must agree about
 * when a query has begun: two literals would let the examples disappear while
 * nothing had been asked yet.
 */
const MIN_QUERY = 3;

/** How many of the results to show before the person has asked for them. */
const PREVIEW = 2;

/** How many kinds of help to name while the field is still empty. */
const SHELVES = 3;

/**
 * One field, then what we made of it.
 *
 * This screen exists so the catalog can have a single input instead of a
 * category tree. It shows the parse back as chips the person can remove, and
 * asks at most one question — and only when the answer changes the result.
 *
 * It also has to answer, before anything is typed and again after, the question
 * a bare text field never answers: what comes out of this? Empty, it names what
 * can be asked for and what the catalog holds. Filled, it shows the count and
 * the first two people on the screen itself. That count used to exist only on
 * Telegram's main button, which no browser has.
 */
export default function AskPage() {
  const navigate = useNavigate();
  const { t, i18n } = useLingui();
  const [text, setText] = useState('');
  const [parsed, setParsed] = useState<ParseResult | null>(null);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [answer, setAnswer] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const parse = useMutation({
    mutationFn: (value: string) => api.parseQuery(value),
    onSuccess: (result) => {
      setParsed(result);
      setDropped(new Set());
      setAnswer(null);
    },
  });

  // Parse as the person pauses, not on every keystroke: each call is a round
  // trip and a logged query, and mid-word text parses to nonsense anyway.
  // The debounce must restart on the text and on nothing else: including the
  // mutation would reset the timer on every state change the mutation makes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const value = text.trim();
    if (value.length < MIN_QUERY) {
      setParsed(null);
      return;
    }
    const timer = setTimeout(() => parse.mutate(value), 450);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const kept = (parsed?.chips ?? []).filter((chip) => !dropped.has(chipKey(chip)));
  const ready = kept.length > 0 || Boolean(answer);

  // One string, used for the preview, for the filters and for the navigation,
  // so none of the three can describe a different search.
  const query = useMemo(() => toQuery(kept, answer), [kept, answer]);
  const { filters, isError: filtersFailed } = useSearchFilters(query);

  const preview = useQuery({
    queryKey: ['ask-preview', filters],
    queryFn: ({ signal }) => api.search({ ...filters, limit: PREVIEW }, signal),
    enabled: ready && filters !== null,
  });

  // The number on the screen is the length of the list behind it, because both
  // come out of this one request. Taking it from the parse instead would make
  // the screen right only for as long as the two endpoints agree.
  const total = preview.data?.total;

  useMainButton(
    // Only once the count is the count. While a changed query is in flight the
    // button goes away rather than keeping the previous number under new chips:
    // a stale number on a button that promises it is the failure this screen was
    // rebuilt to fix.
    ready && total
      ? {
          text: t`Показать ${total}`,
          isVisible: true,
          isEnabled: true,
          isLoaderVisible: parse.isPending || preview.isFetching,
          onClick: () => navigate(`/results?${query}`),
        }
      : null,
  );

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Что нужно?</Trans>
      </Title>
      <Sub>
        <Trans>Напиши как думаешь. Поймём предмет, вуз, срок и бюджет.</Trans>
      </Sub>

      <div className={ui.field} style={{ alignItems: 'flex-start', marginTop: 16 }}>
        <SearchIcon size={18} className={ui.fieldIcon} />
        <textarea
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t`матан на ČVUT к 14 февраля, до 600 Kč`}
          rows={2}
          style={{
            all: 'unset',
            width: '100%',
            resize: 'none',
            lineHeight: 1.4,
          }}
        />
      </div>

      {parsed?.note ? (
        <div style={{ marginTop: 14 }}>
          <Sub>
            <PhraseView phrase={parsed.note} locale={i18n.locale} />
          </Sub>
        </div>
      ) : null}

      {text.trim().length < MIN_QUERY ? <EmptyState onPick={setText} /> : null}

      {kept.length > 0 || (parsed?.chips.length ?? 0) > 0 ? (
        <>
          <Label>
            <Trans>Поняли так — поправь, если не то</Trans>
          </Label>
          <Chips>
            {(parsed?.chips ?? []).map((chip) => {
              const key = chipKey(chip);
              const isDropped = dropped.has(key);
              return (
                <ChipView
                  key={key}
                  active={!isDropped}
                  ghost={isDropped}
                  removeLabel={t`Убрать`}
                  onRemove={
                    isDropped ? undefined : () => setDropped(new Set(dropped).add(key))
                  }
                  onClick={
                    isDropped
                      ? () => {
                          const next = new Set(dropped);
                          next.delete(key);
                          setDropped(next);
                        }
                      : undefined
                  }
                >
                  {chipLabel(chip, i18n.locale)}
                </ChipView>
              );
            })}
          </Chips>
        </>
      ) : null}

      {parsed?.clarify ? (
        <>
          <Label>
            <PhraseView
              phrase={{ code: parsed.clarify.code, params: {} }}
              locale={i18n.locale}
            />
          </Label>
          <Rows>
            {parsed.clarify.options.map((option) => {
              const Icon = OPTION_ICON[option.code] ?? CheckIcon;
              return (
                <Row
                  key={option.code}
                  onClick={() => setAnswer(option.code)}
                  leading={
                    <Tile tone={option.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={<ClarifyOptionLabel code={option.code} />}
                  trailing={answer === option.code ? <CheckIcon size={18} /> : undefined}
                />
              );
            })}
          </Rows>
          <div style={{ marginTop: 14 }}>
            <Hint>
              <Trans>Дальше вопросов не будет.</Trans>
            </Hint>
          </div>
        </>
      ) : null}

      {/* Last, and after the clarifying question rather than before it: the
          answer to that question changes the list, and a list shown above the
          thing that narrows it reads as already final. */}
      {ready ? (
        <Preview
          data={preview.data}
          isPending={preview.isPending}
          isError={preview.isError || filtersFailed}
          locale={i18n.locale}
        />
      ) : null}
    </Screen>
  );
}

/**
 * What to type, and what is here to be found.
 *
 * The examples are the cheap half: a person who has just left a screen of
 * categories needs to be told that this field takes a sentence, not a keyword.
 * The shelves under them are the honest half — three kinds of help that
 * actually have someone behind them today.
 */
function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  const navigate = useNavigate();
  const { t } = useLingui();

  const { data } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  const examples = [
    t`матан ČVUT`,
    t`čeština B2`,
    t`přijímačky на медицину`,
    t`нострификация аттестата`,
    t`курсовая по экономике`,
  ];

  // Only what someone is actually offering. An empty shelf here would be the
  // screen advertising a thing it cannot deliver, which is the failure this
  // whole change is about.
  const shelves = [...(data?.people ?? [])]
    .filter((section) => section.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, SHELVES);

  return (
    <>
      <Label>
        <Trans>Например</Trans>
      </Label>
      <Chips>
        {examples.map((example) => (
          <ChipView key={example} ghost onClick={() => onPick(example)}>
            {example}
          </ChipView>
        ))}
      </Chips>

      {shelves.length > 0 ? (
        <>
          <Label>
            <Trans>Кого тут можно найти</Trans>
          </Label>
          <Rows>
            {shelves.map((section) => {
              const Icon = iconForService(section.code);
              return (
                <Row
                  key={section.code}
                  onClick={() => navigate(`/results?service=${section.code}`)}
                  leading={
                    <Tile tone={section.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={section.name}
                  hint={section.hint}
                  trailing={
                    <>
                      <Count>{section.count}</Count>
                      <Chevron />
                    </>
                  }
                />
              );
            })}
          </Rows>
        </>
      ) : null}
    </>
  );
}

/**
 * The first people the query finds, before the person has asked to see them.
 *
 * Two cards, because the point is not the list — it is that there is one, and
 * what the rows in it look like. Zero is said out loud here rather than left
 * to a main button reading "искать всё равно".
 */
function Preview({
  data,
  isPending,
  isError,
  locale,
}: {
  data: SearchResult | undefined;
  isPending: boolean;
  isError: boolean;
  locale: string;
}) {
  const navigate = useNavigate();

  // Before the skeleton: a failed lookup of the reference list leaves the
  // request disabled and therefore pending for ever, so an error checked second
  // would never be reached.
  if (isError) {
    return (
      <Empty
        title={<Trans>Не получилось посчитать</Trans>}
        body={<Trans>Проверь соединение и попробуй ещё раз.</Trans>}
      />
    );
  }

  if (isPending) {
    return (
      <>
        <Label>
          <Trans>Ищем…</Trans>
        </Label>
        <SkeletonRows count={PREVIEW} />
      </>
    );
  }

  if (!data) return null;

  const { total, results } = data;

  if (total === 0) {
    return (
      <Empty
        title={<Trans>По этому запросу пока никого</Trans>}
        body={<Trans>Убери что-нибудь из уточнений выше или напиши иначе.</Trans>}
      />
    );
  }

  return (
    <>
      <Label aside={<Trans>всего {total}</Trans>}>
        <Trans>Кто найдётся</Trans>
      </Label>
      <Cards>
        {results.map((card) => (
          <HelperCardView
            key={card.user_id}
            card={card}
            locale={locale}
            onClick={() => navigate(`/helper/${card.user_id}`)}
          />
        ))}
      </Cards>
    </>
  );
}

function chipKey(chip: Chip): string {
  return `${chip.kind}:${chip.value ?? chip.label}`;
}

function chipLabel(chip: Chip, locale: string): string {
  if (chip.kind === 'deadline') return formatDay(chip.label, locale);
  if (chip.kind === 'budget') return `≤ ${chip.label} Kč`;
  return chip.label;
}

/** Turn the chips the person kept into the search query string. */
function toQuery(chips: Chip[], answer: string | null): string {
  const params = new URLSearchParams();
  for (const chip of chips) {
    if (chip.value == null) continue;
    if (chip.kind === 'subject') params.set('subject_id', String(chip.value));
    if (chip.kind === 'institution') params.set('institution_id', String(chip.value));
    if (chip.kind === 'service_type') params.set('service_type_id', String(chip.value));
    if (chip.kind === 'budget') params.set('max_price', String(chip.value));
  }
  // The answer to the clarifying question is a service type by name; the
  // results screen resolves it, because it already loads the list.
  if (answer && answer !== 'both') params.set('service', answer);
  return params.toString();
}
