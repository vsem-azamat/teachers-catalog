import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { iconForService, SearchIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import {
  AvatarStack,
  Cell,
  Count,
  Grid,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { api } from '@/lib/api';
import type { HomeSection } from '@/lib/types';

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

        {/* "Люди" only earns its line when there is a second group under it to
            be told apart from. On its own it labels the whole screen, which
            the heading above already does. */}
        {data && data.things.length > 0 ? (
          <Label>
            <Trans>Люди</Trans>
          </Label>
        ) : (
          <div style={{ height: 18 }} />
        )}

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
            {/* The first one spans both columns. Seven categories in two
                columns leaves the last one alone in its row, which reads as
                something failing to load; giving the widest use of the catalog
                the wide cell fixes the shape and says which it is. */}
            <Grid>
              {data.people.map((section, index) => (
                <SectionCell
                  key={section.code}
                  section={section}
                  wide={index === 0}
                  onClick={() => navigate(`/results?service=${section.code}`)}
                />
              ))}
            </Grid>

            {data.things.length > 0 ? (
              <>
                <Label>
                  <Trans>Вещи</Trans>
                </Label>
                <Rows>
                  {data.things.map((section) => (
                    <Row
                      key={section.code}
                      onClick={() => navigate(`/results?category=${section.code}`)}
                      leading={
                        <Tile tone={section.tone}>
                          <SectionIcon section={section} />
                        </Tile>
                      }
                      title={section.name}
                      hint={section.hint}
                      trailing={section.count ? <Count>{section.count}</Count> : null}
                    />
                  ))}
                </Rows>
              </>
            ) : null}
          </>
        )}
      </Screen>
      <TabBar />
    </>
  );
}

function SectionIcon({ section }: { section: HomeSection }) {
  const Icon = iconForService(section.code);
  return <Icon size={19} />;
}

function SectionCell({
  section,
  wide,
  onClick,
}: {
  section: HomeSection;
  wide: boolean;
  onClick: () => void;
}) {
  return (
    <Cell
      wide={wide}
      onClick={onClick}
      leading={
        <Tile tone={section.tone}>
          <SectionIcon section={section} />
        </Tile>
      }
      title={section.name}
      hint={section.hint}
      trailing={
        // Faces only in the wide cell. A narrow tile has room for a number or
        // for three overlapping circles, and the number is the one that says
        // something a person cannot already guess.
        wide && section.avatars.length ? (
          <AvatarStack avatars={section.avatars} />
        ) : section.count ? (
          <Count>{section.count}</Count>
        ) : null
      }
    />
  );
}
