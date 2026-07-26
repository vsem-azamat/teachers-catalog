import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openLink } from '@tma.js/sdk-react';

import {
  Empty,
  Head,
  Hint,
  Label,
  Screen,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { api } from '@/lib/api';
import type { Placement } from '@/lib/types';

/**
 * The things a foreign student here has to buy anyway.
 *
 * Insurance, a language course that carries a visa, a bank statement, a sworn
 * translation. None of it is ours and all of it is labelled. It sits on a page
 * that is useful even if nothing is tapped — the deadlines are the reason to
 * come, the offers are attached to them — because a page that only sells gets
 * visited once.
 */
export default function LifePage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['placements', 'screen_life'],
    queryFn: ({ signal }) => api.getPlacements({ slot: 'screen_life' }, signal),
  });

  return (
    <Screen>
      <Head />
      <Title>
        <Trans>Не про учёбу</Trans>
      </Title>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            Но без этого не доучишься. Сроки и требования — наши, предложения —
            партнёрские.
          </Trans>
        </Sub>
      </div>

      {isPending ? (
        <>
          <Label>
            <Trans>Загружаем</Trans>
          </Label>
          <SkeletonRows count={3} />
        </>
      ) : isError || data.length === 0 ? (
        <Empty
          title={<Trans>Пока пусто</Trans>}
          body={<Trans>Здесь появятся страховка, визы, банк и переводы.</Trans>}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 18 }}>
          {data.map((placement) => (
            <PartnerBlock key={placement.id} placement={placement} />
          ))}
        </div>
      )}

      <div style={{ marginTop: 18 }}>
        <Hint>
          <Trans>
            Это не наши услуги. Мы получаем комиссию с партнёра, со студента — ничего.
          </Trans>
        </Hint>
      </div>
      <div style={{ height: 24 }} />
    </Screen>
  );
}

function PartnerBlock({ placement }: { placement: Placement }) {
  const open = () => {
    // Counted before the browser leaves, and deliberately not awaited: the tap
    // should open the link now, not after a round trip.
    void api.registerPlacementClick(placement.id).catch(() => undefined);
    openLink(placement.url);
  };

  return (
    <div>
      {placement.context_note ? (
        <div style={{ marginBottom: 9 }}>
          <Hint>{placement.context_note}</Hint>
        </div>
      ) : null}

      <button type="button" className={`${ui.partner} ${ui.pressable}`} onClick={open}>
        <span className={ui.partnerLabel}>
          <Trans>Партнёр</Trans>
        </span>
        <span className={ui.partnerTop}>
          {placement.logo_text ? (
            <span
              className={ui.partnerLogo}
              style={{ background: placement.logo_bg ?? 'var(--surface)' }}
            >
              {placement.logo_text}
            </span>
          ) : null}
          <span style={{ minWidth: 0 }}>
            <span className={ui.partnerName}>{placement.title}</span>
            {placement.subtitle ? (
              <span
                style={{
                  display: 'block',
                  marginTop: 2,
                  fontSize: 11.5,
                  color: 'var(--muted)',
                }}
              >
                {placement.subtitle}
              </span>
            ) : null}
          </span>
          {placement.price_text ? (
            <span className={ui.partnerPrice}>{placement.price_text}</span>
          ) : null}
        </span>
      </button>
    </div>
  );
}
