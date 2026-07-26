# Students CZ

A Telegram Mini App for students in the Czech Republic — mostly foreigners —
looking for people who can help: tutors, entrance-exam preparation, help during
an exam, nostrification, written work, gear to rent, textbooks, notes.

Alongside that sits a second line of things a foreign student here has to buy
anyway: insurance, a language course that carries a visa, a bank statement, a
sworn translation. Those are partner placements — always labelled, and shown on
the screen for the task the person is already doing rather than as a banner.

The Python package, the Docker images and the database are all called
`konnekt`. That is the name of the code, not of the product: renaming what
nobody sees costs a day of broken imports and buys nothing.

## How it is put together

```
apps/api     FastAPI + aiogram in one process, Postgres 18
apps/web     React 19 + Vite, the mini app itself
docs         data-model.md — the schema and the reasoning behind it
infra        database bootstrap
```

The bot and the API share a process on purpose. Since 20 July 2026 Telegram
only allows Mini App API calls from the app's own origin, so the page and the
API it talks to have to be the same host regardless.

Three ideas run through the whole thing.

**One input field, not a category tree.** A student types "нужен матан на ČVUT,
экзамен 14 февраля" and gets back three editable chips and at most one
clarifying question. The taxonomy did not go away — it moved into the database,
out of the interface.

**The catalog is three axes crossing.** Subject × institution × kind of help,
meeting in `offers`. A new kind of help is a row, not a schema change.

**Say why.** Every result carries the reason it is in the list, including when
the honest reason is "cheaper than the rest, but has never seen your exam".
That is what makes the other rows believable.

## Running it

Needs Docker, [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```sh
cp .env.example .env      # fill in BOT_TOKEN if you have one
make setup                # database, dependencies, migrations, seed, demo data
make api                  # http://127.0.0.1:8010
make web                  # https://localhost:5173
```

`make help` lists the rest.

The API runs without a bot token — it logs a warning and skips the webhook. To
exercise it from a browser instead of from Telegram, set
`ALLOW_UNSIGNED_INIT_DATA=true`, which turns off signature checking. Local
development only: it lets anyone claim to be anyone.

### Reaching it from Telegram

Telegram will not open a mini app over plain HTTP, and will not accept an
origin other than the registered one. A quick tunnel:

```sh
make tunnel               # prints an https://….trycloudflare.com URL
```

Put that URL in `PUBLIC_BASE_URL`, restart the API so it re-registers the
webhook, and set the same URL as the mini app in @BotFather.

## Outside Telegram

The catalog only works inside Telegram — that is where the accounts, the
conversations and the notifications are — so opening the domain in a browser
gets a landing page instead of a broken app. It is one screen, does not
scroll, and has one button.

That button points at `/api/v1/open`, the only unauthenticated route in the
API, which redirects to the bot. The handle therefore lives in one place, the
token the server already runs with, rather than being copied into the frontend
and into the build. Add `?landing` to any URL to see the page from inside
development.

The palette is the app's own, not Telegram's, and the person picks it:
system, light or dark, from the profile screen. The choice is resolved by an
inline script in `index.html` before the first paint, because a module that
runs after one is a module that runs after the flash.

## Deploying

CI builds images, pushes them to GHCR and deploys over SSH to a shared VPS,
behind Cloudflare and a shared Caddy. The runbook, the one-time setup and the
two ways to break production are in [docs/deploy.md](docs/deploy.md).

## Checks

```sh
make check                # everything CI runs
make test                 # just the API suite
```

Tests run against a real Postgres, each inside a transaction that is rolled
back. The interesting logic here is SQL — trigram matching, word-boundary
synonym matching, exclusion constraints — and none of it survives being mocked.

The tooling is [uv](https://docs.astral.sh/uv/) and
[ruff](https://docs.astral.sh/ruff/) plus [ty](https://docs.astral.sh/ty/) on
the API, [Biome](https://biomejs.dev/), TypeScript and
[Vite](https://vite.dev/) on the mini app, and `lingui compile --strict` so an
untranslated string fails the build rather than falling back to Russian.

`ty` is in preview, so its version is pinned in the lockfile like everything
else: a checker that changes its mind on an unrelated push is a checker people
learn to ignore. It earned its place immediately — `availability_slots.period`
was typed as `object`, which meant every read of `.lower` and `.upper` was
unverifiable, and once it was a real `Range[datetime]` the bounds turned out to
be optional in the type and non-optional only by a database constraint.

### The docs contract

A separate CI job runs [stdd](https://github.com/vsem-azamat/stdd), which
guards two things this repository cares about because most of the code in it
is written with an agent.

The first is that `docs/` and this file describe the present. An agent greps
the tree, finds text that reads authoritative, and builds against it — so a
paragraph narrating an earlier state of the code is not history in there, it
is a trap. `stdd check` flags that phrasing and refuses committed plan and
spec artifacts anywhere. Rationale belongs in the commit message and the pull
request, where it is dated by construction.

The second is that a pull request says which docs it updated. `stdd check-pr`
reads the live body — not the webhook payload, which freezes at trigger time —
and verifies the paths it claims against the actual diff. Draft the line with
`npx @stdd/cli evidence --base origin/main`.

Only that contract is adopted. stdd also offers a recorded loop and an
orchestration layer with plans, slices and delegated review; this is one
person and one agent, and neither has a problem those solve yet.

## The four languages

`ru`, `cs`, `en`, `uk` — and they are two separate problems.

Reference data is translated in the database, so subject and faculty names
arrive already in the caller's language. Sentences the interface composes do
not: the API returns a code and parameters, and the client renders them. Czech
has four plural forms and Russian's are shaped differently; that belongs where
the plural rules live.

Language is also a *matching* attribute, not only a display setting. A profile
written in Russian stays Russian, and a Ukrainian first-year cannot work with a
Czech-only tutor. `users.spoken_langs` and `offers.langs` are indexed arrays, so
that filter is one query.

The list people pick from is those four and no more: a question with four
answers gets answered and one with nine gets skipped, and every code beyond
these four is one nobody here has ever been matched on. Codes taken off the
list are deactivated rather than deleted, because profiles already hold them.

## What is not here yet

Payments, reviews, moderation, and half the catalog — things to rent, books,
materials. `materials.price_stars` exists and nothing writes to it;
`MaterialAccess.PAID` is unreachable. The schema says so rather than pretending.

The original command-driven bot still sits in `bot/` and is documented in
[docs/legacy-bot.md](docs/legacy-bot.md). Nothing new depends on it — it is kept
only as the source for a one-off data import, and goes once that has run.
