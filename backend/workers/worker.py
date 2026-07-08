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
    last_idle_log_at = 0.0
    log_startup_diagnostics("worker", {"worker_id": worker_id, "app_role": settings.APP_ROLE})
    logger.info("Worker started worker_id=%s queue=%s", worker_id, settings.JOB_QUEUE_NAME)

    try:
        while True:
            job_record = await asyncio.to_thread(reserve_next_job, settings.JOB_POLL_TIMEOUT_SECONDS)
            if not job_record:
                now = time.time()
                if now - last_idle_log_at >= max(float(settings.WORKER_IDLE_LOG_SECONDS), 5.0):
                    logger.info(
                        "Worker idle worker_id=%s queue=%s poll_timeout=%ss sleep=%ss",
                        worker_id,
                        settings.JOB_QUEUE_NAME,
                        settings.JOB_POLL_TIMEOUT_SECONDS,
                        settings.WORKER_IDLE_SLEEP_SECONDS,
                    )
                    last_idle_log_at = now
                await asyncio.sleep(settings.WORKER_IDLE_SLEEP_SECONDS)
                continue
            logger.info(
                "Worker accepted job worker_id=%s job_id=%s session_id=%s",
                worker_id,
                str(job_record.get("job_id", "")).strip(),
                str(job_record.get("session_id", "")).strip(),
            )
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
