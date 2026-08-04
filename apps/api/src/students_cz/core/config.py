from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Walk up from this file looking for a .env.

    Not a fixed number of parents: the repository layout puts this five levels
    below the root, but the container image puts it three, and hard-coding the
    depth made the module raise IndexError on import inside Docker. Searching
    upward works in both and simply finds nothing when there is nothing.
    """
    for directory in Path(__file__).resolve().parents:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    # One .env at the repo root, shared with docker compose, so the database
    # credentials cannot drift between the container and the application.
    # Found regardless of where the process was started from — and in
    # production there is no file at all, only the environment.
    model_config = SettingsConfigDict(
        env_file=(ENV_FILE, ".env") if ENV_FILE else (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    postgres_user: str = "students_cz"
    postgres_password: str = "students_cz"
    postgres_db: str = "students_cz"
    postgres_host: str = "127.0.0.1"
    # 5433 on the host: 5432 is usually taken by a local Postgres.
    postgres_port: int = 5433

    # Set this to override the assembled URL, e.g. when the API runs inside
    # compose and has to reach the database by service name.
    database_url: str | None = None
    db_echo: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # One pool per process, and the Dockerfile pins `--workers 1`, so these are
    # the whole connection budget: at most `db_pool_size + db_max_overflow`
    # against Postgres. Raise them together with the worker count, never one
    # without looking at the other.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Postgres and anything in front of it will close an idle connection
    # eventually and say nothing. pool_pre_ping catches that on checkout at the
    # cost of a round trip; recycling retires connections before they get old
    # enough for it to matter.
    db_pool_recycle_seconds: int = 1800

    @computed_field
    @property
    def webhook_url(self) -> str:
        """Where Telegram is told to send updates, and what /healthz compares.

        Derived once: registration and the health check building the same
        string separately is how a health check starts reporting "elsewhere"
        about a webhook that is perfectly correct.
        """
        return f"{self.public_base_url.rstrip('/')}{self.webhook_path}"

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
    # Told when a profile or a request appears, and nothing else. Unset — which
    # is how it runs everywhere but production — means no ping. A numeric
    # Telegram id and not a handle: the bot needs a chat it can open, and it
    # can only open one with somebody who has started it.
    owner_tg_id: int | None = None

    @field_validator("owner_tg_id", mode="before")
    @classmethod
    def _blank_is_nobody(cls, value: object) -> object:
        """An unset variable reaches us as an empty string, not as absent.

        Compose writes `OWNER_TG_ID=` whether or not anybody set it, and an
        empty string is not an integer — so without this the API refuses to
        start in exactly the configuration that means "no ping".
        """
        return None if value == "" else value

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
