# RANU Club Management Platform

Complete web application for **RANU Snookers**: online table booking with deposits, live table status,
automatic game detection (QR · RFID/NFC · sensors · camera · hybrid), time-based billing, POS & inventory,
memberships, CRM & dues, loyalty, tournaments, cash shifts & expenses, reports, audit — multi-branch.

| | |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 — PostgreSQL (primary) or MySQL 8 — Redis |
| Frontend | React 19, TypeScript, Vite, Tailwind 4, React Router, TanStack Query, React Hook Form + Zod, WebSockets |
| Hardware | Raspberry Pi gateway (offline queue), ESP32 sensor sketch, edge-CV camera script, simulator |
| Deploy | Docker Compose (Nginx + API + worker + web + Postgres + Redis), GitHub Actions CI/CD |

## Quick start (development)
```bash
# 1) backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite:///./dev.db RUN_EMBEDDED_WORKER=true     # or a PostgreSQL URL
alembic upgrade head && python -m app.seed --demo
uvicorn app.main:app --reload --port 8000        # API docs → http://localhost:8000/api/docs

# 2) frontend
cd frontend && npm install && npm run dev        # → http://localhost:5173
```
Demo users (password **`Ranu@12345`**): `superadmin`, `admin` (PIN 7860), `manager` (4321), `reception` (1234), `staff1` (1111).
Customer site: `/` and `/book` · Staff app: `/admin` · Table QR: `/t/<token>`.

## Production (single server)
```bash
cp .env.example .env         # fill secrets
docker compose up -d --build db redis && docker compose run --rm migrate
docker compose run --rm api python -m app.create_admin --username owner --name "Owner" --branch-code MAIN --branch-name "RANU Snookers"
docker compose up -d
```
Full guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation
| Document | For |
|----------|-----|
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | Customers, receptionists, managers, admins — step by step |
| [docs/HARDWARE_DETECTION.md](docs/HARDWARE_DETECTION.md) | The detection options (card, QR, sensors, camera, controller, hybrid), costs, install, tuning |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data model, guarantees, flows |
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Setup, conventions, extension recipes, testing |
| [docs/API.md](docs/API.md) + [docs/openapi.json](docs/openapi.json) | REST, WebSocket, device and webhook APIs |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, cloud, TLS, backups, CI/CD, rollback |
| [docs/SPEC_TRACEABILITY.md](docs/SPEC_TRACEABILITY.md) | Every spec section → code → test; legacy app feature mapping |

## Repository layout
```
backend/        FastAPI app (api, core, models, schemas, services, devices, payments, notifications, workers), migrations, tests
frontend/       React app (components, pages, layouts, hooks, services, stores, types, test)
hardware/       gateway/ (Raspberry Pi), esp32/, camera/ (edge CV), simulator/
infrastructure/ nginx/, docker/ (MySQL override)
.github/        workflows/ci.yml, deploy.yml  (also in infrastructure/github-workflows/ — copy them into .github/workflows/ when you create the Git repo)
docs/           manuals and technical documentation
```

## Quality gates (at delivery)
* Backend: **86 tests** pass on SQLite, **PostgreSQL 16** (schema built by Alembic, incl. exclusion constraint) and **MariaDB 10.11**; concurrency race tests pass on PG and MySQL; `ruff` clean; `alembic check` clean on both databases.
* Frontend: `eslint`, `tsc` clean; 6 component/flow tests; production build OK; end-to-end browser run (book → pay deposit → confirm; staff login → start → stop → bill → collect).
