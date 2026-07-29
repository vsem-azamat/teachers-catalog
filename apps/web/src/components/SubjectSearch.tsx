import { useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { Row, Rows, ui } from '@/components/Ui';
import { api } from '@/lib/api';
import type { Subject } from '@/lib/types';

/**
 * Find a subject by typing.
 *
 * Fuzzy on the server, so "matan" and "матан" both land on the same node —
 * which is the whole reason this is a search box and not a tree to browse.
 *
 * Shared by the cabinet and by the offer flow. It was private to the cabinet
 * until the offer screen needed the same thing, and a second copy would have
 * been a second debounce, a second minimum length, and two ideas about what
 * counts as already taken.
 */
export function SubjectSearch({
  onPick,
  taken,
  placeholder,
  disabled = false,
}: {
  onPick: (subject: Subject) => void;
  /** Ids already chosen, so the list does not offer them again. */
  taken: Set<number | null>;
  placeholder?: string;
  disabled?: boolean;
}) {
  const { t } = useLingui();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data } = useQuery({
    queryKey: ['subject-search', debounced],
    queryFn: ({ signal }) => api.searchSubjects(debounced, 6, signal),
    enabled: debounced.length >= 2,
  });

  const results = useMemo(
    () => (data ?? []).filter((subject) => !taken.has(subject.id)),
    [data, taken],
  );

  return (
    <>
      <div className={ui.field}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder ?? t`Добавить предмет — матан, čeština, физика`}
          disabled={disabled}
          maxLength={200}
          style={{ all: 'unset', width: '100%' }}
        />
      </div>
      {results.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Rows>
            {results.map((subject) => (
              <Row
                key={subject.id}
                title={subject.name}
                onClick={() => {
                  onPick(subject);
                  setQuery('');
                  setDebounced('');
                }}
              />
            ))}
          </Rows>
        </div>
      ) : null}
    </>
  );
}
