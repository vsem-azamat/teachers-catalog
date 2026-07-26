import { Trans } from '@lingui/react/macro';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';

import { BookmarkIcon, ChatIcon, PersonIcon, PlusIcon, SearchIcon } from './icons';
import css from './ui.module.css';

const TABS = [
  { to: '/', icon: SearchIcon, label: <Trans>Поиск</Trans> },
  { to: '/mine', icon: BookmarkIcon, label: <Trans>Мои</Trans> },
  { to: '/chats', icon: ChatIcon, label: <Trans>Чаты</Trans> },
  { to: '/profile', icon: PersonIcon, label: <Trans>Профиль</Trans> },
] as const;

/**
 * Four destinations and one action.
 *
 * The round button is not a fifth tab: it posts a request, which is the
 * opposite direction from browsing, and keeping it visually apart is what
 * says so.
 */
export function TabBar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const go = (to: string) => {
    if (to !== pathname) hapticSelection();
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
        onClick={() => go('/ask')}
        aria-label="Создать заявку"
      >
        <PlusIcon size={20} />
      </button>
    </nav>
  );
}
