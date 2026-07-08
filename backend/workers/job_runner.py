import asyncio
import gc
import traceback
from typing import Any, Dict

from core.diagnostics import ResearchDiagnostics
from core.logging import get_logger
from config.settings import settings
from models.request_models import AnalyzeRequest
from workers.job_manager import mark_job_completed, mark_job_failed, mark_job_running, requeue_research_job, update_research_job

logger = get_logger(__name__)


def _is_non_retriable_job_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        message = str(current).strip()
        if "Response validation failed" in message:
            return True
        current = current.__cause__
    return False


async def run_research_job(job_record: Dict[str, Any], worker_id: str) -> None:
    from api.routes import run_analysis_request

    job_id = str(job_record.get("job_id", "")).strip()
    payload = dict(job_record.get("payload", {}) or {})
    request_model = AnalyzeRequest(**payload)
    diagnostics = ResearchDiagnostics(
        research_id=job_id,
        session_id=str(job_record.get("session_id", "")).strip() or str(request_model.session_id or ""),
        topic=request_model.topic,
        section=request_model.section,
    )

    def progress_callback(snapshot: Dict[str, Any]) -> None:
        update_research_job(
            job_id,
            {
                "status": "running",
                "stage": snapshot.get("stage", "Running"),
                "current_activity": snapshot.get("current_activity", "Processing"),
                "progress_percentage": int(snapshot.get("progress_percentage", 0)),
                "diagnostics": snapshot,
            },
        )

    running_record = mark_job_running(job_id, worker_id)
    progress_callback(
        diagnostics.mark_stage(
            "Initializing",
            activity="Preparing research pipeline",
            progress=3,
        )
    )

    try:
        result = await run_analysis_request(
            request_model,
            progress_callback=progress_callback,
            diagnostics=diagnostics,
        )
        final_snapshot = diagnostics.mark_stage(
            "Completed",
            activity="Research completed successfully",
            progress=100,
        )
        mark_job_completed(job_id, result, final_snapshot)
    except Exception as exc:
        logger.exception("Research job failed job_id=%s", job_id)
        failure_snapshot = diagnostics.mark_stage(
            "Failed",
            activity="Research job failed",
            progress=max(int(diagnostics.progress_percentage), 1),
            metadata={"traceback": traceback.format_exc(limit=20)},
        )
        attempt_count = int(running_record.get("attempts", job_record.get("attempts", 0)) or 0)
        if _is_non_retriable_job_error(exc):
            mark_job_failed(job_id, str(exc), failure_snapshot)
        elif attempt_count < settings.JOB_MAX_RETRIES:
            await asyncio.sleep(min(2 ** max(attempt_count, 0), 8))
            requeue_research_job(job_id, str(exc), failure_snapshot)
        else:
            mark_job_failed(job_id, str(exc), failure_snapshot)
    finally:
        payload.clear()
        gc.collect()
        await asyncio.sleep(0)
