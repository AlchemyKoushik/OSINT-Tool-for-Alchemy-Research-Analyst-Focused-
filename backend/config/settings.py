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
    APP_ROLE: str = "api"
    OPENAI_API_KEY: str = ""
    OPENAI_ANALYSIS_MODEL: str = "gpt-4.1"
    OPENAI_SUPPORT_MODEL: str = "gpt-4.1-mini"
    OPENAI_QUERY_MODEL: str = "gpt-4.1-mini"
    OPENAI_TEST_MODEL: str = "gpt-4.1-mini"
    SERPAPI_KEY: str = ""
    SCRAPEDO_KEY: str = ""
    USE_CRAWL4AI: bool = False
    COMPARE_CRAWLERS: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET_NAME: str = ""
    CLOUDFLARE_R2_REGION: str = "auto"
    EXTERNAL_TIMEOUT_SECONDS: int = 20
    EXTERNAL_MAX_RETRIES: int = 3
    SCRAPER_MAX_CONCURRENT_REQUESTS: int = 4
    SCRAPER_MAX_RETRIES: int = 2
    RETRY_JITTER_SECONDS: float = 0.35
    SEARCH_STAGGER_DELAY_SECONDS: float = 0.2
    SEARCH_STAGGER_JITTER_SECONDS: float = 0.15
    SCRAPE_BATCH_DELAY_SECONDS: float = 0.75
    SCRAPE_BATCH_JITTER_SECONDS: float = 0.35
    MAX_PIPELINE_SCRAPE_RESULTS: int = 120
    SCRAPE_BATCH_SIZE: int = 12
    TARGET_USABLE_TEXT_COUNT: int = 60
    SCRAPE_TIME_BUDGET_SECONDS: int = 900
    CRAWL4AI_TIMEOUT_SECONDS: int = 15
    CRAWL4AI_QUALITY_THRESHOLD: float = 0.45
    CRAWL4AI_MIN_CONTENT_LENGTH: int = 180
    CACHE_TTL_SECONDS: int = 3600
    SESSION_TTL_SECONDS: int = 3600
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 10
    MAX_REQUEST_BYTES: int = 250000
    MAX_EXPORT_REQUEST_BYTES: int = 2500000
    MAX_QUERY_LENGTH: int = 500
    MAX_FOLLOW_UP_QUERY_LENGTH: int = 500
    MAX_EXISTING_CHUNKS: int = 250
    MAX_CHUNK_TEXT_LENGTH: int = 6000
    CLEANUP_MAX_RETRIES: int = 2
    MAX_TRENDS_WITH_EXAMPLE_RESEARCH: int | None = None
    BACKFILL_ALL_MISSING_TREND_EXAMPLES: bool = True
    JOB_QUEUE_NAME: str = "osint:research:queue"
    JOB_TTL_SECONDS: int = 21600
    JOB_POLL_TIMEOUT_SECONDS: int = 5
    JOB_MAX_RETRIES: int = 3
    WORKER_IDLE_SLEEP_SECONDS: float = 1.0
    WORKER_HEARTBEAT_FILE: str = "/tmp/osint-worker-heartbeat"
    WORKER_HEARTBEAT_MAX_AGE_SECONDS: int = 120

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
