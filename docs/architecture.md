# Architecture

Three layers and one rule about each. This document is the contract new code
is held to; where the code does not meet it yet, that is written down at the
bottom rather than left to be discovered.

```
api/       HTTP. Parse the request, authorise, delegate, serialise.
services/  The rules. Everything a second caller would need to reuse.
db/        Models, session, migrations. No behaviour.
```

The bot is a fourth door onto the same rules, not a fifth layer. Anything a
bot handler and an endpoint both have to get right belongs in `services/`, and
`services/people.remember` is the pattern: both doors call it, so a person who
writes to the bot and a person who opens the app are recorded the same way.

**What the chat offers is part of what we say.** Telegram remembers a bot's
command list and a chat's reply keyboard until somebody replaces them, and this
token belonged to a command-driven bot before it belonged to this one — so a
list nobody sets is the old one, still offering `/language` to a bot that has
no such command. `bot.configure` sets the two that exist, and any message the
bot answers clears whatever keyboard is left over from before. Both are the
same rule as the copy above: what a person is offered has to exist.

**What we say is part of what we do.** A sentence telling somebody how to undo
something, or who can see their request, or how fast an answer comes, is a
claim about the code — and it is the kind that rots quietly, because nobody
tests prose and the person who finds out is the one who tried it. The rule is
that copy names only what exists: no command nothing implements, no section the
catalog cannot show, no filter that does not filter. When a promise and the
code disagree, cutting the promise is a fix, not a retreat.

The rule is younger than the copy, and the copy has not all been brought to it
yet — what is still owed is listed at the bottom of this document.

**Opting out keeps everything.** `/stop` writes one timestamp and deletes
nothing: not the person, not their profile, not their requests or the answers
to them. The row is what makes them the same person if they come back, and an
opt-out that destroyed it would be a worse answer than the blocking it exists
to prevent.

Nothing here is DDD. There are no aggregates, no repository per model, no
command bus. This is a catalog with two dozen endpoints, one bot and one
database; layering it further would cost more than it returns.

## One name

The product is **Students CZ**, and so is everything that can be renamed
without moving data: the Python package `students_cz`, the images
`students-cz-api` and `students-cz-web`, the compose project, the containers,
`deploy/students-cz`. `konnekt` was the working title and it is gone from
everywhere a person reads.

Three places keep it, each for a reason and each said out loud where it sits:

| Where | Why |
| --- | --- |
| The docker volumes | The data is in them. A compose volume is `<project>_<name>`, so a rename is a move, not an edit — see `docs/deploy.md`. |
| `LEGACY_STORAGE_KEY` / `LEGACY_OVERRIDE_KEY` in the web app | Somebody's saved theme and language. Read once and moved across, so the rename does not reset everyone to their phone's defaults. |
| The Postgres role and database | Invisible, and renaming them costs a dump and a restore. |

The repository is still `teachers-catalog` and the domain is still
`tutors.azamat.io`. Neither is in the code, and neither is free to change —
one breaks every clone and remote, the other breaks the Mini App's registered
URL and every link anybody has shared.

## `api/v1`, one module per domain

Each module owns a slice of the URL space and nothing else. The prefix is
declared once, in `api/v1/__init__.py`, so a module cannot disagree with its
neighbours about where it lives.

| Module | What it serves |
| --- | --- |
| `public.py` | `/open` — the only route without init data |
| `me.py` | the account behind the init data |
| `taxonomy.py` | service types, subjects, institutions, languages |
| `search.py` | free-text parse — the rule is `services/search.py` — and the search it feeds |
| `browse.py` | the home screen, a person's page, starting a contact |
| `cabinet.py` | a helper's own profile: reading it and saving it |
| `requests.py` | the catalog in reverse — post, answer, accept, close |
| `placements.py` | partner placements |
| `health.py` | `/healthz`, on its own router with no prefix |

`health.py` is deliberately outside the versioned router: `/healthz` is what
the deploy and the shared edge Caddy watch, and it must not move when the API
version does.

There is no shared-helpers module here. What two domains both need is a rule,
and a rule belongs in `services/` — that is what stops this package growing a
second god module to replace the one it was split out of.

## What belongs where

**An endpoint** reads the request, checks who is asking, calls one service,
and renders a schema. If it contains a rule — a permission check beyond
"logged in", a multi-step write, ranking, a state machine — that rule belongs
in a service, where a test can reach it without an HTTP client and a live
database.

**A write is a rule**, even a one-line one. An endpoint does not add a row: a
row added in a handler is a fact about the product that only an HTTP test can
reach, and the bot cannot reach it at all. The two that read like exceptions
are not: `catalog.open_home` and `catalog.view_helper` are the plain readers
plus the event each records, kept apart from `home_sections` and
`helper_detail` so that reading the sections is not itself a claim that
somebody opened the app.

**A service** takes a session and plain values, and returns DTOs. It does not
raise `HTTPException`: an HTTP status is a fact about a protocol, and a
service that knows about protocols cannot be called by the bot.

What it raises instead lives in `services/errors.py` — `NotFound`,
`Forbidden`, `Conflict`, `Invalid`, `BadRequest` — and one handler in
`main.py` turns each into its status code, walking the class hierarchy so a
subclass keeps its family's answer. The bot can catch them and answer in
words.

**A name is a rule too.** Every reference table keeps its names in a side
table, one row per language, and `services/naming.py` is the only place that
reads them: which translation to show, what to fall back to when the asked
language has none, and how to fetch a page's worth of them in one query. Five
modules need that, which is what makes it a rule rather than a helper belonging
to whichever module wrote it first.

**What a handler needs arrives as a dependency.** A route does not reach into
`app.state`. What the process was started with — the bot, the settings — is
composed into something usable in `api/deps.py` and asked for by type:
`SessionDep`, `UserDep`, `LangDep`, `NotifierDep`. The reason is not tidiness.
`app.state` is populated by the lifespan, which does not run under the test
client, so every route reaching for it had to decide what "it is not there"
means — and each of them decided quietly, with a `getattr` default. There is
one answer to that question per thing, it belongs where the thing is built, and
a dependency is also the only shape a test can substitute.

`api/v1/health.py` is the exception and stays one: it reports on `app.state`
itself, so reaching for it is the job rather than a shortcut. So is the webhook
route in `main.py`, which is defined inside `create_app` and hands the update
to the dispatcher the lifespan put there — it is the seam between the two
runtimes rather than a handler.

**Two notifications and one ping.** `services/notify.py` writes to people
about something they set in motion — an answer to their request, an acceptance
of their answer. `Notifier.tell_owner` is the other kind and is kept apart from
it: one message to one address, `OWNER_TG_ID`, about a profile or a request
appearing. It is not product copy — nobody reading it chose a language, and it
is addressed to whoever runs this — so it lives in `bot/texts.py` as a plain
string rather than a table per language, and it is off unless that setting
names somebody. A ping that cannot be sent, like a notification that cannot,
costs the action nothing: both are queued after the response and neither may
raise.

**State the process keeps is a service, not an attribute.** `Notifier` is one:
a bot and an address, decided once. `telegram.BotHandle` is the other, and it
was the harder case — it holds the bot's own handle and the cooldown that
stops a failing Telegram being asked again on every landing visit, which is
per-process state rather than a value. `api/deps.py` builds it on the first
request that needs it and keeps it on `app.state`; a route asks for
`HandleDep` and cannot tell whether there is a bot at all, because a handle
with no bot answers `None`.

Built in `deps.py` and not in the lifespan, deliberately: the lifespan does
not run under the test client, so a handle built there would leave the tested
path and the production path as different code.

The webhook watchdog's state — `webhook_observed`, `webhook_checked_at` and
the lock beside them — is the exception, and it belongs to the same carve-out
as `health.py` above: it exists so that `/healthz` can report on the process
without asking Telegram on every probe, and it is read by the one route whose
job is reporting on the process.

**A schema** is a leaf. `students_cz/schemas.py` — the package root, not inside
`api/` — describes what goes over the wire. A service may return one without
that pointing the domain layer at the HTTP layer, which is the whole reason it
sits there.
Screens are assembled server-side — the client renders what it is given rather
than joining data itself — so a schema often mirrors a screen, and that is
intended.

**What the client has generated from that contract is committed**, into
`apps/web/src/lib/generated`, and CI regenerates it from the API's own OpenAPI
document to check that the committed copy still matches. Generating at build
time was the alternative and it is worse: it needs the API process up, so the
web build fails when a backend is not running. Committing it means the two can
disagree, which is what the check is for — a schema changed without running
`make contract` types the client against an endpoint the API does not serve, and
nothing else in this repository notices. That target dumps the document to a
file rather than fetching it: given a URL, the generator writes that URL into
the client as a literal type, so a client generated against somebody's laptop
carries their address.

The check covers what has moved across, and that is not yet the whole client.
`apps/web/src/lib/types.ts` still declares most of the wire types by hand and
says so; each moves to the generated module as the screen using it is touched,
and until one has, nothing compares it to the API. So a green contract check
means the generated types are current, not that every type the app uses is.

## One engine, one pool

`db/session.py` holds the engine and the sessionmaker as module singletons,
created once and lazily. Not on `app.state`, deliberately: the API is not the
only door. The bot's middleware, the notifier's background task and the seed
scripts all need a session and none of them has a FastAPI app to reach
through, and a second engine would double the connection count against
Postgres without anybody deciding to.

A session is not a connection. Each request gets its own `AsyncSession`; the
connection underneath it is checked out on the first query and handed back
when the session closes, so a screen that runs four queries uses one
connection, not four. FastAPI caches dependencies within a request, so
`SessionDep`, `UserDep` and `LangDep` all resolve to the same session.

`db_pool_size` and `db_max_overflow` are therefore the whole connection budget
for the process — and the Dockerfile pins `--workers 1`, so process and
deployment are the same thing here. Raise them together with the worker count,
never one without looking at the other.

## One transaction per request

**Services never commit. The request commits.**

`db/session.py::session_scope` is the unit of work: it commits when the
handler returns and rolls back when the handler raises. So a request either
happened or it did not, and no endpoint has to remember which of its writes
came before the failure.

The rule is worth more than the tidiness. Answering a request wrote the
response row, committed, and only then rendered the notification to its
author — so a rendering error left an answer in the database that the author
was never told about, and the helper saw a 500 and assumed nothing had
happened. That state is now unreachable by construction rather than by
everybody remembering to put the commit last.

The scope is asked for with `scope="function"`. FastAPI tears a
request-scoped `yield` dependency down *after* the response has been sent and
after its background tasks have run, which would answer 201 to a request whose
commit then failed, and would notify somebody about a row that never landed.
The function stack closes earlier — after the handler has returned and its
response model has been validated, and before the response is sent — so a
serialisation error rolls back too.

Everything that commits outside it:

- `api/deps.py::current_user` commits the person's own row before the handler
  runs, so that first sight of someone — and the `source` that says where they
  came from — survives whatever the handler goes on to do.
- `services/notify.py` opens its own session: it runs in a background task,
  after the response, and therefore after this transaction has closed. Nothing
  is handed an ORM row across that line — a background task gets a
  `notify.Recipient`, a snapshot taken while the session was still open.
  Passing the row itself works only for as long as nothing expires it, and the
  thing that would notice is a `MissingGreenlet` inside a task whose exception
  nobody is waiting for.
- The bot has no request to hang a transaction on, so `bot/middleware.py` and
  the `/stop` handler open and commit their own sessions. The middleware
  commits the person's record before the handler runs, for the same reason
  `current_user` does: neither a slow handler nor a throwing one should decide
  whether we remember that this person exists. So a bot update is two
  transactions, deliberately, and not one.
- `db/seed.py` and `db/demo.py` are scripts, not requests. They commit because
  nothing else will.

Tests share one session per test, rolled back at the end, and the override in
`tests/conftest.py` commits and rolls back exactly where `session_scope`
does. A test fixture that is more forgiving than production is a fixture that
hides the bugs this rule exists to prevent.

## The web shell scrolls in exactly one place

The Mini App is a screen, not a document. `#root` is the app: it is exactly one
screenful tall and it is the only element that scrolls. `body` carries
`overflow: hidden`, which the viewport takes its own overflow from, so the
document has nothing to scroll and cannot invent travel of its own.

**One screenful is Telegram's number, not the webview's.** `--app-height`,
published by `bindAppHeight` in `main.tsx` from the viewport's stable height,
with `100dvh` only as the fallback. On iOS and Android the SDK does not trust
`window.innerHeight` either — it asks the client and waits for
`viewport_changed` — and `100dvh` is that same untrusted number. Where they
disagree, an app sized to the webview puts its last rows below the visible edge
with nothing able to scroll to them. Zero is not an answer and is skipped: the
signal reads `0` until the client replies, and a CSS variable set to `0px` is
defined, so the fallback would not fire.

Three rules follow, and they are what to check before changing layout:

- **A scroll must end on content.** Not "a screen that fits must not scroll" —
  for any layout there is a band of viewport heights where the content is a
  few pixels too tall, so that rule only moves the failing size around. What
  makes it a bug is emptiness at the end of the travel. The screen's own
  `padding-bottom` is the only breathing room at the foot of a page; a spacer
  under the last element is a stretch of nothing that someone has to scroll
  through to reach.
- **Anything pinned to an edge is `position: fixed`** — the tab bar, the sheet,
  the scrim. They are descendants of `#root` but are laid out against the
  viewport: a scroll container is not a containing block for fixed elements.
  That is what lets the tab bar stay put while the screen behind it moves.
- **Telegram's vertical swipe is off** (`swipeBehavior`, Mini Apps 7.7). The
  gesture drags the whole app towards dismissal, and on a screen with nothing
  to scroll a drag and a scroll are the same movement, so the app appears to
  scroll where there is nothing to see. Because that same gesture is how a
  part-height Mini App is grown, the app asks for the whole screen with
  `viewport.expand()` at startup rather than leaving someone in a half sheet
  with no way out of it. It is dismissed with Telegram's close button.

`pnpm check:scroll` in `apps/web` is the first rule, executable. At three phone
sizes it measures the gap between the lowest thing that paints and the bottom
of the screen's content box — the screen's own `padding-bottom` is subtracted,
which is also what keeps the number right on a phone with a home indicator. A
container does not count as painting on behalf of its children, so a spacer
nested inside a card list is as visible to it as one at the foot of the page.

It needs the dev server, the API and signed init data, and it stops rather than
measuring a home screen that came back without its categories, because that
means the API is rejecting the init data and every screen behind it is an error
state. A page it cannot recognise as a screen at all is a hard stop too, and a
screen it could not reach is named in the summary: a check that reports an
unmeasured screen as a clean one has stopped being a check.

What it takes on trust is the screen's own `padding-bottom` — that is the
number it subtracts, so a screen that reserves room for a tab bar it does not
render will pass with a blank strip at its foot. Nothing runs it automatically;
it wants a browser and a database, which CI here does not give it.

## The embedding model ships inside the image

`subject_embeddings` is filled by a model, and the model is a 197 MB file. It is
downloaded at **build** time, from a pinned commit revision and verified against
a checksum, and copied into the runtime image — not pulled when the container
starts.

The image is the unit of deploy and of rollback: `prod-<sha7>` is what CI pushes
and what `rollback.yml` puts back. A model fetched at startup would make one tag
behave differently on different days, and a rollback would restore the code
without restoring the model. It would also need a writable cache in a container
whose Dockerfile says the application writes nothing to disk, and it would make
every restart depend on Hugging Face being up. This repository already has one
piece of state that lives outside the image — the seed, which the deploy does
not run — and the cost of that is documented in `docs/data-model.md`.

Two dependencies carry it: `onnxruntime` and `tokenizers`. No torch and no
transformers, which is the difference between 200 MB and two gigabytes.

The weights are **EmbeddingGemma-300m**, quantised to q4, from the ungated ONNX
mirror. They are licensed under the Gemma Terms of Use rather than Apache-2.0:
commercial use is allowed, with use restrictions that have to be passed on
downstream. That is a deliberate trade — it was the only model of the seven
measured that answered the whole fixture, and its scores are the only ones that
separate confident answers from guesses — and it is written here so the choice
is visible if the licence ever matters.

## Where the code does not follow this yet

Written down because an agent greps this tree and builds against what it
finds, and a rule with silent exceptions is worse than no rule.

- **Nothing tells a helper that a request exists.** `requests.feed_for` filters
  on status, authorship, expiry and whether you already answered, and uses the
  subject only for *ranking*, so every helper profile sees every open request —
  which the screens now say, rather than promising the subject narrows it. What
  is still missing is the push: the notifications that exist are about a
  response and an acceptance, so a request waits to be found rather than
  arriving. The product decision it waits on is whether to narrow the feed
  first, since notifying every helper about every request is how a feed becomes
  something people mute — and that decision cannot be made from data yet: the
  catalog holds no profiles and no requests. `Notifier.tell_owner`, described
  under "What belongs where", exists so that the first ones are noticed without
  anybody reading the database.

Each of these is a separate change with its own tests. None of them is a
reason to write new code the old way.
