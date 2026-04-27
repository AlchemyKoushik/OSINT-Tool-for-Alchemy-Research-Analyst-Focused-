from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from services.openai_service import openai_key_loaded, test_openai_connection
from services.search_service import test_ddg

app = FastAPI(
    title="OSINT Research Tool Backend",
    description="AI-powered OSINT Research Tool API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def startup_checks() -> None:
    print("=================================")
    print("SYSTEM START CHECK")
    print("=================================")
    openai_loaded = openai_key_loaded()
    openai_test_result = test_openai_connection()
    ddg_test_result = test_ddg()
    print(f"- OpenAI Key Loaded: {'YES' if openai_loaded else 'NO'}")
    print(f"- OpenAI Test Result: {'SUCCESS' if openai_test_result else 'FAILED'}")
    print(f"- DDG Test Result: {'SUCCESS' if ddg_test_result else 'FAILED'}")
    print("=================================")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
