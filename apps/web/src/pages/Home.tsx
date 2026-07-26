import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { iconForService, SearchIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import {
  AvatarStack,
  Count,
  Head,
  Label,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { useTelegramUser } from '@/hooks/useTelegram';
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
  const user = useTelegramUser();

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['home'],
    queryFn: ({ signal }) => api.getHome(signal),
  });

  return (
    <>
      <Screen withTabs>
        <Head
          right={
            user?.photo_url ? (
              <img
                className={ui.avatar}
                src={user.photo_url}
                alt=""
                style={{ width: 30, height: 30 }}
              />
            ) : null
          }
        />
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

        <Label>
          <Trans>Люди</Trans>
        </Label>

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
            <Rows>
              {data.people.map((section) => (
                <SectionRow
                  key={section.code}
                  section={section}
                  onClick={() => navigate(`/results?service=${section.code}`)}
                />
              ))}
            </Rows>

            {data.things.length > 0 ? (
              <>
                <Label>
                  <Trans>Вещи</Trans>
                </Label>
                <Rows>
                  {data.things.map((section) => (
                    <SectionRow
                      key={section.code}
                      section={section}
                      onClick={() => navigate(`/results?category=${section.code}`)}
                    />
                  ))}
                </Rows>
              </>
            ) : null}
          </>
        )}
        <div style={{ height: 20 }} />
      </Screen>
      <TabBar />
    </>
  );
}

function SectionRow({ section, onClick }: { section: HomeSection; onClick: () => void }) {
  const Icon = iconForService(section.code);
  return (
    <Row
      onClick={onClick}
      leading={
        <Tile tone={section.tone}>
          <Icon size={19} />
        </Tile>
      }
      title={section.name}
      hint={section.hint}
      trailing={
        section.avatars.length ? (
          <AvatarStack avatars={section.avatars} />
        ) : section.count ? (
          <Count>{section.count}</Count>
        ) : null
      }
    />
  );
}
