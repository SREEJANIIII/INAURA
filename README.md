# INAURA
**Bridging skills to industry.**

Student career-readiness platform — React/Vite frontend + FastAPI backend.

## Architecture (Target)

```
React/Vite frontend
        ↓
FastAPI REST API (/api/v1)
        ↓
Data / Analysis Services
        ↓
RAG + Industry Knowledge (future)
        ↓
Skill Scoring Engine (deterministic, future)
        ↓
Career Recommendation (future)
        ↓
Personalized Roadmap (future)
        ↓
Progress Tracking (future)
```

## Project Structure

```
Inaura/
├── frontend/          # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/  # api.ts, healthService etc.
│   │   └── ...
│   └── vite.config.ts # proxy /api -> FastAPI
└── backend/           # FastAPI + Python
    ├── app/
    │   ├── main.py    # entrypoint
    │   └── api/
    └── requirements.txt
```

## Prerequisites

- Node.js >= 18, npm >= 9
- Python >= 3.10, pip

## Running Locally

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
# Windows PowerShell
.\venv\Scripts\Activate.ps1
# or cmd: venv\Scripts\activate.bat
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: http://localhost:8000/api/v1/health
Docs: http://localhost:8000/docs

### Frontend (Vite)

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173
Configure backend URL via env:

```bash
# frontend/.env
VITE_API_URL=http://localhost:8000/api/v1
```

Vite dev proxy also forwards `/api` to `http://localhost:8000` for local dev without CORS.

## Verification (Phase 0/1)

1. Backend health: `curl http://localhost:8000/api/v1/health`
2. Frontend: Home page has "Check Backend Connection" button — should show `ok` when backend is running.
3. Frontend build: `npm run build`
4. Backend check: `python -m py_compile app/main.py` or `pytest` when tests exist.

## Current Phase

- [x] Phase 0 — Skeleton fixed (main.py, requirements, git, README, title)
- [x] Phase 1 — Frontend ↔ Backend connection (api service, CORS, proxy, Home shell)
- [ ] Phase 2 — Scoring engine (next)
- [ ] RAG / Recommendation / Roadmap / Auth / DB — deferred
