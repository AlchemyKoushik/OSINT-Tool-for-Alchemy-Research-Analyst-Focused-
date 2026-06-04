from fastapi import APIRouter

from api.analyze import analyze_topic, get_locations, get_research_job_status, research_topic

router = APIRouter(prefix="/api")
router.add_api_route("/locations", get_locations, methods=["GET"])
router.add_api_route("/research", research_topic, methods=["POST"])
router.add_api_route("/analyze", analyze_topic, methods=["POST"])
router.add_api_route("/research/jobs/{job_id}", get_research_job_status, methods=["GET"])
