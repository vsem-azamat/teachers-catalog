import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { SubjectSearch } from '@/components/SubjectSearch';
import {
  Chips,
  ChipView,
  Hint,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection, hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
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

  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const { data: mine, isPending } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  const [rows, setRows] = useState<Draft[]>([]);
  const [workFormat, setWorkFormat] = useState<WorkFormat>('both');
  const [loaded, setLoaded] = useState(false);

  const chosen = useMemo(
    () =>
      picked && serviceTypes
        ? picked
            .map((code) => serviceTypes.find((type) => type.code === code))
            .filter((type): type is ServiceType => type !== undefined)
        : [],
    [picked, serviceTypes],
  );

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

  const save = useMutation({
    mutationFn: () =>
      api.saveHelper({
        work_format: workFormat,
        offers: rows.map(toOffer),
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

  useMainButton(
    loaded
      ? {
          text: t`Опубликовать`,
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

      {isPending || !loaded ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={4} />
        </div>
      ) : (
        <>
          {chosen.map((type) => {
            const mineHere = rows.filter((row) => row.service_type_id === type.id);
            return (
              <div key={type.id}>
                <Label>{type.name}</Label>

                {type.requires_subject ? (
                  <>
                    {mineHere.some((row) => row.subject_id !== null) ? (
                      <div style={{ marginBottom: 8 }}>
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
                                    // Removing the last subject must not remove
                                    // the service: the person ticked it, and a
                                    // service with no subject is one search
                                    // cannot reach yet, not one they withdrew.
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
                      </div>
                    ) : null}
                    <SubjectSearch
                      onPick={(subject) => addSubject(type, subject)}
                      taken={new Set(mineHere.map((row) => row.subject_id))}
                    />
                    <div style={{ height: 8 }} />
                  </>
                ) : null}

                {/* One price per row, not per service. A tutor really does
                    charge 500 for calculus and 700 for physics, and a single
                    field for the pair rewrites both the first time either is
                    touched. The subject names the line when there is more than
                    one. */}
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
            );
          })}

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
    <div className={ui.field} style={{ marginTop: 8 }}>
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
