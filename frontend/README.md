# CampusOS Frontend

React + TypeScript + Vite client for CampusOS (memberships, events, announcements, admin, merchandise, projects/volunteers, club finance).

## Setup (PowerShell)

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Point `VITE_API_BASE_URL` at the FastAPI host the browser can reach.

## Commands

| Script | Purpose |
| --- | --- |
| `npm run dev` | Dev server |
| `npm run typecheck` | TypeScript check |
| `npm run lint` | Oxlint |
| `npm run gen:api` | Export OpenAPI from backend + regenerate `src/types/openapi.d.ts` |
| `npm run check:api` | Fail if `openapi.json` / types drift (no silent rewrite) |
| `npm run build` | `check:api` then `tsc` + Vite production build |

OpenAPI is generated offline (`python -m app.export_openapi`); no running API/DB required for `gen:api`.

## Phone camera check-in demo

A phone **cannot** open the laptop’s `http://127.0.0.1:5173` address. Use a LAN URL both devices share:

1. Find the laptop LAN IP (e.g. `ipconfig` → `192.168.x.x`).
2. Bind Vite to the LAN interface, e.g. in `vite.config` server `host: true`, or:
   `npm run dev -- --host 0.0.0.0`
3. Set frontend env to the laptop’s LAN API URL:
   `VITE_API_BASE_URL=http://192.168.x.x:8000`
4. Run API with a matching host/CORS origin:
   `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
   and add `http://192.168.x.x:5173` to `CORS_ORIGINS` in `backend/.env`.
5. On the phone (same Wi‑Fi), open `http://192.168.x.x:5173`, log in as Events/Admin, open **Check-in**, allow camera.
6. Prefer HTTPS in real deployments — many mobile browsers restrict camera on insecure origins. For a local demo, some Android Chrome builds still allow `http://192.168…` on the LAN; if the camera is blocked, use manual token entry or tunnel with HTTPS (e.g. Cloudflare Tunnel / ngrok).

Manual token entry always works as a fallback and uses the same check-in API and audit trail. Seed prints a **CampusOS Live Check-in** QR for a reliable first/duplicate scan without window override.
