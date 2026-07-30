import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { api } from '@/lib/api';
import type { SearchParams } from '@/lib/types';

/**
 * The filters a query string describes, as the search endpoint takes them.
 *
 * Shared by the two screens that read the same query string: the search screen,
 * which shows how many people it finds and the first two of them, and the
 * results screen, which lists them. Those two numbers have to be the same
 * number — that is the whole point of showing one at all — and a second copy of
 * this mapping is the way they would stop being.
 *
 * The clarifying answer travels as a service *code* rather than an id, because
 * the screen that asks the question has no reason to hold the reference list.
 * Resolving it needs that list, so `filters` is null until it is here: filtering
 * by nothing instead would count everyone who teaches the subject and then hand
 * over to a screen that does apply the filter.
 */
export function useSearchFilters(query: string | URLSearchParams): {
  filters: SearchParams | null;
  isError: boolean;
} {
  const params = useMemo(
    () => (typeof query === 'string' ? new URLSearchParams(query) : query),
    [query],
  );
  const code = params.get('service');

  const { data, isError } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
    enabled: Boolean(code),
  });

  // Depends on the string rather than on the URLSearchParams object, which is a
  // new identity on every render of a screen that builds one.
  const key = params.toString();

  const filters = useMemo(() => {
    const read = new URLSearchParams(key);
    const byCode = code ? data?.find((type) => type.code === code)?.id : undefined;
    if (code && byCode === undefined) return null;

    return {
      subject_id: numeric(read.get('subject_id')),
      institution_id: numeric(read.get('institution_id')),
      service_type_id: numeric(read.get('service_type_id')) ?? byCode,
      max_price: numeric(read.get('max_price')),
    };
  }, [key, code, data]);

  return { filters, isError };
}

function numeric(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
