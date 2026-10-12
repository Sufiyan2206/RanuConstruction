# Developer Guide

## 1. Local setup (no Docker)

Prerequisites: Python 3.11+, Node 20+, PostgreSQL 14+ (or MySQL 8 / SQLite for quick hacking), Redis (optional).

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://ranu:ranu@localhost/ranu     # or sqlite:///./dev.db
export RUN_EMBEDDED_WORKER=true                                        # run jobs inside the API for dev
alembic upgrade head
python -m app.seed --demo        # prints demo device keys
uvicorn app.main:app --reload --port 8000     # Swagger UI: http://localhost:8000/api/docs

# frontend (new terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173 (proxies /api and WebSockets to :8000)
```

Demo logins (password `Ranu@12345`): `superadmin`, `admin` (PIN 7860), `manager` (4321), `reception` (1234), `staff1` (1111).
`PAYMENT_PROVIDER=mock` (default) shows a "Pay deposit (demo)" button that triggers a signed mock webhook.

## 2. Project layout
```
backend/app/api/v1        thin routers        backend/app/services   business logic
backend/app/models        SQLAlchemy models   backend/app/schemas    Pydantic contracts & settings
backend/app/core          config/security/db  backend/app/devices    detection providers
backend/app/payments      payment providers   backend/app/notifications channel providers
backend/app/workers       scheduler           backend/migrations     Alembic
frontend/src/{components,pages,layouts,hooks,services,stores,types,lib,test}
hardware/{gateway,camera,esp32,simulator}      infrastructure/{nginx,docker}
```

## 3. Rules we follow (spec §56 in practice)
* Route handler = validate → one service call → response model. Put logic in `services/`.
* Every mutating service: `actor.require(permission, branch_id)` → change → `audit(...)` → `db.commit()` → `events.flush()`.
* Money: `Decimal` + `Numeric(12,2)`; round with `pricing.q()`; never floats.
* Financial rows are append-only. Corrections are new rows (adjustment, refund, reversal).
* Time: store UTC (`UTCDateTime`), convert with `to_local(dt, branch.timezone)` at the business boundary; use `timeutil.utcnow()` (freezable in tests).
* Locks: `for_update(select(...), db)` — the helper chooses the right SQL per dialect.
* No hard-coded prices, branch ids, roles: prices → tables/pricing rules/settings; roles → DB; checks use permissions.
* Real-time: add events to a `PendingEvents` inside the transaction; flush after commit.

## 4. Common extension recipes
**New payment provider:** implement `create_order`, `verify_webhook`, `refund` in `app/payments/providers.py`, add to `_PROVIDERS`, set `PAYMENT_PROVIDER`. Webhook URL: `POST /api/v1/payments/webhooks/<name>`.

**New detection hardware:** add a provider class in `app/devices/providers/builtin.py` mapping raw events → `Signal`; register in `provider_for`; add a weight under `DetectionSettings.weights`. See `docs/HARDWARE_DETECTION.md` §6.

**New notification channel:** implement `send()` in `app/notifications/providers.py`, return it from `get_channel_provider`, add the channel to `NotificationSettings.channels`. Templates can be overridden per event/channel in `notification_templates`.

**New setting:** add a typed field with a default to a model in `app/schemas/settings.py` — it is stored in `branches.settings` JSON, validated on every update and appears automatically in Admin → Settings.

**Schema change:** edit models → `alembic revision --autogenerate -m "..."` → review (portable types, no data loss) → `alembic upgrade head` → `alembic check` must say "No new upgrade operations". Never ship destructive changes without a two-step (expand → migrate data → contract) plan; CI's deploy guard requires manual approval for DROP/DELETE migrations.

## 5. Testing
```bash
cd backend
pytest -q                                            # SQLite (fast)
TEST_DATABASE_URL=postgresql+psycopg://ranu:ranu@localhost/ranu_test TEST_USE_MIGRATIONS=1 pytest -q
TEST_DATABASE_URL="mysql+pymysql://ranu:ranu@localhost/ranu_test?charset=utf8mb4" pytest -q
ruff check app tests

cd frontend
npm run lint && npm run typecheck && npm test && npm run build
```
| Suite | File | Covers |
|-------|------|--------|
| Unit | `tests/test_pricing_unit.py` | pricing rules, happy-hour split, midnight windows, rounding, membership cover, deposits, tax |
| Unit | `tests/test_state_and_detection_unit.py` | session state machine, detection fusion rules, providers |
| Integration/API | `tests/test_booking_flow.py` | availability, holds, conflicts, expiry, late payment, webhook idempotency/signature, cancellation policy, reschedule, no-show, self-service |
| Integration/API | `tests/test_sessions_billing.py` | walk-in billing, split pay, pause, POS + inventory ledger, credit dues, deposit applied, reserved-table protection, extension, membership + void reversal, approvals, RBAC, audit, shift cash, refresh-token rotation, lockout, reports |
| Integration | `tests/test_devices_detection.py` | device API, RFID start, hybrid auto-start, spoofing, stale/future events, offline, gateway batches, QR, simulator, inactivity, tournaments |
| Concurrency | `tests/test_concurrency.py` | 10 parallel bookings → 1 winner; 5 parallel starts → 1 session (PG/MySQL) |
| Frontend | `frontend/src/test/app.test.tsx` | login, booking flow, checkout, table dashboard card, validation, formatting |

Test results at delivery: **86 backend tests passing on SQLite, PostgreSQL 16 (migration-built schema) and MariaDB 10.11**; 6 frontend tests passing; ruff, eslint and `tsc` clean; production build OK.

## 6. Observability
JSON logs with `request_id` (also returned as `X-Request-ID` and inside every error body); `/health` (liveness),
`/ready` (DB + Redis), `/metrics` (Prometheus text). Plug Sentry/OTel into `app/main.py` if needed.
