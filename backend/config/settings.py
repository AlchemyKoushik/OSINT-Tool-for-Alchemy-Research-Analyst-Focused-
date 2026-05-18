import os
from pathlib import Path
from typing import Iterable

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE_FILE = BACKEND_DIR / ".env.example"


def _is_production_environment() -> bool:
    environment = str(
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("FASTAPI_ENV")
        or os.getenv("RENDER")
        or ""
    ).strip().lower()
    return environment in {"1", "true", "production", "prod", "render"}


def _resolve_env_files() -> tuple[str, ...]:
    if ENV_FILE.exists():
        return (str(ENV_FILE),)
    if not _is_production_environment() and ENV_EXAMPLE_FILE.exists():
        return (str(ENV_EXAMPLE_FILE),)
    return ()


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_ANALYSIS_MODEL: str = "gpt-4.1"
    OPENAI_SUPPORT_MODEL: str = "gpt-4.1-mini"
    OPENAI_QUERY_MODEL: str = "gpt-4.1-mini"
    OPENAI_TEST_MODEL: str = "gpt-4.1-mini"
    SERPAPI_KEY: str = ""
    SCRAPEDO_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET_NAME: str = ""
    CLOUDFLARE_R2_REGION: str = "auto"
    EXTERNAL_TIMEOUT_SECONDS: int = 20
    EXTERNAL_MAX_RETRIES: int = 3
    CACHE_TTL_SECONDS: int = 3600
    SESSION_TTL_SECONDS: int = 3600
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 10
    MAX_REQUEST_BYTES: int = 250000
    MAX_QUERY_LENGTH: int = 500
    MAX_FOLLOW_UP_QUERY_LENGTH: int = 500
    MAX_EXISTING_CHUNKS: int = 250
    MAX_CHUNK_TEXT_LENGTH: int = 6000
    CLEANUP_MAX_RETRIES: int = 2
    MAX_TRENDS_WITH_EXAMPLE_RESEARCH: int | None = None
    BACKFILL_ALL_MISSING_TREND_EXAMPLES: bool = True
    DEMO_REPLAY_ENABLED: bool = True
    DEMO_REPLAY_DELAY_SECONDS: int = 60
    DEMO_REPLAY_HTML_PATH: str = "data/demo_replay_memo.html"

    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    def validate_required(self, keys: Iterable[str]) -> None:
        missing = [key for key in keys if not str(getattr(self, key, "")).strip()]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


settings = Settings()
