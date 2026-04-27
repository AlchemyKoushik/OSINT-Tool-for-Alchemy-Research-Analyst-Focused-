# OSINT Tool for Alchemy Research Analysts

A deployment-ready monorepo for an analyst-focused OSINT research workflow.

## Structure

```text
.
├── backend/
│   ├── api/
│   ├── config/
│   ├── data/
│   ├── models/
│   ├── services/
│   ├── utils/
│   ├── main.py
│   ├── requirements.txt
│   ├── Procfile
│   └── render.yaml
└── frontend/
    ├── index.html
    ├── styles.css
    ├── vercel.json
    └── ui/
        ├── app.js
        ├── launch-button.css
        ├── pencil-loader.css
        └── pencil-loader.html
```

## Stack

- Backend: FastAPI, deployable on Render
- Frontend: static HTML/CSS/JS, deployable on Vercel
- UI: restored analyst-facing interface with the original Atelier experience

## Backend setup

1. Create `backend/.env` with the required local secrets.
2. Install dependencies:

```powershell
cd backend
..\venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Run locally:

```powershell
cd backend
..\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend setup

Open `frontend/index.html` directly for basic local testing, or serve the folder with any static server.

The frontend reads `window.OSINT_API_URL` and defaults to:

- `http://127.0.0.1:8000` on localhost
- `https://YOUR_RENDER_BACKEND_URL` elsewhere

Before production deploy, replace the placeholder backend URL in `frontend/index.html`.

## API routes

- `GET /health`
- `GET /api/locations`
- `POST /api/research`
- `POST /api/analyze`
- `POST /api/analyze-existing`
- `POST /api/follow-up`
- `POST /api/feedback`

## Deployment

### Render

- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Vercel

- Root directory: `frontend`
- Framework preset: `Other`

## Notes

- `research_artifacts/`, `venv/`, local `.env` files, and generated cache files are intentionally excluded from git.
