from fastapi import APIRouter

from api.analyze import submit_feedback

router = APIRouter(prefix="/api")
router.add_api_route("/feedback", submit_feedback, methods=["POST"])
