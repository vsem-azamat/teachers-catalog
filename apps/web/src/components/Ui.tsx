/**
 * The shared vocabulary of the interface.
 *
 * Six colour tones, referenced by index, chosen by the server. That is what
 * keeps a person the same colour on the results list and on their own page
 * without the client having to remember anything.
 */

import type { ReactNode } from 'react';

import type { Avatar, Price } from '@/lib/types';

import { ChevronIcon, CloseIcon } from './icons';
import css from './ui.module.css';

const TONES = 6;

function toneStyle(tone: number): React.CSSProperties {
  const index = ((tone % TONES) + TONES) % TONES;
  return {
    background: `var(--tone-${index}-bg)`,
    color: `var(--tone-${index}-fg)`,
  };
}

// ── layout ──────────────────────────────────────────────────────────────

export function Screen({
  children,
  withTabs = false,
}: {
  children: ReactNode;
  withTabs?: boolean;
}) {
  return (
    <div className={withTabs ? `${css.screen} ${css.withTabs}` : css.screen}>
      {children}
    </div>
  );
}

export function Head({ right }: { right?: ReactNode }) {
  return (
    <header className={css.head}>
      <span className={css.wordmark}>Konnekt</span>
      {right}
    </header>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <h1 className={css.h1}>{children}</h1>;
}

export function Heading({ children }: { children: ReactNode }) {
  return <h2 className={css.h2}>{children}</h2>;
}

export function Label({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className={css.label}>
      <span>{children}</span>
      {aside ? <span>{aside}</span> : null}
    </div>
  );
}

export function Sub({ children }: { children: ReactNode }) {
  return <p className={css.sub}>{children}</p>;
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className={css.hint}>{children}</p>;
}

// ── atoms ───────────────────────────────────────────────────────────────

export function Tile({ tone, children }: { tone: number; children: ReactNode }) {
  return (
    <span className={css.tile} style={toneStyle(tone)}>
      {children}
    </span>
  );
}

export function AvatarView({
  avatar,
  size = 24,
  square = false,
  short = false,
}: {
  avatar: Avatar;
  size?: number;
  square?: boolean;
  /** One letter instead of two — for stacks, where the next circle covers the second. */
  short?: boolean;
}) {
  const style: React.CSSProperties = {
    ...toneStyle(avatar.tone),
    width: size,
    height: size,
    fontSize: Math.round(size * 0.4),
  };
  const className = square ? `${css.avatar} ${css.avatarSquare}` : css.avatar;

  // A Telegram photo URL expires; the monogram is what is left when it does.
  if (avatar.photo_url) {
    return (
      <img
        className={className}
        style={style}
        src={avatar.photo_url}
        alt=""
        width={size}
        height={size}
      />
    );
  }
  return (
    <span className={className} style={style} aria-hidden="true">
      {short ? avatar.initials.slice(0, 1) : avatar.initials}
    </span>
  );
}

export function AvatarStack({
  avatars,
  size = 24,
  ring,
}: {
  avatars: Avatar[];
  size?: number;
  ring?: string;
}) {
  if (!avatars.length) return null;
  return (
    <div
      className={css.stack}
      style={ring ? ({ '--stack-ring': ring } as React.CSSProperties) : undefined}
    >
      {avatars.map((avatar) => (
        <AvatarView key={avatar.id} avatar={avatar} size={size} short />
      ))}
    </div>
  );
}

export function Count({ children }: { children: ReactNode }) {
  return <span className={css.count}>{children}</span>;
}

export function Chevron() {
  return <ChevronIcon size={17} className={css.chevron} />;
}

export function Badge({ children }: { children: ReactNode }) {
  return <span className={css.badge}>{children}</span>;
}

// ── rows ────────────────────────────────────────────────────────────────

export function Rows({ children }: { children: ReactNode }) {
  return <div className={css.rows}>{children}</div>;
}

export function Row({
  leading,
  title,
  hint,
  trailing,
  badge,
  onClick,
}: {
  leading?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  trailing?: ReactNode;
  badge?: ReactNode;
  onClick?: () => void;
}) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      className={`${css.row} ${css.pressable}`}
      type={onClick ? 'button' : undefined}
      onClick={onClick}
    >
      {badge ? <Badge>{badge}</Badge> : null}
      {leading}
      <span className={css.rowBody}>
        <span className={css.rowName}>{title}</span>
        {hint ? <span className={css.rowHint}>{hint}</span> : null}
      </span>
      {trailing ? <span className={css.rowTrailing}>{trailing}</span> : null}
    </Tag>
  );
}

// ── chips ───────────────────────────────────────────────────────────────

export function Chips({ children }: { children: ReactNode }) {
  return <div className={css.chips}>{children}</div>;
}

export function ChipView({
  children,
  active = false,
  ghost = false,
  onRemove,
  onClick,
  removeLabel,
}: {
  children: ReactNode;
  active?: boolean;
  ghost?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
  removeLabel?: string;
}) {
  const className = [css.chip, active && css.chipOn, ghost && css.chipGhost]
    .filter(Boolean)
    .join(' ');

  const body = (
    <>
      {children}
      {onRemove ? (
        <button
          type="button"
          className={css.chipRemove}
          aria-label={removeLabel}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          <CloseIcon size={12} />
        </button>
      ) : null}
    </>
  );

  // A chip that only removes is not itself a button; nesting one inside
  // another is invalid and breaks keyboard order.
  if (onClick && !onRemove) {
    return (
      <button type="button" className={`${className} ${css.pressable}`} onClick={onClick}>
        {body}
      </button>
    );
  }
  return <span className={className}>{body}</span>;
}

// ── cards ───────────────────────────────────────────────────────────────

export function Cards({ children }: { children: ReactNode }) {
  return <div className={css.cards}>{children}</div>;
}

export function Card({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick?: () => void;
}) {
  if (onClick) {
    return (
      <button type="button" className={`${css.card} ${css.pressable}`} onClick={onClick}>
        {children}
      </button>
    );
  }
  return <div className={css.card}>{children}</div>;
}

export function PriceView({ price, unitLabel }: { price: Price; unitLabel: ReactNode }) {
  if (price.amount == null) return null;
  return (
    <span className={css.price}>
      <b className={css.priceAmount}>
        {formatMoney(price.amount)} {price.currency === 'CZK' ? 'Kč' : price.currency}
      </b>
      <span className={css.priceUnit}>{unitLabel}</span>
    </span>
  );
}

/** Thin spaces between thousands: "8 900", the way prices are written here. */
export function formatMoney(amount: number): string {
  return Math.round(amount)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function Reason({
  children,
  weak = false,
}: {
  children: ReactNode;
  weak?: boolean;
}) {
  return (
    <p className={css.reason}>
      <i className={weak ? `${css.reasonDot} ${css.weak}` : css.reasonDot} />
      <span>{children}</span>
    </p>
  );
}

export function Free({ children }: { children: ReactNode }) {
  return (
    <p className={css.free}>
      <i className={css.freeDot} />
      {children}
    </p>
  );
}

// ── segmented control ───────────────────────────────────────────────────

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className={css.seg} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          className={css.segItem}
          aria-selected={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── states ──────────────────────────────────────────────────────────────

export function Empty({ title, body }: { title: ReactNode; body?: ReactNode }) {
  return (
    <div className={css.empty}>
      <p className={css.emptyTitle}>{title}</p>
      {body ? <p className={css.emptyBody}>{body}</p> : null}
    </div>
  );
}

/**
 * Placeholder rows in the shape of the real ones.
 *
 * A spinner tells you to wait; this tells you what is coming and stops the
 * layout jumping when it lands.
 */
export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className={css.rows} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity and never reorder
        <div key={index} className={css.skeleton} style={{ height: 'var(--h-row)' }} />
      ))}
    </div>
  );
}

export { css as ui };
