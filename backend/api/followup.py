from fastapi import APIRouter

from api.analyze import analyze_existing, follow_up

router = APIRouter(prefix="/api")
router.add_api_route("/follow-up", follow_up, methods=["POST"])
router.add_api_route("/analyze-existing", analyze_existing, methods=["POST"])
