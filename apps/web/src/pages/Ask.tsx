import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { CheckIcon, ClockIcon, PlusIcon, SearchIcon } from '@/components/icons';
import { ClarifyOptionLabel, formatDay, PhraseView } from '@/components/Phrase';
import {
  Chips,
  ChipView,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  Sub,
  Tile,
  ui,
} from '@/components/Ui';
import { useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { Chip, ParseResult } from '@/lib/types';

const OPTION_ICON: Record<string, typeof CheckIcon> = {
  exam_prep: CheckIcon,
  exam_live_help: ClockIcon,
  both: PlusIcon,
};

/**
 * One field, then what we made of it.
 *
 * This screen exists so the catalog can have a single input instead of a
 * category tree. It shows the parse back as chips the person can remove, and
 * asks at most one question — and only when the answer changes the result.
 */
export default function AskPage() {
  const navigate = useNavigate();
  const { t, i18n } = useLingui();
  const [text, setText] = useState('');
  const [parsed, setParsed] = useState<ParseResult | null>(null);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [answer, setAnswer] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const parse = useMutation({
    mutationFn: (value: string) => api.parseQuery(value),
    onSuccess: (result) => {
      setParsed(result);
      setDropped(new Set());
      setAnswer(null);
    },
  });

  // Parse as the person pauses, not on every keystroke: each call is a round
  // trip and a logged query, and mid-word text parses to nonsense anyway.
  // The debounce must restart on the text and on nothing else: including the
  // mutation would reset the timer on every state change the mutation makes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const value = text.trim();
    if (value.length < 3) {
      setParsed(null);
      return;
    }
    const timer = setTimeout(() => parse.mutate(value), 450);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const kept = (parsed?.chips ?? []).filter((chip) => !dropped.has(chipKey(chip)));
  const ready = kept.length > 0 || Boolean(answer);

  useMainButton(
    ready
      ? {
          text:
            parsed && parsed.matches > 0
              ? t`Показать ${parsed.matches}`
              : t`Искать всё равно`,
          isVisible: true,
          isEnabled: true,
          isLoaderVisible: parse.isPending,
          onClick: () => navigate(`/results?${toQuery(kept, answer)}`),
        }
      : null,
  );

  return (
    <Screen>
      <div className={ui.field} style={{ alignItems: 'flex-start' }}>
        <SearchIcon size={18} className={ui.fieldIcon} />
        <textarea
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t`нужен матан на ČVUT, экзамен 14 февраля`}
          rows={2}
          style={{
            all: 'unset',
            width: '100%',
            resize: 'none',
            lineHeight: 1.4,
          }}
        />
      </div>

      {parsed?.note ? (
        <div style={{ marginTop: 14 }}>
          <Sub>
            <PhraseView phrase={parsed.note} locale={i18n.locale} />
          </Sub>
        </div>
      ) : null}

      {kept.length > 0 || (parsed?.chips.length ?? 0) > 0 ? (
        <>
          <Label>
            <Trans>Поняли так — поправь, если не то</Trans>
          </Label>
          <Chips>
            {(parsed?.chips ?? []).map((chip) => {
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
                  {chipLabel(chip, i18n.locale)}
                </ChipView>
              );
            })}
          </Chips>
        </>
      ) : null}

      {parsed?.clarify ? (
        <>
          <Label>
            <PhraseView
              phrase={{ code: parsed.clarify.code, params: {} }}
              locale={i18n.locale}
            />
          </Label>
          <Rows>
            {parsed.clarify.options.map((option) => {
              const Icon = OPTION_ICON[option.code] ?? CheckIcon;
              return (
                <Row
                  key={option.code}
                  onClick={() => setAnswer(option.code)}
                  leading={
                    <Tile tone={option.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={<ClarifyOptionLabel code={option.code} />}
                  trailing={answer === option.code ? <CheckIcon size={18} /> : undefined}
                />
              );
            })}
          </Rows>
          <div style={{ marginTop: 14 }}>
            <Hint>
              <Trans>
                Дальше вопросов не будет — остальное отфильтруешь прямо в списке.
              </Trans>
            </Hint>
          </div>
        </>
      ) : null}
    </Screen>
  );
}

function chipKey(chip: Chip): string {
  return `${chip.kind}:${chip.value ?? chip.label}`;
}

function chipLabel(chip: Chip, locale: string): string {
  if (chip.kind === 'deadline') return formatDay(chip.label, locale);
  if (chip.kind === 'budget') return `≤ ${chip.label} Kč`;
  return chip.label;
}

/** Turn the chips the person kept into the search query string. */
function toQuery(chips: Chip[], answer: string | null): string {
  const params = new URLSearchParams();
  for (const chip of chips) {
    if (chip.value == null) continue;
    if (chip.kind === 'subject') params.set('subject_id', String(chip.value));
    if (chip.kind === 'institution') params.set('institution_id', String(chip.value));
    if (chip.kind === 'service_type') params.set('service_type_id', String(chip.value));
    if (chip.kind === 'budget') params.set('max_price', String(chip.value));
  }
  // The answer to the clarifying question is a service type by name; the
  // results screen resolves it, because it already loads the list.
  if (answer && answer !== 'both') params.set('service', answer);
  return params.toString();
}
