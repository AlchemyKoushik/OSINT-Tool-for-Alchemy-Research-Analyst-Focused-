from fastapi import APIRouter

from api.analyze import (
    analyze_existing,
    analyze_topic,
    cleanup_session,
    export_memo,
    export_pdf,
    follow_up,
    get_locations,
    get_research_job_status,
    research_topic,
    run_analysis_request,
    submit_feedback,
)
from api.admin import router as admin_router
from api.analyze_routes import router as analyze_router
from api.exports import router as exports_router
from api.followup import router as followup_router
from api.health import router as health_router
from api.sessions import router as sessions_router

router = APIRouter()
router.include_router(health_router)
router.include_router(analyze_router)
router.include_router(followup_router)
router.include_router(exports_router)
router.include_router(sessions_router)
router.include_router(admin_router)

__all__ = [
    "analyze_existing",
    "analyze_topic",
    "cleanup_session",
    "export_memo",
    "export_pdf",
    "follow_up",
    "get_locations",
    "get_research_job_status",
    "research_topic",
    "router",
    "run_analysis_request",
    "submit_feedback",
]
