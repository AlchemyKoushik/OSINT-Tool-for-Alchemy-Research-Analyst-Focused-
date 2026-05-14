import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config.settings import settings
from services.openai_service import openai_key_loaded, test_openai_connection
from services.redis_service import ping_redis
from services.search_service import test_ddg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)
STARTUP_DIAGNOSTIC_TIMEOUT_SECONDS = 30
STARTUP_REDIS_TIMEOUT_SECONDS = 3

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


async def _run_startup_diagnostics(redis_available: bool) -> None:
    try:
        openai_loaded, openai_test_result, ddg_test_result = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(openai_key_loaded),
                asyncio.to_thread(test_openai_connection),
                asyncio.to_thread(test_ddg),
            ),
            timeout=STARTUP_DIAGNOSTIC_TIMEOUT_SECONDS,
        )
        logger.info(
            "startup_check_complete redis_available=%s openai_key_loaded=%s openai_test=%s ddg_test=%s",
            redis_available,
            openai_loaded,
            openai_test_result,
            ddg_test_result,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "startup_diagnostics_timeout timeout_seconds=%s redis_available=%s",
            STARTUP_DIAGNOSTIC_TIMEOUT_SECONDS,
            redis_available,
        )
    except Exception as exc:
        logger.warning(
            "startup_diagnostics_failed redis_available=%s error=%s",
            redis_available,
            exc,
        )


@app.on_event("startup")
async def startup_checks() -> None:
    logger.info("startup_check_begin")
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

    redis_available = False
    try:
        redis_available = await asyncio.wait_for(
            asyncio.to_thread(ping_redis),
            timeout=STARTUP_REDIS_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Redis startup validation timed out after %s seconds. Continuing with in-memory fallback.",
            STARTUP_REDIS_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("Redis startup validation failed. Continuing with in-memory fallback. error=%s", exc)

    if not redis_available:
        logger.warning("Redis unavailable at startup. Continuing with in-memory fallback.")

    asyncio.create_task(_run_startup_diagnostics(redis_available))
    logger.info("startup_check_ready redis_available=%s diagnostics=background", redis_available)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
