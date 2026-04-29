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


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_ANALYSIS_MODEL: str = "gpt-5.4"
    OPENAI_QUERY_MODEL: str = "gpt-4o-mini"
    OPENAI_TEST_MODEL: str = "gpt-4o-mini"
    SERPAPI_KEY: str = ""
    SCRAPEDO_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET_NAME: str = ""
    CLOUDFLARE_R2_REGION: str = "auto"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE_FILE),
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
