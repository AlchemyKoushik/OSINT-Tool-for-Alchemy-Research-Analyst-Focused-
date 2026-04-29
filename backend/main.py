import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config.settings import settings
from services.openai_service import openai_key_loaded, test_openai_connection
from services.redis_service import redis_client
from services.search_service import test_ddg

logger = logging.getLogger(__name__)

app = FastAPI(
    title="OSINT Research Tool Backend",
    description="AI-powered OSINT Research Tool API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def startup_checks() -> None:
    print("=================================")
    print("SYSTEM START CHECK")
    print("=================================")
    settings.validate_required(
        (
            "OPENAI_API_KEY",
            "SCRAPEDO_KEY",
            "REDIS_URL",
            "CLOUDFLARE_R2_ACCOUNT_ID",
            "CLOUDFLARE_R2_ACCESS_KEY_ID",
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
            "CLOUDFLARE_R2_BUCKET_NAME",
        )
    )

    try:
        await asyncio.to_thread(redis_client.ping)
    except Exception as exc:
        logger.exception("Redis startup validation failed.")
        raise RuntimeError(f"Redis startup validation failed: {exc}") from exc

    try:
        openai_loaded, openai_test_result, ddg_test_result = await asyncio.gather(
            asyncio.to_thread(openai_key_loaded),
            asyncio.to_thread(test_openai_connection),
            asyncio.to_thread(test_ddg),
        )
    except Exception as exc:
        logger.exception("Startup checks failed.")
        raise RuntimeError(f"Startup checks failed: {exc}") from exc

    print(f"- OpenAI Key Loaded: {'YES' if openai_loaded else 'NO'}")
    print(f"- OpenAI Test Result: {'SUCCESS' if openai_test_result else 'FAILED'}")
    print(f"- DDG Test Result: {'SUCCESS' if ddg_test_result else 'FAILED'}")
    print("=================================")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
