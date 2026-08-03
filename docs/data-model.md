# Data model

Postgres 18. 32 tables. The schema is defined in
`apps/api/src/students_cz/db/models/` and is the source of truth — this document
explains the decisions behind it, not the columns.

## The shape of the problem

Students CZ connects students in the Czech Republic — mostly foreigners — with
people who help them: tutors, exam help, written work, nostrification, and the
paperwork of staying in the country — insurance, a bank statement, a sworn
translation. It also lists physical things (gear to rent, textbooks to buy),
digital materials, and partner offers for some of that same paperwork.

The last two overlap on purpose: a person offering to sit in the bank with you
and a partner selling insurance are different listings with different rules,
and both are useful. `offers` holds the first, `placements` the second, and
nothing merges them.

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

## Kinds of help come in three groups

`service_types.group_code` is a native Postgres enum (`service_group`) with
exactly three members:

| group | what is in it |
| --- | --- |
| `study` | tutoring, languages, exam preparation, written work |
| `entrance` | entrance exams, help during the exam, nostrification |
| `life` | insurance, a bank statement, translations, residence, housing |

The group orders both screens that show these tiles — the catalog's front door
and the screen where someone offers a service — and they render the same grid
from the same list. A kind of help that is in no group would appear on neither,
so the column is `NOT NULL` with `study` as its default.

`life` is help with no subject and no institution: both axis columns stay null
and the tile is the whole query. The axes were already nullable for writing a
thesis, as above — this group is the case that leans on it hardest, and the one
that would have needed a third pair of tables in the legacy schema.

**Group names are translated on the client, not through an `*_i18n` table.**
This is a deliberate exception to the rule below, not an oversight. The i18n
tables exist for rows we author and keep adding to — subjects, institutions,
service types. A closed enum of three has the same shape as `work_format` and
`price_unit`, which `apps/web/src/components/Phrase.tsx` already translates
client-side. Adding a `service_group_i18n` table would mean a migration every
time a word changes.

**A migration that adds reference data carries the rows itself.** The
deployment runs `alembic upgrade head` and never runs `seed.py`
(`.github/workflows/deploy.yml`), so a service type that exists only in the
seed reaches every developer's database and no production one. Reference rows
therefore live in two places on purpose, and
`apps/api/tests/test_service_groups.py` fails when the two disagree about which
types exist, and — for the rows a migration actually creates — about what they
are called. Names matter as much as codes: renaming a service type in the seed
alone leaves production showing the old one for ever, so a rename needs a
migration too.

The seven types that predate the grouping are the gap, and the reason the rule
exists at all. No migration creates them — the initial schema builds the table
and inserts nothing — so they are in production only because somebody ran
`seed.py` against it by hand. Nothing compares their names, and renaming one in
the seed still needs a migration; nothing but this paragraph will tell you so.

## A group is not a form

`service_types.form_shape` is a second closed enum — `lesson`, `work`,
`errand` — and it answers a different question from the group. The group is for
the student browsing the catalog: *what do I need*. The shape is for the person
offering: *what do we ask you*. They nearly coincide and must not be merged,
because the two that differ are the ones that matter:

| shape | which kinds | what the form asks |
| --- | --- | --- |
| `lesson` | tutoring, languages, exam preparation, entrance exams | a subject, a school where one is required, an hourly price, online or in person, where |
| `work` | written work | a price per work, a turnaround, and nothing about meeting |
| `errand` | nostrification, help during the exam, and all five of `life` | a price, remote or alongside you, where |

Help *during* an exam is the clearest case: it sits on the `entrance` shelf
with the exam preparation a student would compare it to, and its form has
nothing to do with teaching — it is standby for one event on one day.

What the price is *per* is not the shape's business: `default_price_unit` says
that per service type, so five errands are priced per case while nostrification
and help during an exam are priced by the hour. The shape decides which
questions exist, not what the answers are measured in.

A `work` is always remote, so its form does not ask how you meet. For the other two the
question is the same three answers under different words: `work_format` is
`online` / `offline` / `both`, which reads as online-or-in-person for a lesson
and remotely-or-alongside-you for an errand. One column, worded by what the
person actually offers — a second column would be the same fact stored twice.

## What an errand covers

A lesson is described by its axes: this subject, at this school, for this much
an hour. An errand has no axes at all — the tile is the whole query — so a
person offering one has nothing to say beyond the tile unless we ask.

Two things carry that, and the split is the point:

- **`service_options`** is a checklist per service type, translated through
  `service_option_i18n` like every other name we author: "I arrange VZP or
  PVZP", "I come to the bank with you". An offer's choices live in
  `offers.option_ids`, an integer array with a GIN index — the same shape as
  `offers.langs`, and searchable for the same reason. "Who goes with you to the
  bank" is a question this schema can answer; a paragraph of prose is not.
- **`offers.note`** is what did not fit the checklist, in the person's own
  words. It is read, not matched.

An option taken out of circulation is marked `is_active = false` rather than
deleted, for the reason `languages` gives: the array holds plain integers and
references nothing, so a deleted row would leave an offer pointing at an option
with no name to show.

The checklist belongs to the service type and not to the shape, which is why the
column sits where it does: every errand has one, and so does written work, whose
lines are the kinds of work taken on rather than the errands run. Nothing stops
a lesson growing one — "first lesson free" is the obvious candidate.

**`offers.turnaround_days`** is how long the work takes, and `NULL` means the
two of them will agree rather than that nobody knows: a written work is the one
kind of help where "when" is the question asked straight after "how much", and
a person who will not commit to a number is saying something, not omitting it.

Only a `work` is asked, and only a `work` may answer: a turnaround sent for any
other kind of help is dropped on the way in, the same filter the checklist gets
and for the same reason — a profile reading «Срок: неделя» under a lesson would
be answering a question that form never asked.

It is a column and not a key in `offers.attrs`, which is where a turnaround
would naturally go — `attrs` is the bag for per-service-type extras that do not
deserve columns. Two reasons it does not go there. No schema exposes `attrs`, so
a client would be reading an untyped bag the generated types cannot check. And
the question worth asking of a turnaround is a range — who can do it inside a
week — which a small integer answers and a JSONB key does not. Days, not a free
text, for the same reason: "asap" sorts against nothing. Nothing indexes the
column yet, because nothing queries it until search does.

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

Three rules keep the trigram half of that from answering confidently about
something else:

- **A two-letter short name matches as a whole word or not at all.** `FI`, `UK`
  and `JU` are two letters, and trigram similarity puts any word containing them
  above the threshold, so "по физике" found the faculty FI and "uklidit" would
  find Charles University. Those are compared against the query's tokens, the
  same whole-word test the synonym branch uses. Three letters stay on the
  trigram path deliberately: Czech declines the abbreviation itself — "na FELu",
  "na MFFce" — and the whole-word rule would cost every one of the 69
  institutions with a three-character short name, 60 of them faculties, the
  inflected forms they have. The two-letter names pay that price instead: an
  inflected "na UKu" resolves to nothing. That is the trade — a missing
  institution filter shows a wider list than was asked for, a wrong one narrows
  the catalog to a faculty nobody named.
- **When the words naming the kind of help were the whole query, only a certain
  subject survives.** There is no subject left in the text to find, so a trigram
  score is the scorer answering a question nobody asked: "bank statement" came
  back as `Probability and Statistics` at 0.61, which would then filter the
  search by a subject nobody named. A synonym hit is kept, because a curated
  synonym is not a guess — "курсовая" and "нострификация" are written down
  against real subjects.
- **A synonym names one row, so a word that names a whole shelf does not belong
  in one.** `prijimacky` and `приймачки` sat on «Поступление в технические вузы»,
  and a synonym scores 1.00 — so every «přijímačky …» query came back filtered by
  maths and physics, including one that said medicine. The word names a kind of
  help, and reaches `entrance_prep` through the keyword table, which is where a
  category word belongs. What stays in `synonyms` is what names *that* row and
  no other: «матан» is calculus, «приемка математика» is the maths entrance exam.
- **A subject and a kind of help that carries none cannot both survive.** The
  `life` group's offers have no subject at all, while the search applies subject
  and kind of help together — so the pair matches nobody, and one of the two has
  to go. Which one depends on whether the kind of help could have been mentioned
  in passing:

  Insurance, a bank statement, residence and housing are ordinary words that
  turn up as asides. Beside a *named* subject — a curated synonym, or a name the
  query reproduced exactly — the subject is the question and the aside is not:
  "нужен матан, живу в общежитии" is about calculus, and reading it as housing
  turned a list of tutors into an empty screen. Beside a *guessed* subject the
  guess goes instead, because a score of 0.55 cannot narrow a kind of help that
  has no subjects to narrow by.

  A document translation is the exception, and always wins: nobody writes
  "присяжный перевод диплома" in passing, so when that phrase appears it is the
  request, and any subject beside it is dropped whether it was named or not.

  The group, and not `requires_subject`, is what identifies this set — exam help
  and nostrification have that false as well and belong outside it.

A kind of help that cannot be named in words cannot be found, in any of the four
languages. The five that are not about studying — insurance, a bank statement,
a document translation, residence paperwork, housing — were offerable and
unfindable, which is a listing nobody can reach. So is a kind of help named by
the brands people actually say: an insurance policy is asked for as "VZP" or
"PVZP" far more often than as "pojištění", and those are `Word`s rather than
stems because `vzp` prefixes `vzpomínky`.

Languages are the case where two kinds of help overlap: asking for a Czech tutor
is `language_tutoring` and not plain `tutoring`. It has no keywords in the table,
because the words that would name it — "чешск", "anglict" — also say *whose*
bank, *whose* visa and *whose* dormitory, and anything placed high enough to beat
tutoring takes all of those with it.

It is a refinement of a lesson instead, and the test is **whether the language
is the whole request**. Take out the words that asked and the language itself,
and what is left decides: "репетитор по чешскому" leaves nothing, while
"репетитор по химии на чешском" leaves chemistry, "репетитор по чешской
литературе" leaves literature and "репетитор по матану на чешском" leaves maths
— a medium of instruction and a nationality, not a request for a language. Read
the other way they would carry a subject no language offer has, and the search
ANDs the two: an empty screen for a query that worked. It is the same test the
rule above makes of a keyword that was the whole query.

"What is left" ignores the words that ask rather than name — verbs of searching,
prepositions, the word "language" itself, and the word "course", which is what
makes "kurzy cestiny" and "курс чешского языка" lessons as well. It also ignores
the words that say the *same* request more precisely: a level ("B2"), a shade
("разговорный", "konverzace") and a second language, so "doucovani cestiny B2"
and "репетитор по чешскому и английскому" are language lessons too.

The words and not the resolved subject, because the commonest phrasing resolves
none: "репетитор по чешскому" says which language and not which level, and a
bare «чешский» names five subjects and belongs to none of them.

Above all this sits the query parser, which turns free text into ids. Because it
does, the database rarely has to do linguistic work at all — it looks up
canonical ids and filters. `search_queries` logs every query with the parse, the
result count and any correction the user made to our chips. Queries returning
zero results are a ranked list of what the catalog is missing; raw text paired
with the parse is training data for making the parser better. It is the cheapest
table in the schema and the most valuable.

That count — returned to the caller as `matches` and stored as
`results_count` — is computed with every parsed filter the search can apply:
subject, institution, kind of help and budget. Dropping one of them records a
result for a query nobody ran, which is the one thing the zero-result list must
not contain, and hands the same wrong number to anyone who shows it.

The deadline is the parsed value with nowhere to go: it becomes a chip and is
logged in the parse, but the search has no date filter, so a query that says
nothing except a date counts the whole catalog. The screen does not show that
number — it shows a count only when something is being filtered — but the logged
`results_count` is still the size of the catalog rather than an answer, so
date-only rows do not belong in the zero-result list either way.

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

**What the text says, and what the caller says.** A request can be one
sentence: anything the caller leaves out is read out of the text by the same
parser the search screen uses, so «матан на ČVUT, экзамен 14 февраля» arrives
with a subject, an institution and a deadline without a form. The rule that
makes that safe is the one `HelperUpsert` already follows — the caller's own
words win over the inference, and *mentioning* a field is what makes it the
caller's. A `subject_id` of `null` that was sent means "any subject", and is
kept; a `subject_id` that was never sent means "read it out of the text". The
screen that posts a request shows the parse back as chips, and removing one is
exactly the first case: the text still says ČVUT while the request says nothing
about a school.

**The same request twice is one request.** A live request by the same person,
for the same subject, the same school, the same kind of help and the same
deadline, is a double tap or a reload — not a second thing to answer — so it is
refused rather than stored. Most of those four are nearly always `NULL`, which
is why all four are in the key and why, when the request names no subject, no
school and no kind of help, the words are compared instead. A date does not
count towards that: exam week is the same week for everybody, so two errands
sharing only a deadline share nothing.

The reason is the shape of the catalog: half of it is help
with no subject at all, so a rule keyed on the subject alone reads a visa and a
flat as the same request.

Live and not merely `open`: expiry is a deadline rather than a job that has to
have run, so a request the feed stopped showing thirty days ago must not refuse
the next one.

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
