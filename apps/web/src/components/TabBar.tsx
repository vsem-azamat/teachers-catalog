import { Trans, useLingui } from '@lingui/react/macro';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';

import { BookmarkIcon, PlusIcon, SearchIcon } from './icons';
import { Pick, Sheet } from './Sheet';
import { Tile } from './Ui';
import css from './ui.module.css';

/**
 * Two destinations and one action.
 *
 * It used to be four. "Профиль" moved to the avatar in the header, where a
 * person's own face is a better label than the word; "Чаты" was removed
 * outright, because the screen behind it existed only to say that we do not
 * have chats and that conversations happen in Telegram. A tab that explains an
 * absence is worse than no tab.
 *
 * The round button is not a third tab: it posts something, which is the
 * opposite direction from browsing, and keeping it visually apart is what says
 * so.
 */
const TABS = [
  { to: '/', icon: SearchIcon, label: <Trans>Поиск</Trans> },
  { to: '/mine', icon: BookmarkIcon, label: <Trans>Заявки</Trans> },
] as const;

export function TabBar() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [posting, setPosting] = useState(false);

  const go = (to: string) => {
    if (to !== pathname) hapticSelection();
    navigate(to);
  };

  const post = (to: string) => {
    hapticSelection();
    setPosting(false);
    navigate(to);
  };

  return (
    <nav className={css.tabs}>
      {TABS.map(({ to, icon: Icon, label }) => (
        <button
          key={to}
          type="button"
          className={css.tab}
          aria-current={pathname === to ? 'page' : undefined}
          onClick={() => go(to)}
        >
          <Icon size={21} />
          {label}
        </button>
      ))}

      <button
        type="button"
        className={css.fab}
        aria-label={t`Разместить`}
        aria-haspopup="dialog"
        onClick={() => {
          hapticSelection();
          setPosting(true);
        }}
      >
        <PlusIcon size={20} />
      </button>

      {/*
        Asked here rather than settled by a mode switch at the top of the app.
        A student/helper toggle doubles the interface for the few people who
        offer something, and makes everyone else carry a control they will
        never touch. The question costs one tap, and only the people who press
        the button ever see it.
      */}
      {posting ? (
        <Sheet
          title={t`Что делаем?`}
          closeLabel={t`Закрыть`}
          onClose={() => setPosting(false)}
        >
          <Pick
            leading={
              <Tile tone={0}>
                <SearchIcon size={19} />
              </Tile>
            }
            name={<Trans>Мне нужна помощь</Trans>}
            hint={<Trans>опиши задачу — придут отклики</Trans>}
            onClick={() => post('/ask')}
          />
          <Pick
            leading={
              <Tile tone={1}>
                <PlusIcon size={19} />
              </Tile>
            }
            name={<Trans>Предлагаю услугу</Trans>}
            hint={<Trans>репетиторство, работы, помощь</Trans>}
            onClick={() => post('/become-helper')}
          />
        </Sheet>
      ) : null}
    </nav>
  );
}
