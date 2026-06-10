# Production Deployment for Hostinger VPS + Coolify

## Placement

- `backend/Dockerfile`: backend and worker image
- `backend/.dockerignore`: backend build context exclusions
- `backend/scripts/worker_healthcheck.py`: worker liveness check
- `frontend/Dockerfile`: frontend image
- `frontend/.dockerignore`: frontend build context exclusions
- `frontend/nginx/default.conf`: frontend static server config
- `frontend/docker-entrypoint.d/40-render-config.sh`: runtime frontend config renderer
- `docker-compose.yml`: single-VPS production stack
- `.env.production.example`: production env template
- `deploy/nginx/nginx.conf`: edge reverse proxy
- `deploy/redis/redis.conf`: Redis persistence and memory policy

## How it runs

- `nginx`: public entrypoint on port `80`
- `frontend`: static UI container on port `8080` inside Docker
- `backend`: FastAPI on port `8000` inside Docker
- `worker`: background research worker using the same backend image
- `redis`: queue/session/cache store

## Coolify recommendations

1. Use a Docker Compose application, not four separate apps.
2. Expose only the `nginx` service publicly.
3. Store secrets in Coolify environment variables, not in the repo.
4. Add a persistent volume for `redis-data`.
5. Keep `USE_CRAWL4AI=false` unless you confirm the VPS still has enough memory under load.
6. Start with one worker only on a `4 vCPU / 16 GB` VPS.
7. Watch `GET /metrics` and queue growth before increasing worker count.

## Suggested production env values on this VPS

- `USE_CRAWL4AI=false`
- `COMPARE_CRAWLERS=false`
- `JOB_MAX_RETRIES=2` or `3`
- `STATIC_ASSET_VERSION` set to your release tag or commit SHA
- `OSINT_PUBLIC_API_URL` blank if Nginx serves frontend and backend on the same domain

## Deploy steps

1. Copy `.env.production.example` to `.env.production`.
2. Fill in all required secrets.
3. In Coolify, create a Docker Compose application from this repo.
4. Set the compose file to `docker-compose.yml`.
5. Attach the domain to the `nginx` service and expose container port `80` through Coolify.
6. Deploy.

## Notes

- The frontend does not need a separate public domain when Nginx fronts both app layers.
- Do not publish `80:80` in Compose on Coolify-managed hosts because Coolify already owns ports `80/443`.
- The worker health check uses a heartbeat file updated in `backend/workers/worker.py`.
- Backend startup still validates required secrets, Redis, OpenAI, and DDG availability.
