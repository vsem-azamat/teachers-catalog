from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KONNEKT_",
        extra="ignore",
    )

    # Host port 5433 by default: 5432 is usually taken by a local Postgres.
    database_url: str = Field(
        default="postgresql+asyncpg://konnekt:konnekt@127.0.0.1:5433/konnekt"
    )
    db_echo: bool = False

    bot_token: str = ""
    # Telegram sends this back in X-Telegram-Bot-Api-Secret-Token on every
    # webhook call; anything else is not Telegram.
    webhook_secret: str = ""
    webhook_base_url: str = ""

    # How long an initData payload stays acceptable. Telegram's own guidance is
    # to reject anything older than a few hours.
    init_data_max_age_seconds: int = 3600

    jwt_secret: str = ""
    jwt_ttl_seconds: int = 900

    default_currency: str = "CZK"
    supported_ui_langs: tuple[str, ...] = ("ru", "cs", "en", "uk")


@lru_cache
def get_settings() -> Settings:
    return Settings()
