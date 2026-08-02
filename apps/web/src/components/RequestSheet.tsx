import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { hapticSelection, hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
import type { Chip, RequestCreate } from '@/lib/types';
import { Sheet } from './Sheet';
import { Action, Chips, ChipView, Hint, ui } from './Ui';

/**
 * Which axis each kind of chip is.
 *
 * Only the four the search filters on, and only the ones whose value is a
 * number: a deadline is neither, which is why the sheet has no chip for it.
 */
const AXIS = {
  subject: 'subject_id',
  institution: 'institution_id',
  service_type: 'service_type_id',
  budget: 'budget_max',
} as const satisfies Record<string, keyof RequestCreate>;

/**
 * Turn the search that is already on screen into a request.
 *
 * Nothing here is a new form. The words are the ones the person typed, the
 * chips are the ones the search is already filtering on, and the only decision
 * left is which of them the request should carry — a tutor for this subject at
 * any school is an ordinary thing to want, and removing the school chip is how
 * you say it.
 *
 * A removed chip is sent as an explicit `null` rather than left out. The server
 * reads anything the caller did not mention out of the text, so leaving it out
 * would put the school straight back — see `services/requests.create`.
 *
 * The deadline is not among the chips: it is not a filter, so the search never
 * carried one. It still reaches the request, because the server reads the text,
 * and the words are right there to edit.
 */
export function RequestSheet({
  text,
  chips,
  onClose,
}: {
  text: string;
  chips: Chip[];
  onClose: () => void;
}) {
  const { t, i18n } = useLingui();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [words, setWords] = useState(text);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  // Empty string is "not asked for" and not zero: the field only exists once
  // somebody taps the chip that adds it.
  const [budget, setBudget] = useState<string | null>(null);

  const hasBudget = chips.some((chip) => chip.kind === 'budget');

  const post = useMutation({
    mutationFn: () => api.createRequest(payload()),
    onSuccess: () => {
      hapticSuccess();
      void queryClient.invalidateQueries({ queryKey: ['requests'] });
      navigate('/mine');
    },
  });

  function payload(): RequestCreate {
    const body: RequestCreate = { text: words.trim() };
    for (const chip of chips) {
      const axis = AXIS[chip.kind as keyof typeof AXIS];
      if (!axis || chip.value == null) continue;
      // Mentioned either way: kept means "this one", removed means "any". Only
      // an axis the search never carried is left for the text to answer.
      body[axis] = dropped.has(chipKey(chip)) ? null : Number(chip.value);
    }
    if (budget) body.budget_max = Number(budget);
    return body;
  }

  const enough = words.trim().length >= 3;

  return (
    <Sheet title={<Trans>Что нужно</Trans>} onClose={onClose} closeLabel={t`Закрыть`}>
      <div className={`${ui.field} ${ui.fieldTall}`}>
        <textarea
          value={words}
          onChange={(event) => setWords(event.target.value)}
          aria-label={t`Что нужно`}
          rows={2}
          maxLength={2000}
          style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.45 }}
        />
      </div>

      <Chips>
        {chips.map((chip) => {
          const key = chipKey(chip);
          const isDropped = dropped.has(key);
          return (
            <ChipView
              key={key}
              active={!isDropped}
              ghost={isDropped}
              removeLabel={t`Убрать`}
              onRemove={
                isDropped
                  ? undefined
                  : () => {
                      hapticSelection();
                      setDropped(new Set(dropped).add(key));
                    }
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
        {/* Only when the sentence carried none. A budget is the one thing
            people leave out of the words and mean anyway. */}
        {!hasBudget && budget === null ? (
          <ChipView
            ghost
            onClick={() => {
              hapticSelection();
              setBudget('');
            }}
          >
            <Trans>+ бюджет</Trans>
          </ChipView>
        ) : null}
      </Chips>

      {budget !== null ? (
        <div className={ui.field}>
          <input
            value={budget}
            onChange={(event) => setBudget(event.target.value.replace(/\D/g, ''))}
            inputMode="numeric"
            placeholder={t`Сколько готов платить`}
            aria-label={t`Сколько готов платить`}
            style={{ all: 'unset', width: '100%' }}
          />
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>Kč</span>
        </div>
      ) : null}

      {post.isError ? (
        <Hint>
          <PostError error={post.error} />
        </Hint>
      ) : (
        <Hint>
          <Trans>
            Заявку увидят все, кто предлагает помощь. Дату из текста поймём сами.
          </Trans>
        </Hint>
      )}

      <Action disabled={!enough || post.isPending} onClick={() => post.mutate()}>
        <Trans>Опубликовать заявку</Trans>
      </Action>
    </Sheet>
  );
}

/**
 * Why it did not post.
 *
 * The 409 is the one worth naming: "try again" invites a retry that cannot
 * succeed while the earlier request is open, and the person would keep tapping.
 */
function PostError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 409) {
    return <Trans>Такая заявка уже открыта — она в разделе «Заявки»</Trans>;
  }
  return <Trans>Не отправилось — попробуй ещё раз.</Trans>;
}
