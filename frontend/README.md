# CampusOS Frontend

React + TypeScript + Vite client for CampusOS (Phase 1: initialization placeholder).

## Setup (PowerShell)

```powershell
cd frontend
Copy-Item .env.example .env
npm install
```

## Commands

| Script | Purpose |
| --- | --- |
| `npm run dev` | Dev server on http://127.0.0.1:5173 |
| `npm run typecheck` | TypeScript project references check |
| `npm run lint` | Oxlint |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |

## Environment

`VITE_API_BASE_URL` — FastAPI base URL (default fallback in code: `http://127.0.0.1:8000`).

HTTP calls are centralized in `src/services/api.ts`. The home screen calls `GET /api/v1/health` and shows loading / connected / unavailable honestly.
