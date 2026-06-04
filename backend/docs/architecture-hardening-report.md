# Architecture Hardening Report

## Updated Architecture

```text
Frontend
  frontend/index.html
  frontend/ui/app.js
  frontend/ui/components/
  frontend/ui/hooks/
  frontend/ui/services/
  frontend/ui/pages/
  frontend/ui/utils/

API
  backend/main.py
  backend/api/routes.py
  backend/api/analyze.py
  backend/api/analyze_routes.py
  backend/api/followup.py
  backend/api/exports.py
  backend/api/sessions.py
  backend/api/admin.py
  backend/api/health.py

Runtime
  backend/core/logging.py
  backend/core/diagnostics.py
  backend/workers/job_manager.py
  backend/workers/job_runner.py
  backend/workers/worker.py

Research Services
  backend/services/scraper_service.py
  backend/services/scrapers/
  backend/services/openai_service.py
  backend/services/openai/
  backend/services/source_confidence_service.py
  backend/services/contradiction_detection_service.py
  backend/services/security/url_guard.py

Models
  backend/models/response_models.py
  backend/models/research_models.py
  backend/models/report_models.py
  backend/models/trend_models.py
  backend/models/export_models.py
  backend/models/session_models.py

Agent Readiness
  backend/agents/interfaces.py
```

## Refactored File Tree

```text
backend/
  agents/
  api/
  core/
  docs/
  models/
  services/
    openai/
    scrapers/
    security/
  workers/
frontend/ui/
  components/
  hooks/
  pages/
  services/
  utils/
```

## Security Audit Summary

- Added reusable SSRF guard in `backend/services/security/url_guard.py`.
- Blocked URL targets:
  - `localhost`
  - `127.0.0.0/8`
  - `10.0.0.0/8`
  - `172.16.0.0/12`
  - `192.168.0.0/16`
  - `169.254.0.0/16`
  - `::1`
- Integrated URL validation before:
  - PDF downloads
  - Scrape.do fetches
  - Scrapling fetches
  - Per-result scrape execution
- Remaining audit target:
  - Any future service that fetches remote URLs outside the shared scraper path should call `assert_public_url()` before network access.

## Technical Debt Summary

- `backend/api/routes.py` is now a router aggregator instead of a monolith.
- API behavior is preserved through compatibility routing around `backend/api/analyze.py`.
- `backend/services/scraper_service.py`, `backend/services/openai_service.py`, and `backend/models/response_models.py` now act as compatibility facades over decomposed module trees.
- Frontend polling logic is split into dedicated hook and service modules while the visual UI remains unchanged.

## Exception Handling Audit

- Broad exception handlers still exist in legacy-compatible orchestration files, especially:
  - `backend/api/analyze.py`
  - `backend/services/scrapers/core.py`
  - `backend/services/openai/core.py`
- The new hardening layer avoids adding new silent `except Exception` patterns in security, routing, confidence, contradiction, and agent-readiness files.
- Recommended next pass:
  - narrow request parsing to `JSONDecodeError`, `ValueError`, and `HTTPException`
  - narrow network failures to `httpx.HTTPError`, `TimeoutError`, and provider-specific runtime failures
  - narrow Redis failures to redis exception classes once the repo standardizes them

## Migration Notes

- Existing imports from:
  - `services.scraper_service`
  - `services.openai_service`
  - `models.response_models`
  remain valid.
- Existing endpoint URLs remain unchanged.
- Worker, Redis queue, and job polling contracts remain unchanged.
- Render deployment now continues using the same API and worker startup shape introduced in the prior phase.

## Remaining High-Risk Areas

- `backend/api/analyze.py` still contains the largest concentration of orchestration logic and is the next candidate for deeper internal extraction.
- `backend/services/scrapers/core.py` and `backend/services/openai/core.py` preserve behavior exactly, but they still contain dense compatibility logic that should be gradually reduced behind the new module boundaries.
- Full live end-to-end validation with Redis, OpenAI, scraping providers, and frontend polling should be run before production rollout.
