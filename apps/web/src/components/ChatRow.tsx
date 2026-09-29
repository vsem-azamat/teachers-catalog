import { Trans } from '@lingui/react/macro';
import { openTelegramLink } from '@tma.js/sdk-react';

import { type Activity, chipFor, initials, type PublicChat } from '@/lib/chats';

import { Chevron, Row, Tile } from './Ui';
import css from './ui.module.css';

/**
 * A tile's letters, sized to fit: a faculty's «FSv» or a university's «VŠCHT»
 * is its name, and a fixed size would push it over the tile's edge.
 */
export function Letters({ text }: { text: string }) {
  return (
    <span className={css.letters} data-length={Math.min(text.length, 5)}>
      {text}
    </span>
  );
}

/** Supervisor's word for how much a chat talks, and nothing for `unknown`. */
export function ActivityChip({ activity }: { activity: Activity }) {
  const chip = chipFor(activity);
  if (chip === null) return null;
  return (
    <span
      className={chip === 'busy' ? `${css.activity} ${css.activityBusy}` : css.activity}
    >
      {chip === 'busy' ? (
        <Trans>оживлённый</Trans>
      ) : chip === 'active' ? (
        <Trans>активный</Trans>
      ) : (
        <Trans>тихий</Trans>
      )}
    </span>
  );
}

/**
 * One chat. A tap opens it in Telegram, which is where it lives: the app
 * holds no conversations, only the way in.
 */
export function ChatRow({ chat, tone }: { chat: PublicChat; tone: number }) {
  return (
    <Row
      leading={
        <Tile tone={tone}>
          <Letters text={initials(chat.title)} />
        </Tile>
      }
      title={chat.title}
      hint={
        chipFor(chat.activity) ? <ActivityChip activity={chat.activity} /> : undefined
      }
      trailing={<Chevron />}
      onClick={() => openTelegramLink(chat.link)}
    />
  );
}
