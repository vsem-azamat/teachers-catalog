# Konnekt

A Telegram Mini App for students in the Czech Republic — mostly foreigners —
looking for people who can help: tutors, entrance-exam preparation, help during
an exam, nostrification, written work, gear to rent, textbooks, notes.

Alongside that sits a second line of things a foreign student here has to buy
anyway: insurance, a language course that carries a visa, a bank statement, a
sworn translation. Those are partner placements — always labelled, and shown on
the screen for the task the person is already doing rather than as a banner.

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

## Testing

```sh
make test
```

Tests run against a real Postgres, each inside a transaction that is rolled
back. The interesting logic here is SQL — trigram matching, word-boundary
synonym matching, exclusion constraints — and none of it survives being mocked.

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

The list people pick from is those four and no more. It used to be nine, and
the tail of it — Slovak, German, Kazakh, Uzbek, Vietnamese — never matched a
pair while making the question long enough to skip. Retired codes are
deactivated rather than deleted, because profiles already hold them.

## What is not here yet

Payments, reviews, moderation, and half the catalog — things to rent, books,
materials. `materials.price_stars` exists and nothing writes to it;
`MaterialAccess.PAID` is unreachable. The schema says so rather than pretending.

The original command-driven bot still sits in `bot/` and is documented in
[docs/legacy-bot.md](docs/legacy-bot.md). Nothing new depends on it — it is kept
only as the source for a one-off data import, and goes once that has run.
