# Architecture

## 1. System overview

```
                   Customers (mobile web)          Staff (tablet / desktop)
                              │  HTTPS + WSS                 │
                         ┌────▼──────────────────────────────▼────┐
     Cloudflare (opt.) → │ Nginx: TLS, rate limit, /api, /ws, SPA │
                         └────┬───────────────────────┬───────────┘
                              │                       │ static React build
                ┌─────────────▼─────────────┐   ┌─────▼─────┐
                │ FastAPI (N replicas)       │   │  web      │
                │  api/v1 routers (thin)     │   └───────────┘
                │  services (business logic) │◀── device gateway (Pi / ESP32) HTTP, later MQTT bridge
                │  models (SQLAlchemy 2)     │◀── payment provider webhooks (Razorpay / Stripe)
                └──┬───────────┬───────────┬─┘
                   │           │           │ pub/sub fan-out for WebSockets, rate limits, job locks
            ┌──────▼────┐ ┌────▼────┐ ┌────▼──────────┐
            │PostgreSQL │ │  Redis  │ │ Worker process │ holds expiry, no-shows, reserved status,
            │(or MySQL) │ └─────────┘ │ (scheduler)    │ device offline, idle/long session alerts,
            └───────────┘             └────────────────┘ reminders, notification outbox
```

*Modular monolith* (spec §56-28/29): one deployable backend with strict internal layers; any module can
be split into a service later because modules talk through service functions, not shared globals.

## 2. Backend layers

| Layer | Folder | Rule |
|-------|--------|------|
| API | `app/api/v1/*.py` | Parse/validate (Pydantic), call **one** service function, shape the response. No business logic. |
| Schemas | `app/schemas/` | API contracts + validated branch settings (`BranchSettings`). |
| Services | `app/services/` | All business rules, transactions, authorisation re-checks (`actor.require(perm, branch_id)`), audit rows, real-time events. |
| Pure engines | `services/pricing.py`, `detection_service.fuse()` | No I/O — unit-tested in isolation. |
| Models | `app/models/` | Persistence only: columns, constraints, indexes. |
| Core | `app/core/` | config, DB session, security, errors, RBAC deps, realtime hub, rate limit, logging. |
| Devices | `app/devices/providers/` | Pluggable detection providers (RFID/NFC, sensors, camera, controller). |
| Payments | `app/payments/providers.py` | Provider abstraction (mock, Razorpay, Stripe). |
| Notifications | `app/notifications/providers.py` | Email / SMS / WhatsApp / push channel adapters. |
| Workers | `app/workers/scheduler.py` | Idempotent periodic jobs (Redis-locked when several replicas run). |

## 3. Data model (55 tables)

Grouped by domain (all PK are UUID; every transactional table has `branch_id`; timestamps are UTC):

* **Org:** `organizations → clubs → branches` (+ `holidays`, `system_settings`, `document_sequences`)
* **Auth/RBAC:** `users`, `roles`, `permissions`, `role_permissions`, `user_roles` (branch-scoped), `refresh_tokens`
* **CRM:** `customers`, `customer_ledger` (dues), `loyalty_transactions`, `coupons`
* **Tables & pricing:** `game_types`, `tables`, `pricing_rules`, `table_detection_states`
* **Bookings:** `bookings`, `booking_holds`
* **Sessions:** `game_sessions`, `session_events`, `session_pauses`
* **Money:** `invoices`, `invoice_lines`, `invoice_adjustments`, `payments`, `payment_webhook_events`, `idempotency_keys`
* **POS/Inventory:** `product_categories`, `products`, `suppliers`, `stock_levels`, `inventory_transactions`, `orders`, `order_items`
* **Membership:** `membership_plans`, `memberships`, `membership_transactions`
* **Devices:** `devices`, `device_events`, `device_heartbeats`
* **Ops:** `audit_logs`, `alerts`, `approval_requests`, `shifts`, `expense_categories`, `expenses`
* **Tournaments:** `tournaments`, `tournament_players`, `tournament_matches`
* **Notifications:** `notification_templates`, `notifications` (outbox)

Status columns are short strings guarded by CHECK constraints generated from Python enums
(`app/models/enums.py`) — portable across PostgreSQL and MySQL.

## 4. Key guarantees and how they are implemented

| Requirement | Implementation |
|-------------|----------------|
| No double booking (§9, §45) | Booking writes lock the `tables` row (`SELECT … FOR UPDATE`), re-check overlaps, then insert. PostgreSQL adds `EXCLUDE USING gist (table_id =, tstzrange(start,end) &&)` (migration 0002). Proven by a 10-thread race test on PG and MySQL. |
| Holds expire (§9) | `bookings.status = HELD` + `hold_expires_at`; expired holds are ignored by overlap checks immediately and flipped to EXPIRED by the worker/next write. |
| Payment webhook authoritative (§37) | `payment_webhook_events` unique `(provider, event_id)`; the webhook confirms the booking even if the browser crashed; late payment for a lost slot → automatic refund + alert. |
| One open session per table (§45) | Row lock + `game_sessions.active_table_key` UNIQUE (holds table id while open, NULL when closed) — portable alternative to a partial unique index. |
| Duplicate sensor events (§37) | `device_events` UNIQUE `(device_pk, event_id)`; engine returns `SESSION_ALREADY_ACTIVE` for repeated start signals. |
| Server restart (§37) | All state (sessions, pauses, detection state) is in the DB; startup re-derives table statuses. |
| Financial immutability (§34) | Invoice lines never edited after issue; corrections = `invoice_adjustments`; refunds = new negative `payments` rows; voids reverse stock & membership via new ledger rows. |
| Inventory ledger (§24) | `inventory_transactions` append-only + `stock_levels` cache updated under row lock. |
| Backend is source of truth (§56-9/10) | Quotes, availability, live bills and final invoices are computed server-side only. |
| Auditable (§32) | `audit()` is written in the same transaction as the change (before/after JSON, reason, IP, user agent, request id). |
| Real-time (§29) | Services queue events in `PendingEvents`; published only after commit → WebSocket hub (Redis pub/sub across replicas). Clients invalidate the matching React Query caches. |
| Timezones (§56-16) | `UTCDateTime` type stores UTC on every dialect; pricing windows, business days and reports use the branch timezone. |

## 5. Main flows

**Online booking:** `GET /public/availability` → `POST /public/bookings/hold` (HELD, 10-min hold, deposit quote, provider order created *after* commit) →
customer pays → provider webhook → `payment_service.handle_webhook` → `booking_service.on_deposit_paid` → CONFIRMED → WhatsApp/email outbox → WebSocket `availability.changed`.

**Game:** check-in (READY session) → start (manual/QR/RFID/sensor fusion) → pause/resume/extend/add items →
stop → `billing_service.generate_for_session` (per-minute pricing, membership cover, discounts, deposit applied, tax) → pay (split / due) → loyalty + CRM counters.

**Detection:** device → `POST /devices/ingest/events` (key auth, idempotent) → provider → `Signal` → `detection_service.process_signal`
(anti-fraud time checks → state row lock → identification → fusion → `session_service.start(method=HYBRID…)`).

## 6. Pricing engine
`services/pricing.py`: for each billable minute (local time) pick the highest-priority matching `PricingRule`
(scope: table > game type > branch; filters: day type, weekdays, time window incl. over-midnight, date range,
member segment). Rounding (1/5/10/15/30/60-min blocks, UP/NEAREST/DOWN, minimum, grace) happens first; rounded
tail minutes are priced at the rate in force then. Membership minutes are consumed first in plan blocks (30 min).

## 7. Security
Argon2id passwords & PINs; JWT access tokens (15 min) + opaque rotating refresh tokens stored hashed with
**reuse detection** (reuse revokes the whole family); httpOnly SameSite=Strict refresh cookie; account lockout;
permission checks both in route dependencies and inside services; per-device API keys (hashed); signed payment
webhooks; rate limiting (Redis or in-memory) on public/auth endpoints; security headers at Nginx; secrets only from env.

## 8. Frontend
React 19 + TypeScript + Vite + Tailwind 4, React Router 7, TanStack Query 5, React Hook Form + Zod.
`services/` (HTTP client with silent refresh, booking API), `stores/auth.tsx` (session, permissions, branch),
`hooks/useRealtime.ts` (WebSocket → cache invalidation, auto-reconnect), `components/` (UI kit, TableBoard,
InvoicePanel, CustomerPicker), `layouts/` (public site, admin shell), `pages/`. The UI never computes prices.
