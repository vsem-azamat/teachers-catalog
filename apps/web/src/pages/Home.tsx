import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { SearchIcon } from '@/components/icons';
import { ServiceGrid } from '@/components/ServiceGrid';
import { TabBar } from '@/components/TabBar';
import {
  AvatarStack,
  Count,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Title,
  ui,
} from '@/components/Ui';
import { api } from '@/lib/api';

/**
 * The first screen.
 *
 * The query field sits above the categories, not below them: someone who
 * already knows they need "нострификация аттестата" should never have to find
 * it in a tree. The categories are for the people who came to look around.
 */
export default function HomePage() {
  const navigate = useNavigate();
  const { t } = useLingui();

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  return (
    <>
      <Screen withTabs>
        <AppHeader />
        <Title>
          <Trans>Что нужно?</Trans>
        </Title>

        <button
          type="button"
          className={`${ui.field} ${ui.fieldGhost} ${ui.pressable}`}
          style={{ marginTop: 16 }}
          onClick={() => navigate('/ask')}
        >
          <SearchIcon size={18} className={ui.fieldIcon} />
          <span>{t`матан, čeština B2, přijímačky…`}</span>
        </button>

        {isPending ? (
          <SkeletonRows count={6} />
        ) : isError ? (
          <Rows>
            <Row
              title={<Trans>Не удалось загрузить каталог</Trans>}
              hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
              onClick={() => void refetch()}
            />
          </Rows>
        ) : (
          <>
            {/* Grouped, with a heading per shelf. There used to be a wide
                first cell, because seven tiles in two columns left the last one
                alone in its row; there are twelve now and three headings, so
                the wide cell would create the orphan it was there to fix. */}
            <ServiceGrid
              items={data.people}
              onPick={(section) => navigate(`/results?service=${section.code}`)}
              renderTrailing={(section, wide) =>
                // Faces only in the wide cell. A narrow tile has room for a
                // number or for three overlapping circles, and the number is
                // the one that says something a person cannot already guess.
                wide && section.avatars.length ? (
                  <AvatarStack avatars={section.avatars} />
                ) : section.count ? (
                  <Count>{section.count}</Count>
                ) : null
              }
            />

            {/* Things — gear to rent, textbooks to buy — are not seeded, so
                `/home` always answers with an empty list and the block that
                drew them never rendered. It navigated to `/results?category=`,
                which the results screen does not read: the day somebody seeds a
                category, those rows would have opened a list of *people*
                unfiltered. Deleted rather than left with a dead link, because
                the screen that lists things does not exist yet either, and it
                will be written against a real one. */}
          </>
        )}
      </Screen>
      <TabBar />
    </>
  );
}
