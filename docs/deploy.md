# Deployment

Production runs on a shared VPS alongside other projects. The shape follows the
one already in use there, so the two behave the same way when something breaks.

```
client
  → Cloudflare (TLS, proxied A record)
  → shared Edge Caddy on the host, ports 80/443
  → 127.0.0.1:<project port>
  → this project's Caddy
  → the mini app (static) or FastAPI (/api, /healthz, /tg)
```

The webhook, the API and the page share one origin. That is not tidiness:
since 20 July 2026 Telegram only allows Mini App API calls from the app's own
origin.

## How a deployment happens

Nothing is built on the server.

1. Push to `main` runs **CI**. Deployment is a separate workflow triggered by
   CI *succeeding* — so only a commit that passed tests can ship.
2. **Deploy** builds two images and pushes them to GHCR under
   `prod-<short-sha>` and `prod-latest`. The immutable tag is what gets
   deployed; `prod-latest` exists only for humans reading the registry.
3. It copies the compose file, the Caddyfile, the route script and a freshly
   generated mode-0600 `.env` to the server over SSH.
4. On the server: `docker compose run --rm migrate` — Alembic runs to
   completion before anything serves traffic, and a failed migration stops the
   deployment with a readable error instead of crash-looping the API.
5. `docker compose up -d --wait` — every service must report healthy.
6. The published port is asserted to be `127.0.0.1:<port>` and nothing else.
7. The hostname is registered with the shared Edge Caddy, under a marked block
   this project owns, behind a host-wide lock, validated before reload and
   rolled back on failure.
8. Public smoke tests, and a check that Telegram is pointing at our webhook.

If anything fails before step 6, the previous `.env` is restored and the
previous stack is brought back up. After step 6 the release is committed;
recovering from a bad release is `Rollback production`.

### Reference data does not ship with the code

Step 4 runs Alembic and nothing else. `konnekt.db.seed` — subjects,
institutions, service types, languages — is a development and CI convenience;
production was seeded once and is never re-seeded.

So a change to `seed.py` alone reaches every fresh checkout and never reaches
the catalog people are using. Anything that has to take effect in production
needs a migration carrying the same change, and the migration writes the
values out rather than importing the constant: a migration describes the
database at one moment, and one that follows a constant changes meaning the
next time that constant does.

## Rolling back

Run the **Rollback production** workflow with a tag such as `prod-1a2b3c4`. It
rewrites `IMAGE_TAG` in the server's `.env`, pulls, and restarts. It does not
build and it does not migrate — reversing a schema change is a separate,
riskier decision that should be made deliberately.

Only per-commit tags are accepted. `prod-latest` would roll *forward* to
whatever shipped last, which is the opposite of what the button says.

## One-time setup

None of this is in the repository, because the repository is public.

### 1. DNS

In Cloudflare, on the zone: an **A** record for the chosen subdomain, pointing
at the same origin as the existing project, **proxied** (orange cloud), TTL
auto. Nothing in CI provisions DNS.

### 2. A deploy identity on the server

Prefer a dedicated key over reusing a personal one. Membership of the `docker`
group is effectively root, so this identity should be treated as such.

```sh
ssh-keygen -t ed25519 -C 'github-actions konnekt deploy' -f konnekt_deploy
ssh-copy-id -i konnekt_deploy.pub <user>@<host>
ssh-keyscan -t ed25519 <host>          # for DEPLOY_KNOWN_HOSTS
```

### 3. Repository secrets

| Secret | What it is |
| --- | --- |
| `DEPLOY_HOST` | Server address. Never commit it — the repository is public. |
| `DEPLOY_USER` | SSH user. |
| `DEPLOY_DIR` | Absolute path for this project's directory on the server. |
| `DEPLOY_SSH_KEY` | Private key from step 2. |
| `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan`. Deliberately not fetched at deploy time — accepting whatever key answers would defeat the point. |
| `EDGE_CADDY_DIR` | Directory of the shared edge project. |
| `EDGE_CADDY_COMPOSE_FILE` | Its compose file. |
| `EDGE_CADDYFILE` | Path on the host to the shared Caddyfile. |
| `BOT_TOKEN` | From @BotFather. See the warning below about which bot. |
| `WEBHOOK_SECRET` | `openssl rand -hex 32`. At least 32 characters; the deploy refuses less. |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24`. |

### 4. Repository variables

| Variable | Value |
| --- | --- |
| `PUBLIC_HOST` | `https://<subdomain>` — scheme and host, no path, no trailing slash. |
| `PUBLIC_PORT` | A loopback port not used by another project on the host. |
| `EDGE_CADDY_SERVICE` | Service name of the edge Caddy in its compose file. |
| `EDGE_CADDY_CONFIG_PATH` | Path to the Caddyfile *inside* that container. |
| `POSTGRES_DB`, `POSTGRES_USER` | Optional; both default to `konnekt`. |
| `INIT_DATA_MAX_AGE_SECONDS` | Optional; defaults to 86400. |
| `BACKUP_HOUR_UTC`, `BACKUP_RETENTION_DAYS` | Optional; default 3 and 14. |

### 5. In @BotFather

Set the Mini App URL to `PUBLIC_HOST`. The webhook is registered by the
application at startup, but that does **not** configure the Mini App or the
menu button — the app sets the menu button itself, and the Main Mini App entry
has to be set by hand.

## Two ways to break production

**Running the legacy bot with the production token.** `bot/` still contains the
old polling bot, and polling calls `delete_webhook()`. Start it against the
production token and the webhook silently stops existing. It is not in any
image and no workflow runs it, but do not run it locally with that token
either. See [legacy-bot.md](legacy-bot.md).

**More than one Uvicorn worker.** The lifespan hook creates the bot, registers
the webhook and holds aiogram's dispatcher state. Two workers register the
webhook twice and keep half the state in the wrong process. The Dockerfile
pins `--workers 1`; leave it there until the bot moves out of the API process.

## Backups

A sidecar runs `pg_dump --format=custom` daily at `BACKUP_HOUR_UTC` into
`<DEPLOY_DIR>/data/backups`, keeping `BACKUP_RETENTION_DAYS`. Dumps are written
to a `.part` file and renamed only on success, so a partial file is never
mistaken for a usable backup.

They sit on the same disk as the database, which protects against a bad
migration and not against losing the machine. Copying them off the host is not
set up yet.

To restore:

```sh
docker compose exec -T postgres pg_restore --clean --if-exists \
  -U konnekt -d konnekt < data/backups/konnekt-<stamp>.dump
```

Test that on a copy before you need it in anger.

## Checking on it

```sh
curl https://<host>/healthz                      # API and database
curl -sI https://<host>/                         # the mini app
docker compose -f <DEPLOY_DIR>/docker-compose.yml ps
docker compose -f <DEPLOY_DIR>/docker-compose.yml logs -f api
```

Telegram's own view of the webhook, which is the one that matters:

```sh
curl "https://api.telegram.org/bot<token>/getWebhookInfo"
```

`pending_update_count` climbing means updates are arriving and not being
accepted. A `last_error_message` naming a certificate or DNS problem is
Cloudflare or the edge, not this project.
