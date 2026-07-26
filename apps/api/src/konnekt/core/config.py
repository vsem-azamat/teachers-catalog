from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/src/konnekt/core/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    # One .env at the repo root, shared with docker compose, so the database
    # credentials cannot drift between the container and the application.
    # Found regardless of whether the process starts from the root or apps/api.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    postgres_user: str = "konnekt"
    postgres_password: str = "konnekt"
    postgres_db: str = "konnekt"
    postgres_host: str = "127.0.0.1"
    # 5433 on the host: 5432 is usually taken by a local Postgres.
    postgres_port: int = 5433

    # Set this to override the assembled URL, e.g. when the API runs inside
    # compose and has to reach the database by service name.
    database_url: str | None = None
    db_echo: bool = False

    @computed_field
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Telegram ────────────────────────────────────────────────────────
    bot_token: str = ""
    # Echoed back by Telegram in X-Telegram-Bot-Api-Secret-Token on every
    # webhook call; anything else is not Telegram.
    webhook_secret: str = ""
    webhook_path: str = "/tg/webhook"
    # Public HTTPS origin. Since 20 July 2026 Telegram only allows Mini App API
    # calls from the app's own origin, so a preview deployment on a different
    # domain will not work.
    public_base_url: str = ""

    # How long an initData payload stays usable. Telegram mandates nothing here
    # and aiogram does not check it at all — the number is ours. A day is long
    # enough that a session does not expire mid-use, short enough that a leaked
    # payload is not a standing key.
    init_data_max_age_seconds: int = 86_400
    # Lets the API run without a bot token in local development. Never true in
    # anything reachable from the internet.
    allow_unsigned_init_data: bool = False

    # ── Behaviour ───────────────────────────────────────────────────────
    default_currency: str = "CZK"
    default_ui_lang: str = "ru"
    supported_ui_langs: tuple[str, ...] = ("ru", "cs", "en", "uk")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
