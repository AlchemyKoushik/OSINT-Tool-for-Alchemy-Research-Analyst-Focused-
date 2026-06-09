import asyncio
import socket
import time

from config.settings import settings
from core.diagnostics import log_shutdown_diagnostics, log_startup_diagnostics
from core.logging import configure_logging, get_logger
from workers.job_manager import reserve_next_job
from workers.job_runner import run_research_job

configure_logging()
logger = get_logger(__name__)


async def worker_loop() -> None:
    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    log_startup_diagnostics("worker", {"worker_id": worker_id, "app_role": settings.APP_ROLE})
    logger.info("Worker started worker_id=%s queue=%s", worker_id, settings.JOB_QUEUE_NAME)

    try:
        while True:
            job_record = await asyncio.to_thread(reserve_next_job, settings.JOB_POLL_TIMEOUT_SECONDS)
            if not job_record:
                await asyncio.sleep(settings.WORKER_IDLE_SLEEP_SECONDS)
                continue
            await run_research_job(job_record, worker_id)
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
