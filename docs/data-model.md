# Data model

Postgres 18. 29 tables. The schema is defined in
`apps/api/src/students_cz/db/models/` and is the source of truth — this document
explains the decisions behind it, not the columns.

## The shape of the problem

Students CZ connects students in the Czech Republic — mostly foreigners — with
people who help them: tutors, exam help, written work, nostrification. It also
lists physical things (gear to rent, textbooks to buy), digital materials, and
partner services that have nothing to do with studying but everything to do with
staying in the country.

Three different kinds of listing, three different sets of rules. The schema
keeps them apart rather than forcing them into one shape.

## Three axes, one intersection

Every catalog query is an intersection:

```
subject × institution context × kind of help
"calculus" × "ČVUT FEL" × "live exam help"
```

`offers` is that intersection. A helper adds one row per combination they can
serve. Subject and institution are both nullable — writing a thesis needs no
subject, tutoring needs no particular school — and each `service_type` declares
through `requires_subject` / `requires_institution` what its form must ask for.

The unique constraint on the four axis columns uses `NULLS NOT DISTINCT`
(Postgres 15+). Without it a helper could add "calculus, no institution" twice,
because two NULLs would count as different values.

> The legacy schema modelled this as two parallel branches — `LessonsUniversity`
> and `LessonsLanguage` — each with its own join table. A third kind of help
> meant a third pair of tables. Here it is one row in `service_types`.

## Trees without recursion

`subjects` and `institutions` are hierarchies stored as materialised paths:
`path` holds the chain of ancestor ids terminated by a dot (`'4.19.128.'`).
A whole branch is one indexed `path LIKE '4.19.%'`. No recursive CTE, no `ltree`
extension, no custom SQLAlchemy type.

Paths are built from ids rather than slugs, so renaming a subject never rewrites
its subtree.

## Four languages, two different problems

The interface speaks `ru`, `cs`, `en`, `uk`. That is two separate concerns, and
conflating them is the usual mistake.

**Reference data is translated.** Subjects, institutions, service types, item
categories and languages each have a `*_i18n` table keyed by `(entity_id, lang)`.
We write those names, so we can translate them.

**User content is not.** A profile written in Russian stays Russian. It carries
a `lang` column saying what it is, and that is all. Instead, language becomes a
*matching attribute*: `users.spoken_langs` and `offers.langs` are arrays with GIN
indexes, so "show me people who speak a language I speak" is one indexed overlap
test. A Ukrainian first-year cannot work with a Czech-only tutor, and the catalog
should know that before showing the card.

The `languages` table offers the same four and no more. Codes taken off the
list are marked `is_active = false` rather than deleted: the arrays above hold
plain text and reference nothing, so a deleted row leaves a profile claiming a
language with no name to show for it.

> The legacy bot used non-standard codes `cz` and `ua`. The import maps them to
> `cs` and `uk`.

## Finding what people meant

Students type `matan`, `prijimacky`, `mat. analyza` — slang, no diacritics,
wrong language, misspelled. Three mechanisms handle it, cheapest first:

1. `subjects.synonyms` — a text array of known alternative spellings, GIN indexed.
2. `pg_trgm` on every translated name, so similarity matching works across all
   four languages at once.
3. `unaccent`, wrapped in an `IMMUTABLE` function so it can be used in
   expression indexes. This is what makes `prijimacky` match `Přijímačky`.

Verified against a live database: `prijimacky` scores 1.00 against `Přijímačky`,
`matematicka analyza` scores 1.00 against `Matematická analýza`.

Above all this sits the query parser, which turns free text into ids. Because it
does, the database rarely has to do linguistic work at all — it looks up
canonical ids and filters. `search_queries` logs every query with the parse, the
result count and any correction the user made to our chips. Queries returning
zero results are a ranked list of what the catalog is missing; raw text paired
with the parse is training data for making the parser better. It is the cheapest
table in the schema and the most valuable.

## Services, things, materials

Three tables because three sets of rules:

| | `offers` | `items` | `materials` |
|---|---|---|---|
| what | someone's time | something physical | a file |
| price | per hour / work | per day / week, plus a deposit | Stars |
| location | online or a district | pickup point | none |
| money | between people | between people | through Telegram |

The split is not tidiness, it is a payment constraint. Telegram requires Stars
for digital goods sold inside a mini app; physical goods and real-world services
are exempt. Materials therefore carry `price_stars`; items never do. Both are
nullable and `MaterialAccess.PAID` is currently unreachable — payments are
deferred, and the schema says so honestly instead of pretending.

## Requests: the catalog in reverse

A directory only works once it is full. Until then the useful direction is the
other one: `help_requests` lets a student post "calculus, ČVUT, exam on
14 February" and helpers answer through `request_responses`, one answer each —
repeat pitching is spam, and the unique constraint says so.

Requests carry `expires_at` because they rot: an exam on 14 February is
worthless on the 15th. A request past it is filtered out of the helper feed and
refuses new answers even while its `status` still reads `open` — expiry is a
deadline, not a job that has to have run.

An answer carries `price_amount` **and** `price_unit`: "500" alone is ambiguous
between an hour and the whole job, and the two readings are different offers.
Accepting one writes a `contacts` row — the same row the catalog writes when
someone taps "write" on a profile — so response times and deal counts count
both routes to a conversation, and accepting deliberately does not close the
request: needing two people for two subjects is ordinary.

## Availability

`availability_slots` stores concrete windows as `tstzrange` with a GiST
exclusion constraint, so overlapping slots for one helper are impossible at the
database level. This needs `btree_gist`. `weekly_availability` answers a
different question — "generally reachable on Tuesday evenings" — and is shown on
the profile rather than used for filtering.

## Partner placements are not catalog content

Insurance, visa language courses, bank statements, sworn translations. These
must never be searchable alongside real listings, so they live in their own
tables and render with an outline instead of a fill.

A `placement` is a rule: *show this offer in this slot when this condition
holds*. Conditions are JSONB — `{"service_type": "nostrification"}`,
`{"month": [8, 9]}`, `{"ui_lang": ["uk"]}` — so a new targeting idea is a row,
not a migration. `placement_events` records impressions and clicks; worth
partitioning by month once it hurts.

## Counters are caches, not truth

`deals_count`, `rating`, `reviews_count`, `response_minutes_avg` on
`helper_profiles` are denormalised so list screens do not aggregate on every
read. They are recomputed by background jobs and never trusted as the source of
truth. `contacts` is what they are computed from: we do not host conversations —
those happen in Telegram — but we record that a contact was made and when it was
answered, so response times are measured rather than self-reported.

## Conventions

- Every NOT NULL column with a default has a `server_default`. Python-side
  defaults only fire through the ORM, and the legacy import runs raw SQL.
- Native Postgres enums, created with `values_callable` so the stored values are
  the enum *values* (`rent`), not the member names (`RENT`).
- Explicit constraint naming convention in `db/base.py`, otherwise Alembic
  generates unnamed indexes that later migrations cannot drop.
- Flexible per-type attributes go in `attrs` JSONB with a GIN index. Anything
  filtered on in a hot path gets a real column instead.

## Required extensions

`pg_trgm`, `unaccent`, `btree_gist`, plus the `immutable_unaccent()` wrapper.
Created both by `infra/postgres/init/01-extensions.sql` on first boot and by the
initial migration, so either path — a fresh container or `alembic upgrade head`
against an empty managed database — produces a working schema.

Note that `DROP SCHEMA public CASCADE` removes the extensions too. Re-run the
init file after resetting a development database.

## Planned: semantic search

The image is `pgvector/pgvector:pg18`, so the `vector` extension is available.
It is **not enabled** — semantic search is planned, not built, and turning on an
extension nothing queries would misrepresent the schema.

When it happens, the shape is already clear from how search works today. The
parser turns free text into ids; trigram matching covers typos and missing
diacritics. What neither handles is meaning: "нужен кто-то объяснить пределы и
производные" should reach calculus without containing the word. Three places
would carry embeddings:

- `subjects` — one vector per subject, so a query embeds once and finds the node
  by proximity. Smallest table, biggest payoff, and it slots in behind the
  existing lookup rather than replacing it.
- `helper_profiles.about` — matching against how someone describes themselves,
  not just the boxes they ticked.
- `help_requests.raw_text` — notifying helpers about requests that fit them.

Two things to decide then, not now: which embedding model (it fixes the vector
dimension, and changing it means recomputing everything), and whether hybrid
ranking blends the trigram and vector scores or falls back from one to the
other. `search_queries` is already logging the raw text and result counts that
would tell us which.
