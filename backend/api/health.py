from fastapi import APIRouter

from config.settings import settings
from core.diagnostics import get_system_health_snapshot
from services.openai_service import can_use_openai, get_openai_status_message, openai_key_loaded
from services.redis_service import get_redis_status
from workers.job_manager import get_job_metrics

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    redis_status = get_redis_status()
    status = "healthy" if redis_status.get("available") else "degraded"
    return {"status": status}


@router.get("/health/detailed")
def detailed_health_check() -> dict[str, object]:
    redis_status = get_redis_status()
    job_metrics = get_job_metrics()
    return {
        "status": "healthy" if redis_status.get("available") else "degraded",
        "system": get_system_health_snapshot(),
        "queue": job_metrics,
        "redis": redis_status,
        "openai": {
            "configured": openai_key_loaded(),
            "available": can_use_openai(),
            "message": get_openai_status_message(),
        },
        "app_role": settings.APP_ROLE,
    }


@router.get("/metrics")
def metrics() -> dict[str, object]:
    system = get_system_health_snapshot()
    redis_status = get_redis_status()
    queue = get_job_metrics()
    return {
        "cpu": system.get("cpu_percent", 0.0),
        "ram": system.get("memory_percent", 0.0),
        "queue_length": queue.get("queue_length", 0),
        "active_jobs": queue.get("active_jobs", 0),
        "completed_jobs": queue.get("completed_jobs", 0),
        "failed_jobs": queue.get("failed_jobs", 0),
        "redis_status": redis_status.get("available", False),
        "openai_status": {
            "available": can_use_openai(),
            "message": get_openai_status_message(),
        },
    }
