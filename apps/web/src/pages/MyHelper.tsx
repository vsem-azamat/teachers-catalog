import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { AppHeader } from '@/components/AppHeader';
import { CloseIcon } from '@/components/icons';
import {
  Empty,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  Segmented,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection, hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { MyOffer, OfferInput, PriceUnit, Subject, WorkFormat } from '@/lib/types';

/**
 * The helper's own page: everything they have told us, editable.
 *
 * One screen, not a wizard. Someone who has already decided to help should be
 * able to fix a price or add a subject in ten seconds, and every step between
 * them and that is a step where they close the app instead. Nothing here is
 * required — an empty profile is a profile nobody finds, which is a fair
 * consequence and not an error message.
 */
export default function MyHelperPage() {
  const queryClient = useQueryClient();
  const { t } = useLingui();

  const { data, isPending, isError } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  const [headline, setHeadline] = useState('');
  const [about, setAbout] = useState('');
  const [city, setCity] = useState('');
  const [placeNote, setPlaceNote] = useState('');
  const [workFormat, setWorkFormat] = useState<WorkFormat>('both');
  const [listed, setListed] = useState(true);
  const [rows, setRows] = useState<Draft[]>([]);

  // Filled once, from the server. Later renders must not clobber what the
  // person is typing, which is what a plain `value={data.about}` would do.
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!data || loaded) return;
    setHeadline(data.headline ?? '');
    setAbout(data.about ?? '');
    setCity(data.city ?? '');
    setPlaceNote(data.place_note ?? '');
    setWorkFormat(data.work_format);
    setListed(data.status !== 'hidden' && data.status !== 'draft');
    setRows(data.offers.map(toDraft));
    setLoaded(true);
  }, [data, loaded]);

  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const save = useMutation({
    mutationFn: () =>
      api.saveHelper({
        headline: headline.trim() || null,
        about: about.trim() || null,
        work_format: workFormat,
        city: city.trim() || null,
        place_note: placeNote.trim() || null,
        offers: rows.map(toOffer),
        publish: listed,
      }),
    onSuccess: (me) => {
      hapticSuccess();
      queryClient.setQueryData(['me'], me);
      void queryClient.invalidateQueries({ queryKey: ['my-helper'] });
      void queryClient.invalidateQueries({ queryKey: ['home'] });
    },
  });

  // Null while the profile has not arrived, so the error screen below does not
  // get a disabled Save button floating over it with nothing to save.
  useMainButton(
    loaded
      ? {
          text: t`Сохранить`,
          isVisible: true,
          isEnabled: !save.isPending,
          isLoaderVisible: save.isPending,
          onClick: () => save.mutate(),
        }
      : null,
  );

  const tutoring = serviceTypes?.find((type) => type.code === 'tutoring');
  const tutoringId = tutoring?.id;

  const addSubject = (subject: Subject) => {
    if (tutoring === undefined) return;
    if (rows.some((row) => row.subject_id === subject.id)) return;
    hapticSelection();
    setRows([
      ...rows,
      {
        key: `subject-${subject.id}`,
        service_type_id: tutoring.id,
        service_type_name: tutoring.name,
        subject_id: subject.id,
        subject_name: subject.name,
        institution_id: null,
        institution_name: null,
        price: '',
        // Tutoring is priced by the hour almost everywhere; the row's own
        // select is there for the exceptions.
        unit: 'hour',
        langs: [],
      },
    ]);
  };

  if (isError) {
    return (
      <Screen>
        <AppHeader />
        <Empty title={<Trans>Не получилось загрузить анкету</Trans>} />
      </Screen>
    );
  }

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Моя анкета</Trans>
      </Title>
      <Sub>
        <Trans>Всё можно менять когда угодно. Пустые поля просто не показываем.</Trans>
      </Sub>

      {isPending ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={5} />
        </div>
      ) : (
        <>
          {/* The line under the name on every card in the catalog. It was
              being written by nothing and read by three screens, which is how
              it got silently erased; giving it an owner fixes that end too. */}
          <Label>
            <Trans>Строчка под именем</Trans>
          </Label>
          <div className={ui.field}>
            <input
              value={headline}
              onChange={(event) => setHeadline(event.target.value)}
              placeholder={t`ČVUT FEL, 3 курс`}
              maxLength={160}
              style={{ all: 'unset', width: '100%' }}
            />
          </div>

          <Label>
            <Trans>О себе</Trans>
          </Label>
          <div className={ui.field} style={{ alignItems: 'flex-start' }}>
            <textarea
              value={about}
              onChange={(event) => setAbout(event.target.value)}
              placeholder={t`Что преподаёшь, где учишься, как проходят занятия. Своими словами.`}
              rows={5}
              maxLength={4000}
              style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.5 }}
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Hint>
              <Trans>
                Это первое, что читают. Пара живых предложений работает лучше списка.
              </Trans>
            </Hint>
          </div>

          <Label>
            <Trans>Предметы и цены</Trans>
          </Label>

          {rows.length === 0 ? (
            <Hint>
              <Trans>
                Пока ни одного. Найди предмет ниже — без них тебя не найдут по поиску.
              </Trans>
            </Hint>
          ) : (
            <Rows>
              {rows.map((row) => (
                <SubjectRow
                  key={row.key}
                  row={row}
                  onPrice={(price) =>
                    setRows(rows.map((r) => (r.key === row.key ? { ...r, price } : r)))
                  }
                  onUnit={(next) =>
                    setRows(
                      rows.map((r) => (r.key === row.key ? { ...r, unit: next } : r)),
                    )
                  }
                  onRemove={() => setRows(rows.filter((r) => r.key !== row.key))}
                />
              ))}
            </Rows>
          )}

          <div style={{ marginTop: 10 }}>
            <SubjectSearch
              onPick={addSubject}
              disabled={tutoringId === undefined}
              taken={new Set(rows.map((row) => row.subject_id))}
            />
          </div>

          <Label>
            <Trans>Как занимаешься</Trans>
          </Label>
          <Segmented
            value={workFormat}
            onChange={setWorkFormat}
            options={[
              { value: 'online' as WorkFormat, label: <Trans>Онлайн</Trans> },
              { value: 'offline' as WorkFormat, label: <Trans>Очно</Trans> },
              { value: 'both' as WorkFormat, label: <Trans>И так, и так</Trans> },
            ]}
          />

          {workFormat === 'online' ? null : (
            <>
              <Label>
                <Trans>Где</Trans>
              </Label>
              <div className={ui.field}>
                <input
                  value={city}
                  onChange={(event) => setCity(event.target.value)}
                  placeholder={t`Город`}
                  maxLength={96}
                  style={{ all: 'unset', width: '100%' }}
                />
              </div>
              <div className={ui.field} style={{ marginTop: 8 }}>
                <input
                  value={placeNote}
                  onChange={(event) => setPlaceNote(event.target.value)}
                  placeholder={t`Район или где удобно встречаться`}
                  maxLength={240}
                  style={{ all: 'unset', width: '100%' }}
                />
              </div>
            </>
          )}

          <Label>
            <Trans>Видимость</Trans>
          </Label>
          <Segmented
            value={listed ? 'on' : 'off'}
            onChange={(value) => setListed(value === 'on')}
            options={[
              { value: 'on', label: <Trans>В каталоге</Trans> },
              { value: 'off', label: <Trans>Скрыть</Trans> },
            ]}
          />
          <div style={{ marginTop: 9 }}>
            <Hint>
              {listed ? (
                <Trans>Тебя видят в поиске и могут написать.</Trans>
              ) : (
                <Trans>Анкета сохранится, но в каталоге её не будет.</Trans>
              )}
            </Hint>
          </div>

          {save.isError ? (
            <div style={{ marginTop: 12 }}>
              <Hint>
                <Trans>Не сохранилось — попробуй ещё раз.</Trans>
              </Hint>
            </div>
          ) : null}
        </>
      )}
    </Screen>
  );
}

/**
 * One thing this person offers: its price, what the price is per, and the way
 * to drop it.
 *
 * The unit lives on the row rather than on the screen. A profile really can
 * mix them — tutoring by the hour, a thesis by the job — and a single control
 * at the top would quietly rewrite "1500 за работу" as "1500 в час" the first
 * time anything else on the page was saved.
 */
function SubjectRow({
  row,
  onPrice,
  onUnit,
  onRemove,
}: {
  row: Draft;
  onPrice: (price: string) => void;
  onUnit: (unit: PriceUnit) => void;
  onRemove: () => void;
}) {
  const { t } = useLingui();
  /*
   * A native select: it shows what the alternatives are, opens the platform's
   * own picker on a phone, and follows `color-scheme` in both themes.
   *
   * Every unit, not the popular four. A select whose value is missing from its
   * options renders the first one instead, so a profile priced per semester
   * would show "за час" and be saved that way the next time anything else on
   * the page changed.
   */
  const units: { value: PriceUnit; label: string }[] = [
    { value: 'hour', label: t`за час` },
    { value: 'lesson', label: t`за занятие` },
    { value: 'work', label: t`за работу` },
    { value: 'day', label: t`в день` },
    { value: 'week', label: t`за неделю` },
    { value: 'month', label: t`в месяц` },
    { value: 'semester', label: t`за семестр` },
    { value: 'item', label: t`за штуку` },
    { value: 'negotiable', label: t`договорная` },
  ];

  return (
    <div className={ui.row}>
      <span className={ui.rowBody}>
        {/* A service with no subject — writing a thesis, nostrification — is
            named by what it is, not by the blank where a subject would go. */}
        <span className={ui.rowName}>{row.subject_name ?? row.service_type_name}</span>
        {row.institution_name ? (
          <span className={ui.rowHint}>{row.institution_name}</span>
        ) : null}
      </span>
      <input
        value={row.price}
        /*
         * Digits only, filtered as they are typed.
         *
         * Prices here are whole crowns, and parsing free text was a way to be
         * quietly wrong in two directions at once: "1,500" became 1.5 Kč,
         * because a comma is a decimal point on a Czech or Russian keyboard,
         * and "1 500" became nothing at all. Both saved without complaint and
         * left the field still showing what the person had typed. Refusing
         * the characters is the version with no failure mode to explain.
         */
        onChange={(event) => onPrice(event.target.value.replace(/\D/g, '').slice(0, 7))}
        placeholder={t`Kč`}
        inputMode="numeric"
        aria-label={t`Цена`}
        style={{
          all: 'unset',
          width: 52,
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums',
        }}
      />
      <select
        value={row.unit}
        onChange={(event) => onUnit(event.target.value as PriceUnit)}
        aria-label={t`За что цена`}
        style={{
          all: 'unset',
          maxWidth: 92,
          fontSize: 12,
          color: 'var(--muted)',
          cursor: 'pointer',
        }}
      >
        {units.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        className={ui.chipRemove}
        aria-label={t`Убрать`}
        onClick={onRemove}
      >
        <CloseIcon size={14} />
      </button>
    </div>
  );
}

/**
 * Find a subject by typing.
 *
 * Fuzzy on the server, so "matan" and "матан" both land on the same node —
 * which is the whole reason this is a search box and not a tree to browse.
 */
function SubjectSearch({
  onPick,
  disabled,
  taken,
}: {
  onPick: (subject: Subject) => void;
  disabled: boolean;
  taken: Set<number | null>;
}) {
  const { t } = useLingui();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data } = useQuery({
    queryKey: ['subject-search', debounced],
    queryFn: ({ signal }) => api.searchSubjects(debounced, 6, signal),
    enabled: debounced.length >= 2,
  });

  const results = useMemo(
    () => (data ?? []).filter((subject) => !taken.has(subject.id)),
    [data, taken],
  );

  return (
    <>
      <div className={ui.field}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t`Добавить предмет — матан, čeština, физика`}
          disabled={disabled}
          maxLength={200}
          style={{ all: 'unset', width: '100%' }}
        />
      </div>
      {results.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Rows>
            {results.map((subject) => (
              <Row
                key={subject.id}
                title={subject.name}
                onClick={() => {
                  onPick(subject);
                  setQuery('');
                  setDebounced('');
                }}
              />
            ))}
          </Rows>
        </div>
      ) : null}
    </>
  );
}

/**
 * An offer while it is being edited.
 *
 * The price is a string, not a number: an input mid-typing legitimately holds
 * "" and "4", and parsing on every keystroke turns both into something the
 * field then has to render back.
 */
interface Draft {
  key: string;
  service_type_id: number;
  service_type_name: string;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  institution_name: string | null;
  price: string;
  unit: PriceUnit;
  langs: string[];
}

function toDraft(offer: MyOffer): Draft {
  return {
    // The subject alone is not unique — the same subject at two schools is two
    // rows — so the key carries every axis the server keys on.
    key: `${offer.service_type_id}:${offer.subject_id}:${offer.institution_id}`,
    service_type_id: offer.service_type_id,
    service_type_name: offer.service_type_name,
    subject_id: offer.subject_id,
    subject_name: offer.subject_name,
    institution_id: offer.institution_id,
    institution_name: offer.institution_name,
    // Rounded, because the field holds digits: an older row saved as 550.5
    // would otherwise render a decimal point the input then refuses to accept.
    price: offer.price_amount == null ? '' : String(Math.round(offer.price_amount)),
    unit: offer.price_unit,
    langs: offer.langs,
  };
}

function toOffer(row: Draft): OfferInput {
  return {
    service_type_id: row.service_type_id,
    subject_id: row.subject_id,
    institution_id: row.institution_id,
    // The field holds digits and nothing else, so there is no parse to get
    // wrong. An empty one means "did not say", not free.
    price_amount: row.price ? Number(row.price) : null,
    price_unit: row.unit,
    langs: row.langs,
  };
}
