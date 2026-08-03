.DEFAULT_GOAL := help
API := apps/api
WEB := apps/web

# Port 8010, not 8000: something else on this machine already listens there,
# and a dev server that silently fails to bind is worse than one on an odd port.
API_PORT ?= 8010

.PHONY: help
help:  ## Show this list
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

# ── setup ───────────────────────────────────────────────────────────────

.PHONY: setup
setup: db-up install migrate seed demo  ## Everything needed for a first run

.PHONY: install
install:  ## Install both apps' dependencies
	cd $(API) && uv sync
	cd $(WEB) && pnpm install

.PHONY: db-up
db-up:  ## Start Postgres and wait until it answers
	docker compose up -d db
	@until docker compose exec -T db pg_isready -q -U students_cz -d students_cz; \
	 do sleep 1; done
	@echo "database ready"

.PHONY: db-down
db-down:  ## Stop Postgres, keep the data
	docker compose down

.PHONY: db-reset
db-reset:  ## Throw the database away and rebuild it from scratch
	docker compose down -v
	$(MAKE) db-up migrate seed demo

.PHONY: db-shell
db-shell:  ## psql prompt
	docker compose exec db psql -U students_cz -d students_cz

# ── data ────────────────────────────────────────────────────────────────

.PHONY: migrate
migrate:  ## Apply migrations
	cd $(API) && uv run alembic upgrade head

.PHONY: revision
revision:  ## Autogenerate a migration: make revision m="what changed"
	cd $(API) && uv run alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed:  ## Load reference data: subjects, institutions, service types
	cd $(API) && uv run python -m students_cz.db.seed

.PHONY: demo
demo:  ## Load plausible content so the screens have something in them
	cd $(API) && uv run python -m students_cz.db.demo

.PHONY: demo-clear
demo-clear:  ## Remove demo content, keep reference data
	cd $(API) && uv run python -m students_cz.db.demo --clear

# ── running ─────────────────────────────────────────────────────────────

.PHONY: api
api:  ## Run the API and bot with reload
	cd $(API) && uv run uvicorn students_cz.main:app --reload --port $(API_PORT)

.PHONY: web
web:  ## Run the mini app
	cd $(WEB) && pnpm dev

CLOUDFLARED := $(shell command -v cloudflared 2>/dev/null || echo .tools/cloudflared)

.PHONY: tunnel-tool
tunnel-tool:  ## Fetch cloudflared into .tools if it is not on PATH
	@test -x "$(CLOUDFLARED)" || { \
	  mkdir -p .tools && \
	  curl -sfL -o .tools/cloudflared \
	    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && \
	  chmod +x .tools/cloudflared; }
	@"$(CLOUDFLARED)" --version

.PHONY: tunnel
tunnel: tunnel-tool  ## Expose the mini app over HTTPS so Telegram can reach it
	@echo "Put the printed https URL in PUBLIC_BASE_URL and in @BotFather,"
	@echo "then restart the API so it re-registers the webhook."
	"$(CLOUDFLARED)" tunnel --url https://localhost:5173 --no-tls-verify

# ── checks ──────────────────────────────────────────────────────────────

.PHONY: test
test:  ## Run both test suites (the API's needs the database up)
	cd $(API) && uv run pytest -q
	cd $(WEB) && pnpm test

.PHONY: lint
lint:  ## Lint and type-check both apps
	cd $(API) && uv run ruff check src tests && uv run ruff format --check src tests
	cd $(API) && uv run ty check src tests
	cd $(WEB) && pnpm lint && pnpm typecheck

.PHONY: format
format:  ## Reformat both apps
	cd $(API) && uv run ruff check --fix src tests && uv run ruff format src tests
	cd $(WEB) && pnpm format

# Named per user: /tmp is shared, and a file owned by somebody else fails in a
# way that reads as a broken check rather than a full disk.
OPENAPI_DUMP := $(or $(TMPDIR),/tmp)/students-cz-openapi-$(shell id -u).json

.PHONY: contract
contract:  ## Check the committed client still matches the API's OpenAPI document
	cd $(API) && uv run python -m students_cz.openapi > $(OPENAPI_DUMP)
	@# openapi-ts exits 0 without writing anything when its input is missing or
	@# empty, and a generator that quietly did nothing leaves a stale client
	@# looking identical to itself. Check the document before trusting the diff.
	@grep -q '"openapi"' $(OPENAPI_DUMP) || { \
	  echo "The OpenAPI dump is empty or not a document: $(OPENAPI_DUMP)"; \
	  exit 1; \
	}
	cd $(WEB) && OPENAPI_URL=$(OPENAPI_DUMP) pnpm api:generate
	@# --porcelain and not `git diff`: a generated file that is new is untracked,
	@# and `git diff` cannot see those at all. Kept in a variable so a git that
	@# failed — no repository, a dubious-ownership refusal, no git at all — is
	@# not read as an empty answer, which is the same string a clean tree gives.
	@changed=$$(git status --porcelain -- $(WEB)/src/lib/generated) || { \
	  echo "git status failed; the contract check compared nothing."; \
	  exit 1; \
	}; \
	test -z "$$changed" || { \
	  echo; \
	  echo "The generated client is out of date. Commit what api:generate just wrote."; \
	  git --no-pager status --short -- $(WEB)/src/lib/generated; \
	  exit 1; \
	}

.PHONY: check
check: lint test contract  ## Everything CI would run
