from fastapi import APIRouter

from api.analyze import cleanup_session

router = APIRouter(prefix="/api")
router.add_api_route("/sessions/{session_id}", cleanup_session, methods=["DELETE"])
