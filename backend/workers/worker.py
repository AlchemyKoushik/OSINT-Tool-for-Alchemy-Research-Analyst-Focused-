import asyncio
import socket
import time
from pathlib import Path

from config.settings import settings
from core.diagnostics import log_shutdown_diagnostics, log_startup_diagnostics
from core.logging import configure_logging, get_logger
from workers.job_manager import reserve_next_job
from workers.job_runner import run_research_job

configure_logging()
logger = get_logger(__name__)

REQUIRED_WORKER_SETTINGS = (
    "OPENAI_API_KEY",
    "SCRAPEDO_KEY",
    "REDIS_URL",
    "CLOUDFLARE_R2_ACCOUNT_ID",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_R2_BUCKET_NAME",
)


def _write_heartbeat() -> None:
    heartbeat_path = Path(settings.WORKER_HEARTBEAT_FILE).expanduser()
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(str(time.time()), encoding="utf-8")


async def worker_loop() -> None:
    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    log_startup_diagnostics("worker", {"worker_id": worker_id, "app_role": settings.APP_ROLE})
    settings.validate_required(REQUIRED_WORKER_SETTINGS)
    logger.info(
        "Worker runtime config worker_id=%s openai_model=%s query_model=%s scrapedo_configured=%s serpapi_configured=%s use_crawl4ai=%s compare_crawlers=%s",
        worker_id,
        settings.OPENAI_ANALYSIS_MODEL,
        settings.OPENAI_QUERY_MODEL,
        bool(settings.SCRAPEDO_KEY.strip()),
        bool(settings.SERPAPI_KEY.strip()),
        settings.USE_CRAWL4AI,
        settings.COMPARE_CRAWLERS,
    )
    logger.info("Worker started worker_id=%s queue=%s", worker_id, settings.JOB_QUEUE_NAME)
    _write_heartbeat()

    try:
        while True:
            _write_heartbeat()
            job_record = await asyncio.to_thread(reserve_next_job, settings.JOB_POLL_TIMEOUT_SECONDS)
            if not job_record:
                await asyncio.sleep(settings.WORKER_IDLE_SLEEP_SECONDS)
                continue
            await run_research_job(job_record, worker_id)
            _write_heartbeat()
    except asyncio.CancelledError:
        logger.info("Worker cancelled worker_id=%s", worker_id)
        raise
    finally:
        log_shutdown_diagnostics("worker", {"worker_id": worker_id})


def main() -> None:
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")


if __name__ == "__main__":
    main()
