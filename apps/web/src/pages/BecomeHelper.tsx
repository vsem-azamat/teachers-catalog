import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { ClockIcon } from '@/components/icons';
import { PriceUnitLabel, WorkFormatLabel } from '@/components/Phrase';
import {
  Chips,
  ChipView,
  Heading,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  Sub,
  Tile,
  ui,
} from '@/components/Ui';
import { hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { Chip, IntroResult, OfferInput } from '@/lib/types';

const EXAMPLE = `Учусь на FEL, третий курс. Могу подтянуть матан и линейку, сам сдавал на A. Беру 500 в час, онлайн или в Дейвице.`;

/**
 * Becoming a helper is one text field.
 *
 * Not a four-step wizard: someone deciding whether to bother will abandon a
 * wizard on step two. They write a paragraph the way they would to a friend,
 * and the parse comes back as chips they can correct — which also shows them
 * they were understood before anything is published.
 */
export default function BecomeHelperPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { t } = useLingui();
  const [text, setText] = useState('');
  const [intro, setIntro] = useState<IntroResult | null>(null);
  const [dropped, setDropped] = useState<Set<string>>(new Set());

  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const read = useMutation({
    mutationFn: (value: string) => api.readIntro(value),
    onSuccess: (result) => {
      setIntro(result);
      setDropped(new Set());
    },
  });

  const publish = useMutation({
    mutationFn: api.saveHelper,
    onSuccess: (me) => {
      hapticSuccess();
      queryClient.setQueryData(['me'], me);
      void queryClient.invalidateQueries({ queryKey: ['home'] });
      navigate('/profile');
    },
  });

  // The debounce must restart on the text and on nothing else: including the
  // mutation would reset the timer on every state change the mutation makes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const value = text.trim();
    if (value.length < 20) {
      setIntro(null);
      return;
    }
    const timer = setTimeout(() => read.mutate(value), 600);
    return () => clearTimeout(timer);
  }, [text]);

  const keptSubjects = (intro?.chips ?? []).filter(
    (chip) => chip.kind === 'subject' && !dropped.has(chipKey(chip)),
  );
  const tutoringId = serviceTypes?.find((type) => type.code === 'tutoring')?.id;
  const canPublish = keptSubjects.length > 0 && tutoringId !== undefined;

  useMainButton(
    canPublish
      ? {
          text: t`Опубликовать`,
          isVisible: true,
          isEnabled: !publish.isPending,
          isLoaderVisible: publish.isPending,
          onClick: () =>
            publish.mutate({
              about: text.trim(),
              raw_intro: text.trim(),
              work_format: intro?.work_format ?? 'both',
              publish: true,
              offers: toOffers(keptSubjects, tutoringId, intro),
            }),
        }
      : null,
  );

  return (
    <Screen>
      <div style={{ paddingTop: 8 }}>
        <Heading>
          <Trans>Расскажи своими словами</Trans>
        </Heading>
      </div>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>Одним куском, как другу. Анкету соберём сами.</Trans>
        </Sub>
      </div>

      <div className={ui.field} style={{ marginTop: 14, alignItems: 'flex-start' }}>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={EXAMPLE}
          rows={5}
          style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.5 }}
        />
      </div>

      {intro ? (
        <>
          <Label>
            <Trans>Получилось так</Trans>
          </Label>
          <Chips>
            {intro.chips.map((chip) => {
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
                  <ChipLabel chip={chip} intro={intro} />
                </ChipView>
              );
            })}
          </Chips>

          {intro.missing.length > 0 ? (
            <>
              <Label>
                <Trans>Не хватает</Trans>
              </Label>
              <Rows>
                {intro.missing.map((code) => (
                  <Row
                    key={code}
                    leading={
                      <Tile tone={1}>
                        <ClockIcon size={19} />
                      </Tile>
                    }
                    title={<MissingLabel code={code} />}
                  />
                ))}
              </Rows>
              <div style={{ marginTop: 12 }}>
                <Hint>
                  <Trans>
                    Без расписания анкету покажем, но реже — люди чаще пишут тем, у кого
                    видно свободные дни.
                  </Trans>
                </Hint>
              </div>
            </>
          ) : null}
        </>
      ) : (
        <div style={{ marginTop: 14 }}>
          <Hint>
            <Trans>
              Напиши хотя бы пару предложений — предметы, цену и как удобно заниматься.
            </Trans>
          </Hint>
        </div>
      )}

      <div style={{ height: 24 }} />
    </Screen>
  );
}

/** A raw "500" or "online" means nothing on its own. */
function ChipLabel({ chip, intro }: { chip: Chip; intro: IntroResult }) {
  if (chip.kind === 'price') {
    return (
      <>
        {chip.label} Kč <PriceUnitLabel unit={intro.price?.unit ?? 'hour'} />
      </>
    );
  }
  if (chip.kind === 'work_format') {
    return <WorkFormatLabel format={String(chip.value ?? chip.label)} />;
  }
  return <>{chip.label}</>;
}

function MissingLabel({ code }: { code: string }) {
  switch (code) {
    case 'subjects':
      return <Trans>Какие предметы</Trans>;
    case 'price':
      return <Trans>Сколько берёшь</Trans>;
    case 'work_format':
      return <Trans>Онлайн или очно</Trans>;
    case 'availability':
      return <Trans>Когда ты свободен</Trans>;
    default:
      return <>{code}</>;
  }
}

function chipKey(chip: Chip): string {
  return `${chip.kind}:${chip.value ?? chip.label}`;
}

/** One offer per subject the person kept, all on the same terms. */
function toOffers(
  subjects: Chip[],
  serviceTypeId: number,
  intro: IntroResult | null,
): OfferInput[] {
  return subjects.map((chip) => ({
    service_type_id: serviceTypeId,
    subject_id: typeof chip.value === 'number' ? chip.value : null,
    institution_id: intro?.institution_id ?? null,
    price_amount: intro?.price?.amount ?? null,
    price_unit: intro?.price?.unit ?? 'hour',
  }));
}
