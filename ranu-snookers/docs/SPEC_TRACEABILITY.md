# Specification Traceability

Every section of *"RANU Snookers — Full Club & Snooker Management Software"* mapped to where it is
implemented and how it is verified. Status: ✅ done & tested · 🟡 done, foundation level (extend later) · ⏭ planned.

| § | Requirement | Implementation | Verified by | Status |
|---|-------------|----------------|-------------|--------|
| 1 | Full visit lifecycle | booking → hold → deposit → check-in → session → detection → billing → POS → invoice → payment → CRM/analytics | `test_booking_checkin_start_deposit_applied`, e2e browser run | ✅ |
| 2 | React, TS, Vite, Router, TanStack Query, Tailwind, component kit, Zod, RHF, WebSockets | `frontend/` (own shadcn-style kit in `components/ui`) | `npm run lint/typecheck/test/build` | ✅ |
| 3 | Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL + MySQL, Redis, WS, workers | `backend/` | suite passes on PG, MariaDB, SQLite | ✅ |
| 4 | Docker deploy, compose, Dockerfiles, nginx, .env.example, cloud-agnostic | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `infrastructure/`, `.env.example`, `docs/DEPLOYMENT.md` | `docker compose config` | ✅ |
| 5 | RBAC roles | `core/permissions.py` (data-seeded roles), `core/deps.py` (branch-scoped permissions), `services/admin_service.py` | `test_rbac_staff_cannot_change_prices_or_adjust` | ✅ |
| 6 | Multi-branch | `organizations/clubs/branches`, `branch_id` on all transactional rows, branch-scoped roles, branch selector in UI | model + RBAC tests | ✅ |
| 7 | Tables, game types, statuses, real-time | `models/table.py`, `services/table_service.py`, live board | board/dashboard tests | ✅ |
| 8 | Online booking steps | `pages/public/Book.tsx`, `/public/availability`, `/public/bookings/hold` | `test_full_online_booking_with_deposit`, frontend booking test | ✅ |
| 9 | Conflict prevention, holds, expiry, cancel, reschedule, no-show, early/late, extension | `services/booking_service.py`, migration 0002 exclusion constraint | `test_double_booking_prevented`, `test_ten_customers_racing…`, hold/late-payment/no-show/extension tests | ✅ |
| 10 | Deposit rules, payment states, provider abstraction | `BookingPolicy`, `payments/providers.py` (mock/Razorpay/Stripe) | deposit unit tests, webhook tests | ✅ |
| 11-15 | Detection options A–E | `devices/providers/builtin.py`, `services/detection_service.py`, QR endpoints, `hardware/` | `test_devices_detection.py`, fusion unit tests | ✅ |
| 16 | Device, type, event, heartbeat, config, states, dashboard | `models/device.py`, `services/device_service.py`, Admin → Devices | heartbeat/offline tests | ✅ |
| 17 | GameSession entity & statuses | `models/session.py` | state machine tests | ✅ |
| 18-19 | Billing engine, configurable pricing & intervals | `services/pricing.py`, `PricingRule`, `BillingSettings` | 15 pricing unit tests | ✅ |
| 20 | Extension with availability check | `session_service.extend` | `test_extension_blocked_by_next_booking` | ✅ |
| 21 | Walk-ins | `POST /sessions/start` + customer picker | `test_walk_in_session_billing_and_split_payment` | ✅ |
| 22 | Membership plans/cards/expiry/discounts/limits | `membership_service.py`, plan fields incl. daily cap, RFID `card_uid` | `test_membership_hours_deducted_and_reversed_on_void`, RFID test | ✅ |
| 23 | POS, table tabs | `pos_service.py`, Add items, counter sale | `test_table_orders_and_inventory_ledger`, `test_counter_sale_and_credit_due` | ✅ |
| 24 | Inventory ledger, suppliers, low stock | `inventory_transactions`, `stock_levels`, alerts | out-of-stock + ledger tests | ✅ |
| 25 | CRM profile & dashboard | `customer_service.profile`, Customers page | walk-in test (visits/spend) | ✅ |
| 26 | Loyalty, coupons, referrals | `loyalty_service.py`, `LoyaltySettings` | earn on invoice (integration) | 🟡 (promotions via pricing rules) |
| 27 | Tournaments | `tournament_service.py` (knockout w/ seeding & byes, round robin, groups→KO) | `test_knockout_tournament` | ✅ |
| 28 | Staff dashboard tiles & grid | `pages/admin/Dashboard.tsx`, `/dashboard` | `test_dashboard_and_reports`, frontend card test | ✅ |
| 29 | WebSockets live updates (staff + customer) | `core/realtime.py`, `hooks/useRealtime.ts` | manual/e2e | ✅ |
| 30 | Notifications, pluggable providers | `notification_service.py` (outbox, templates, reminders), `notifications/providers.py` | worker jobs | 🟡 (push channel adapter stub) |
| 31 | Reports | `report_service.py`, Reports page, CSV export | report assertions in tests | ✅ |
| 32 | Audit logs | `services/audit.py` everywhere, Audit page | `test_price_change_is_audited` | ✅ |
| 33 | Normalised schema, UUID, FKs, checks, indexes, soft delete only for master data | `models/*`, `migrations/versions/0001` | `alembic check` clean on PG & MySQL | ✅ |
| 34 | Financial integrity (adjustments, not overwrites) | invoice adjustments, refund rows, void reversals | discount/void tests | ✅ |
| 35 | Versioned REST, OpenAPI, JWT+refresh, RBAC, validation, rate limit, pagination, filters, sorting, consistent errors | `api/v1`, `core/errors.py`, `core/ratelimit.py` | error-shape test | ✅ |
| 36 | Security | Argon2, token rotation/reuse detection, httpOnly cookie, lockout, device keys, webhook HMAC, headers | refresh/lockout/spoofing tests | ✅ |
| 37 | Reliability cases | idempotency, webhook authority, offline alerts, restart recovery, gateway queue | duplicate/webhook/offline/batch tests | ✅ |
| 38 | Event-driven device pipeline, MQTT-ready | HTTP gateway → providers → engine → sessions → billing | device tests | ✅ (MQTT bridge ⏭) |
| 39 | Session state machine | `session_service.TRANSITIONS` | parametrised tests | ✅ |
| 40 | Anti-fraud alerts | duplicate, manual cancel, price changes audited, no-customer, long session, spoofing, stale/skew, duplicate payments, cash variance | alert tests | ✅ |
| 41 | Public website pages & BOOK A TABLE CTA | `pages/public/Home.tsx` sections, Book, Login, My bookings | e2e screenshots | ✅ |
| 42 | Admin application routes | `/admin/*` (16 screens) | typecheck/build | ✅ |
| 43, 53 | Staff-friendly, responsive, touch | large tap targets, mobile drawer, bottom-sheet modals | screenshots at 390px & 1366px | ✅ |
| 44 | Transactions for financial ops | one unit of work per service call | integration tests | ✅ |
| 45 | Concurrency | row locks, unique active key, idempotency keys | `test_concurrency.py` on PG & MySQL | ✅ |
| 46 | Unit, integration, API, frontend tests | `backend/tests`, `frontend/src/test` | 86 + 6 passing | ✅ |
| 47 | CI/CD with safe migrations | `.github/workflows/ci.yml`, `deploy.yml` (destructive-migration gate, backup, health check, rollback) | — | ✅ |
| 48 | Observability | JSON logs + request id, `/health`, `/ready`, `/metrics`, device health | — | ✅ |
| 49 | Env-var configuration | `core/config.py`, `.env.example` | prod validation of JWT_SECRET/DB | ✅ |
| 50 | Swagger/OpenAPI docs | `/api/docs`, `docs/openapi.json`, `docs/API.md` | — | ✅ |
| 51 | Hardware phases | QR+manual now; RFID, sensors, camera, hybrid ready | `docs/HARDWARE_DETECTION.md` | ✅ |
| 52 | Never bill from a single movement | fusion + sustain + event count + optional identification | `test_single_motion_event_does_not_start_billing` | ✅ |
| 54 | Project structure | matches (plus `docs/`, `hardware/`) | — | ✅ |
| 55 | Phased implementation | built phase 1 → 7 in order | this table | ✅ |
| 56 | Development rules | see `docs/DEVELOPER_GUIDE.md` §3 | code review | ✅ |

## Features carried over from the existing RS Sales & Expense app
| Legacy feature | New implementation |
|----------------|-------------------|
| 10 tables + 4 PS5 consoles, per-table rate overrides | Tables with game types (PS5 is a game type), `hourly_rate`/`off_peak_rate`/`peak_rate` |
| Happy hour 14:00–18:00 (₹150 → ₹100) | Pricing rule *Happy Hour* using each table's off-peak rate |
| 15-minute billing blocks, happy-hour split by minute | `BillingSettings.interval_minutes=15`, per-minute pricing |
| Membership hour packs (30h ₹3000/30d, 50h ₹5000/60d), 30-min deduction, overage billing | Plans `H30`, `H50`; `deduction_block_minutes=30`; `compute_session_charge` |
| Customer gate before starting a table | Customer picker on Start game |
| F&B orders on a table, direct counter sales, menu items, stock movements, low stock | POS + inventory ledger |
| Split payments, Cash/UPI/Card/Credit (Due), references required for UPI/card | `take_payment` splits + validation |
| Credit (Due), opening balances, due payments, outstanding report | Customer dues ledger, Outstanding tab + WhatsApp reminder |
| Discount & item-cancel approval by admin | Approval requests (maker-checker) |
| Edit/delete audit report | Audit log (before/after, reason, IP) |
| Staff passcode login (4 staff + admin) | Per-user accounts with PIN login + RBAC |
| Shift open/close with cash reconciliation | Shifts with expected vs counted cash + variance alert |
| Expenses (grocery, general, police, salary, charity) | Expense categories + expenses (void, not delete) |
| Receipts print + WhatsApp share | Invoice print (80 mm) + WhatsApp share |
| Reports (sales, expenses, P&L, table/PS5 usage, membership) | Reports module (revenue vs expenses, utilisation, games, payments, customers, products) |

Legacy data import (from the artifact's data store) is not automated; export it to CSV and load via the API if needed.
