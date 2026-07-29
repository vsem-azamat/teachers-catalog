import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { iconForService } from '@/components/icons';
import { ServiceGroupLabel } from '@/components/Phrase';
import { SubjectSearch } from '@/components/SubjectSearch';
import {
  Chips,
  ChipView,
  Empty,
  Hint,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection, hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { groupRuns } from '@/lib/groups';
import type {
  MyOffer,
  OfferInput,
  PriceUnit,
  ServiceType,
  Subject,
  WorkFormat,
} from '@/lib/types';

/**
 * Prices for everything that was ticked, on one screen.
 *
 * One screen and one button, not a form per service. Someone who can do four
 * things should say so once; making them walk a wizard four times is how a
 * catalog ends up full of people who can do one.
 *
 * Nothing here is required. An empty price saves as null, which the catalog
 * already reads as "did not say" rather than as free — and a screen that can be
 * skipped entirely is a screen nobody abandons.
 */
export default function OfferPricesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { t } = useLingui();

  // The choice travels in router state: the two screens are one flow, and a
  // reload legitimately restarts it rather than resuming half way through.
  const picked = (location.state as { picked?: string[] } | null)?.picked;

  const { data: serviceTypes, isError: typesFailed } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const {
    data: mine,
    isPending,
    isError: profileFailed,
  } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  const [rows, setRows] = useState<Draft[]>([]);
  const [workFormat, setWorkFormat] = useState<WorkFormat>('both');
  const [loaded, setLoaded] = useState(false);

  // In the catalog's order, not the order the tiles happened to be tapped.
  // The headings below are contiguous runs of the group field, so a person who
  // ticked insurance first and tutoring second would otherwise get «Документы и
  // жизнь» above «Учёба» — and two headings if they went back for a third.
  const chosen = useMemo(() => {
    if (!picked || !serviceTypes) return [];
    const wanted = new Set(picked);
    return serviceTypes.filter((type) => wanted.has(type.code));
  }, [picked, serviceTypes]);

  // Filled once. Whatever the person already offers is carried in, so a save
  // that replaces the whole list does not throw away the prices they set last
  // time.
  useEffect(() => {
    if (!mine || chosen.length === 0 || loaded) return;
    setWorkFormat(mine.work_format);
    setRows(
      chosen.flatMap((type) => {
        const existing = mine.offers.filter((offer) => offer.service_type_id === type.id);
        return existing.length > 0
          ? existing.map((offer) => fromOffer(type, offer))
          : [blank(type)];
      }),
    );
    setLoaded(true);
  }, [mine, chosen, loaded]);

  /*
   * Offers whose service type the catalog no longer lists.
   *
   * `/taxonomy/service-types` returns only active ones, so a type that was
   * deactivated leaves its offers invisible to the grid — and the save below
   * is authoritative, so anything absent from it is deleted. Carried through
   * untouched: withdrawing a category is our decision, and it should not
   * quietly take somebody's row with it the next time they edit a price.
   *
   * The server has to accept them, and now does — `_apply_offers` allows the
   * active types plus whatever the caller already holds. Sending these without
   * that rule would have been worse than the deletion: a 422 on every save,
   * with nothing on screen to say which row was the reason.
   */
  const unlisted = useMemo(() => {
    if (!mine || !serviceTypes) return [];
    const known = new Set(serviceTypes.map((type) => type.id));
    return mine.offers.filter((offer) => !known.has(offer.service_type_id));
  }, [mine, serviceTypes]);

  const save = useMutation({
    mutationFn: () =>
      api.saveHelper({
        work_format: workFormat,
        offers: [...rows.map(toOffer), ...unlisted.map(keep)],
        // Not an unconditional `true`. Somebody who hid their profile on
        // purpose and then adds a service from the cabinet is adding a
        // service, not asking to be listed again — and `false` here keeps a
        // hidden profile hidden rather than un-hiding it behind their back.
        publish: mine?.status !== 'hidden',
      }),
    onSuccess: (me) => {
      hapticSuccess();
      queryClient.setQueryData(['me'], me);
      void queryClient.invalidateQueries({ queryKey: ['my-helper'] });
      void queryClient.invalidateQueries({ queryKey: ['home'] });
      navigate('/my-helper', { replace: true });
    },
  });

  // A hidden profile stays hidden, so the button must not promise otherwise.
  const hidden = mine?.status === 'hidden';

  useMainButton(
    loaded
      ? {
          text: hidden ? t`Сохранить` : t`Опубликовать`,
          isVisible: true,
          isEnabled: !save.isPending,
          isLoaderVisible: save.isPending,
          onClick: () => save.mutate(),
        }
      : null,
  );

  // Arrived here directly — a reload, or a link. There is nothing to price.
  if (!picked || picked.length === 0) return <Navigate to="/offer" replace />;

  const addSubject = (type: ServiceType, subject: Subject) => {
    hapticSelection();
    setRows((current) => {
      // The first row of a subject-taking service starts with no subject. Fill
      // it rather than leaving an empty one behind, which would save as "this
      // service, no subject" alongside the real ones.
      const empty = current.find(
        (row) => row.service_type_id === type.id && row.subject_id === null,
      );
      if (empty) {
        return current.map((row) =>
          row === empty
            ? { ...row, subject_id: subject.id, subject_name: subject.name }
            : row,
        );
      }
      return [
        ...current,
        {
          ...blank(type),
          key: `${type.id}:${subject.id}`,
          subject_id: subject.id,
          subject_name: subject.name,
          // A new subject inherits what the person already typed for this
          // service. Asking the same price four times is asking three times
          // too many.
          price: current.find((row) => row.service_type_id === type.id)?.price ?? '',
        },
      ];
    });
  };

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Сколько берёшь?</Trans>
      </Title>
      <Sub>
        <Trans>Необязательно. Пустое поле значит «договоримся».</Trans>
      </Sub>

      {typesFailed || profileFailed ? (
        <Empty
          title={<Trans>Не получилось загрузить анкету</Trans>}
          body={<Trans>Проверь связь и попробуй ещё раз.</Trans>}
        />
      ) : isPending || !loaded ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={4} />
        </div>
      ) : (
        <>
          {groupRuns(chosen, (type) => type.group).map(({ key: group, items }) => (
            <div key={group}>
              <Label aside={items.length}>
                <ServiceGroupLabel group={group} />
              </Label>
              {items.map((type) => {
                const mineHere = rows.filter((row) => row.service_type_id === type.id);
                const Icon = iconForService(type.code);
                return (
                  // A box each, with the icon and the colour the category wears
                  // everywhere else. Four services under four grey labels read
                  // as one long list of fields belonging to nothing.
                  <div key={type.id} className={ui.svcCard}>
                    <div className={ui.svcHead}>
                      <Tile tone={type.tone}>
                        <Icon size={19} />
                      </Tile>
                      <span className={ui.svcTitle}>
                        <span className={ui.svcName}>{type.name}</span>
                        {type.hint ? (
                          <span className={ui.svcHint}>{type.hint}</span>
                        ) : null}
                      </span>
                    </div>

                    <div className={ui.svcBody}>
                      {type.requires_subject ? (
                        <>
                          {mineHere.some((row) => row.subject_id !== null) ? (
                            <Chips>
                              {mineHere
                                .filter((row) => row.subject_id !== null)
                                .map((row) => (
                                  <ChipView
                                    key={row.key}
                                    active
                                    removeLabel={t`Убрать`}
                                    onRemove={() =>
                                      setRows((current) => {
                                        const left = current.filter(
                                          (other) => other.key !== row.key,
                                        );
                                        // Removing the last subject must not
                                        // remove the service: the person ticked
                                        // it, and a service with no subject is
                                        // one search cannot reach yet, not one
                                        // they withdrew.
                                        return left.some(
                                          (other) => other.service_type_id === type.id,
                                        )
                                          ? left
                                          : [...left, blank(type)];
                                      })
                                    }
                                  >
                                    {row.subject_name}
                                  </ChipView>
                                ))}
                            </Chips>
                          ) : null}
                          <SubjectSearch
                            onPick={(subject) => addSubject(type, subject)}
                            taken={new Set(mineHere.map((row) => row.subject_id))}
                          />
                        </>
                      ) : null}

                      {/* One price per row, not per service. A tutor really
                          does charge 500 for calculus and 700 for physics, and
                          a single field for the pair rewrites both the first
                          time either is touched. The subject names the line
                          when there is more than one. */}
                      {mineHere.map((row) => (
                        <PriceRow
                          key={row.key}
                          name={mineHere.length > 1 ? row.subject_name : null}
                          value={row.price}
                          unit={row.unit}
                          onPrice={(price) =>
                            setRows((current) =>
                              current.map((other) =>
                                other.key === row.key ? { ...other, price } : other,
                              ),
                            )
                          }
                          onUnit={(unit) =>
                            setRows((current) =>
                              current.map((other) =>
                                other.key === row.key ? { ...other, unit } : other,
                              ),
                            )
                          }
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}

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

          {hidden ? (
            <div style={{ marginTop: 12 }}>
              <Hint>
                <Trans>
                  Анкета скрыта — услуги сохранятся, но в каталоге их не будет. Включить
                  видимость можно в анкете.
                </Trans>
              </Hint>
            </div>
          ) : null}

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
 * One price, and what it is per.
 *
 * The unit belongs to the service rather than to the screen: a profile really
 * does mix them — tutoring by the hour, a thesis by the job — and one control
 * at the top would rewrite "4000 за работу" as "4000 в час".
 */
function PriceRow({
  name,
  value,
  unit,
  onPrice,
  onUnit,
}: {
  /** The subject this price is for, when a service has more than one. */
  name?: string | null;
  value: string;
  unit: PriceUnit;
  onPrice: (price: string) => void;
  onUnit: (unit: PriceUnit) => void;
}) {
  const { t } = useLingui();
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
    // No margin of its own: everything inside a card is spaced by the card.
    <div className={ui.field}>
      {name ? (
        <span
          style={{
            // `flex: none` so the name keeps its width: the input next to it is
            // `flex: 1` and would otherwise squeeze this to two characters and
            // an ellipsis. The cap is what stops a long subject doing the same
            // thing to the input.
            flex: 'none',
            maxWidth: 132,
            color: 'var(--muted)',
            fontSize: 13,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {name}
        </span>
      ) : null}
      <input
        value={value}
        // Digits only, filtered as they are typed. "1 500" and "1,500" both
        // parse to something wrong on a Czech or Russian keyboard, and both
        // save without complaint.
        onChange={(event) => onPrice(event.target.value.replace(/\D/g, '').slice(0, 7))}
        placeholder={t`Сколько`}
        inputMode="numeric"
        aria-label={t`Цена`}
        style={{
          all: 'unset',
          flex: 1,
          minWidth: 0,
          fontVariantNumeric: 'tabular-nums',
        }}
      />
      <span style={{ color: 'var(--muted)', fontSize: 13 }}>Kč</span>
      <select
        value={unit}
        onChange={(event) => onUnit(event.target.value as PriceUnit)}
        aria-label={t`За что цена`}
        style={{
          all: 'unset',
          maxWidth: 104,
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
    </div>
  );
}

/** One offer while it is being edited. The price is a string: an input mid-typing
 *  legitimately holds "" and "4", and parsing on every keystroke turns both into
 *  something the field then has to render back. */
interface Draft {
  key: string;
  service_type_id: number;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  price: string;
  unit: PriceUnit;
  langs: string[];
}

function blank(type: ServiceType): Draft {
  return {
    key: `${type.id}:new`,
    service_type_id: type.id,
    subject_id: null,
    subject_name: null,
    institution_id: null,
    price: '',
    // From the server, not guessed here: a thesis priced by the hour reads as
    // ten times too little.
    unit: type.default_price_unit ?? 'hour',
    langs: [],
  };
}

function fromOffer(type: ServiceType, offer: MyOffer): Draft {
  return {
    key: `${offer.service_type_id}:${offer.subject_id}:${offer.institution_id}`,
    service_type_id: offer.service_type_id,
    subject_id: offer.subject_id,
    subject_name: offer.subject_name,
    institution_id: offer.institution_id,
    // Rounded, because the field holds digits: an older row saved as 550.5
    // would render a decimal point the input then refuses to accept.
    price: offer.price_amount == null ? '' : String(Math.round(offer.price_amount)),
    unit: offer.price_unit ?? type.default_price_unit ?? 'hour',
    langs: offer.langs,
  };
}

/** An offer we are not editing, sent back exactly as it came. */
function keep(offer: MyOffer): OfferInput {
  return {
    service_type_id: offer.service_type_id,
    subject_id: offer.subject_id,
    institution_id: offer.institution_id,
    price_amount: offer.price_amount,
    price_unit: offer.price_unit,
    langs: offer.langs,
  };
}

function toOffer(row: Draft): OfferInput {
  return {
    service_type_id: row.service_type_id,
    subject_id: row.subject_id,
    institution_id: row.institution_id,
    // The field holds digits and nothing else, so there is no parse to get
    // wrong. Empty means "did not say", not free.
    price_amount: row.price ? Number(row.price) : null,
    price_unit: row.unit,
    langs: row.langs,
  };
}
