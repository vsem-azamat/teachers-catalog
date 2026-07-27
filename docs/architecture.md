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

Nothing here is DDD. There are no aggregates, no repository per model, no
command bus. This is a catalog with two dozen endpoints, one bot and one
database; layering it further would cost more than it returns.

## `api/v1`, one module per domain

Each module owns a slice of the URL space and nothing else. The prefix is
declared once, in `api/v1/__init__.py`, so a module cannot disagree with its
neighbours about where it lives.

| Module | What it serves |
| --- | --- |
| `public.py` | `/open` — the only route without init data |
| `me.py` | the account behind the init data |
| `taxonomy.py` | service types, subjects, institutions, languages |
| `search.py` | free-text parse, and the search it feeds |
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

**A service** takes a session and plain values, and returns DTOs. It does not
raise `HTTPException`: an HTTP status is a fact about a protocol, and a
service that knows about protocols cannot be called by the bot.

What it raises instead lives in `services/errors.py` — `NotFound`,
`Forbidden`, `Conflict`, `Invalid`, `BadRequest` — and one handler in
`main.py` turns each into its status code, walking the class hierarchy so a
subclass keeps its family's answer. The bot can catch them and answer in
words.

**A schema** is a leaf. `konnekt/schemas.py` — the package root, not inside
`api/` — describes what goes over the wire. A service may return one without
that pointing the domain layer at the HTTP layer, which is the whole reason it
sits there.
Screens are assembled server-side — the client renders what it is given rather
than joining data itself — so a schema often mirrors a screen, and that is
intended.

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
  after the response, and therefore after this transaction has closed.
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

## Where the code does not follow this yet

Written down because an agent greps this tree and builds against what it
finds, and a rule with silent exceptions is worse than no rule.

- **Some endpoints still write in the route body**: `browse.start_contact`,
  `me.update_me`, and the event logging behind `browse.home`,
  `browse.helper_detail` and `search.parse`. Named rather than counted — a
  number here is one nobody remembers to correct, and the last three attempts
  at one were all wrong.
- **`services/catalog._localised` is imported across the package boundary** by
  name, from a private symbol, at sixteen call sites, and three more
  "fetch localised names by id" helpers exist alongside it.

Each of these is a separate change with its own tests. None of them is a
reason to write new code the old way.
