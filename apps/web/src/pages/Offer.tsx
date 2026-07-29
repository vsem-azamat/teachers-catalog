import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ServiceGrid } from '@/components/ServiceGrid';
import { Hint, Screen, SkeletonRows, Sub, Title } from '@/components/Ui';
import { hapticSelection, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';

/**
 * What can you help with?
 *
 * This replaced a textarea. Someone used to write a paragraph and a parser
 * guessed subjects and a price out of it, which made the parser the gatekeeper:
 * a person offering something the taxonomy had never heard of wrote three
 * sentences and got nothing back. Tiles cannot fail to be understood.
 *
 * Multiple choice, not one at a time. The people worth having in the catalog
 * are the ones who can do four things, and asking them to walk the same form
 * four times is how you end up with a catalog of people who can do one.
 *
 * Tiles the person already offers start ticked. That is not a convenience: the
 * save replaces the whole offer list, so a screen that started empty would
 * quietly delete everything they had the moment they added something new.
 */
export default function OfferPage() {
  const navigate = useNavigate();
  const { t } = useLingui();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  const { data: serviceTypes, isPending } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const { data: mine } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  // Once, from the server. Re-running this on every render would undo each tap
  // the moment the query refetched.
  useEffect(() => {
    if (!mine || !serviceTypes || loaded) return;
    const byId = new Map(serviceTypes.map((type) => [type.id, type.code]));
    const already = new Set<string>();
    for (const offer of mine.offers) {
      const code = byId.get(offer.service_type_id);
      if (code) already.add(code);
    }
    setPicked(already);
    setLoaded(true);
  }, [mine, serviceTypes, loaded]);

  const toggle = (code: string) => {
    hapticSelection();
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  useMainButton(
    picked.size > 0
      ? {
          text: t`Дальше · ${picked.size}`,
          isVisible: true,
          isEnabled: true,
          onClick: () => navigate('/offer/prices', { state: { picked: [...picked] } }),
        }
      : { text: t`Выбери, чем можешь помочь`, isVisible: true, isEnabled: false },
  );

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Чем ты можешь помочь?</Trans>
      </Title>
      <Sub>
        <Trans>Отметь всё, что умеешь. Цены спросим на следующем экране.</Trans>
      </Sub>

      {isPending || !serviceTypes ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={6} />
        </div>
      ) : (
        <ServiceGrid
          items={serviceTypes}
          selected={picked}
          onToggle={toggle}
          renderNote={(group) =>
            group === 'life' ? (
              <div style={{ marginTop: -4, marginBottom: 10 }}>
                <Hint>
                  <Trans>
                    Сейчас бесплатно. Когда людей станет больше, размещение таких услуг
                    станет платным.
                  </Trans>
                </Hint>
              </div>
            ) : null
          }
        />
      )}
    </Screen>
  );
}
