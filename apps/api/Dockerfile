# syntax=docker/dockerfile:1.7

# Build and runtime are separated so the image that ships carries no compilers,
# no uv, and no lockfile — only the virtualenv and the source it needs.

FROM python:3.14-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile alone, in their own layer, so editing
# application code does not reinstall the world.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY alembic.ini ./
# The reference data ships with the code that reads it: seeding production is
# not a development-only task, and a seed file that drifts from its loader is
# worse than no seed file.
COPY seeds ./seeds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-slim-bookworm AS runtime

# Non-root from the start. The application writes nothing to disk — Postgres
# holds the state and Telegram holds the files.
RUN groupadd --system --gid 1001 students_cz \
    && useradd --system --uid 1001 --gid students_cz --create-home students_cz

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder --chown=students_cz:students_cz /app/.venv /app/.venv
COPY --from=builder --chown=students_cz:students_cz /app/src /app/src
COPY --from=builder --chown=students_cz:students_cz /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=students_cz:students_cz /app/seeds /app/seeds

USER students_cz
EXPOSE 8000

# One worker, deliberately. The lifespan hook creates the bot, registers the
# webhook and holds aiogram's dispatcher state; a second worker would register
# the webhook twice and keep half the state in the wrong process.
CMD ["uvicorn", "students_cz.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
