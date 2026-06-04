from fastapi import APIRouter

from api.analyze import export_memo, export_pdf

router = APIRouter(prefix="/api")
router.add_api_route("/export-memo", export_memo, methods=["POST"])
router.add_api_route("/export-pdf", export_pdf, methods=["POST"])
