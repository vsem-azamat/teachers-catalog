import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { SearchIcon } from '@/components/icons';
import { Hint, Row, Rows, ui } from '@/components/Ui';
import { api } from '@/lib/api';
import type { Institution } from '@/lib/types';

/**
 * Which school, for the one kind of help that is about a particular one.
 *
 * `entrance_prep` is the only service type with `requires_institution`, and
 * until now nothing asked: the flag was read by no screen, so preparation for
 * ČVUT's entrance exam was stored the same way as preparation for nobody's.
 *
 * Filtered here rather than on the server, unlike subjects. The whole list is
 * sixteen universities and their faculties, it is reference data that changes
 * about never, and every other screen has already cached it — a search endpoint
 * would be a round trip to filter a list the client is holding.
 *
 * `taken` is not politeness: `offers` is unique on its four axes, so a second
 * row for the same school is a 422 the screen can only report as "did not
 * save".
 */
export function InstitutionPicker({
  onPick,
  taken,
  placeholder,
}: {
  onPick: (institution: Institution) => void;
  /** Ids already on the offer, so the list does not offer them again. */
  taken: Set<number>;
  placeholder?: string;
}) {
  const { t } = useLingui();
  const [query, setQuery] = useState('');

  const { data, isError } = useQuery({
    queryKey: ['institutions'],
    queryFn: ({ signal }) => api.getInstitutions(signal),
    staleTime: 60 * 60 * 1000,
  });

  // Faculties as well as universities: somebody prepares for ČVUT FEL, not for
  // ČVUT in general, and the row says which is which.
  const flat = useMemo(() => {
    const out: { row: Institution; under: string | null }[] = [];
    for (const university of data ?? []) {
      out.push({ row: university, under: null });
      for (const faculty of university.faculties) {
        out.push({ row: faculty, under: university.short_name ?? university.name });
      }
    }
    return out;
  }, [data]);

  const found = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle.length < 2) return [];
    return flat
      .filter(({ row }) => !taken.has(row.id))
      .filter(({ row, under }) =>
        [row.name, row.short_name, row.code, under]
          .filter(Boolean)
          .some((field) => (field as string).toLowerCase().includes(needle)),
      )
      .slice(0, 6);
  }, [flat, query, taken]);

  return (
    <>
      <div className={ui.field}>
        <SearchIcon size={18} className={ui.fieldIcon} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder ?? t`Вуз или факультет — ČVUT, VŠE, FEL`}
          maxLength={120}
          style={{ all: 'unset', flex: 1, minWidth: 0 }}
        />
      </div>
      {/* A search box that answers nothing looks like a school nobody has
          heard of. The list is one request, and when it fails every query comes
          back empty with nothing to explain it. */}
      {isError ? (
        <Hint>
          <Trans>Список вузов не загрузился. Попробуй ещё раз позже.</Trans>
        </Hint>
      ) : null}
      {/* No margin of its own: the card this sits in spaces everything in it,
          the way it does for the subject search. */}
      {found.length > 0 ? (
        <Rows>
          {found.map(({ row, under }) => (
            <Row
              key={row.id}
              title={row.short_name ?? row.name}
              hint={under ?? row.name}
              onClick={() => {
                onPick(row);
                setQuery('');
              }}
            />
          ))}
        </Rows>
      ) : null}
    </>
  );
}
