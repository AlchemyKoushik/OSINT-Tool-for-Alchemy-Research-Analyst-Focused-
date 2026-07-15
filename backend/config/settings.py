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
    ALLOWED_RESEARCH_SECTIONS: str = "trends,drivers,competitive_landscape"
    FOLLOW_UP_ENABLED: bool = True
    MAX_EXISTING_CHUNKS: int = 250
    MAX_CHUNK_TEXT_LENGTH: int = 6000
    CLEANUP_MAX_RETRIES: int = 2
    MAX_TRENDS_WITH_EXAMPLE_RESEARCH: int | None = None
    BACKFILL_ALL_MISSING_TREND_EXAMPLES: bool = True
    SEARCH_MAX_CONCURRENT_REQUESTS: int = 4
    SCRAPER_MAX_CONCURRENT_REQUESTS: int = 8
    CL_ENRICHMENT_CONCURRENCY: int = 0
    CL_DISCOVERY_CONCURRENCY: int = 0
    CL_OPENAI_CONCURRENCY: int = 3
    CL_SEARCH_CONCURRENCY: int = 2
    CL_SCRAPER_CONCURRENCY: int = 2
    CL_OPENAI_MIN_INTERVAL_MS: int = 250
    CL_SEARCH_MIN_INTERVAL_MS: int = 350
    CL_SCRAPER_MIN_INTERVAL_MS: int = 150
    JOB_QUEUE_NAME: str = "osint:research:queue"
    JOB_TTL_SECONDS: int = 21600
    JOB_POLL_TIMEOUT_SECONDS: int = 5
    JOB_MAX_RETRIES: int = 3
    WORKER_IDLE_SLEEP_SECONDS: float = 1.0
    WORKER_IDLE_LOG_SECONDS: float = 30.0

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

    @property
    def allowed_research_sections(self) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw_value in str(self.ALLOWED_RESEARCH_SECTIONS or "").split(","):
            section = raw_value.strip().lower()
            if section and section not in normalized:
                normalized.append(section)

        if not normalized:
            return ("trends", "drivers", "competitive_landscape")

        return tuple(normalized)


settings = Settings()
