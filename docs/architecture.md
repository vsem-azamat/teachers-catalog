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
| `_shared.py` | what a second domain module already needs |

`health.py` is deliberately outside the versioned router: `/healthz` is what
the deploy and the shared edge Caddy watch, and it must not move when the API
version does.

`_shared.py` stays small on purpose. A module that collects everything shared
becomes the god module this package was split out of, so the bar for adding to
it is that a second domain already needs the thing — not that it might.

## What belongs where

**An endpoint** reads the request, checks who is asking, calls one service,
and renders a schema. If it contains a rule — a permission check beyond
"logged in", a multi-step write, ranking, a state machine — that rule belongs
in a service, where a test can reach it without an HTTP client and a live
database.

**A service** takes a session and plain values, and returns DTOs. It does not
raise `HTTPException`: an HTTP status is a fact about a protocol, and a
service that knows about protocols cannot be called by the bot.

**A schema** is a leaf. `api/schemas.py` describes what goes over the wire.
Screens are assembled server-side — the client renders what it is given rather
than joining data itself — so a schema often mirrors a screen, and that is
intended.

## Where the code does not follow this yet

Written down because an agent greps this tree and builds against what it
finds, and a rule with silent exceptions is worse than no rule.

- **Eleven endpoints write to the database directly**, without a service. The
  largest are `cabinet.upsert_helper` — the publish state machine and the
  offer diff — and `requests.request_feed`, which holds the matching and
  ranking algorithm.
- **There is no transaction rule.** Commits happen in route bodies, in two
  services, and once inside dependency resolution. The intended rule is
  *services never commit; the request commits*, and `db/session.py` is not yet
  a unit of work that could enforce it.
- **`services/` imports `api/schemas`,** which points the domain layer at the
  HTTP layer. Moving `schemas.py` to the package root fixes it.
- **`services/catalog._localised` is imported across the package boundary** by
  name, from a private symbol, at sixteen call sites, and three more
  "fetch localised names by id" helpers exist alongside it.

Each of these is a separate change with its own tests. None of them is a
reason to write new code the old way.
