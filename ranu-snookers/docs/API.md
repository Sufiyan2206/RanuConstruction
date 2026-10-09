# API Reference (overview)

* Interactive docs: **`/api/docs`** (Swagger) and **`/api/redoc`**; machine-readable spec: `docs/openapi.json` (151 endpoints).
* Base path: `/api/v1`. JSON everywhere. Money = decimal strings (`"187.50"`). Times = ISO-8601 UTC (send any offset, e.g. `+05:30`).

## Authentication
| Call | Notes |
|------|-------|
| `POST /auth/login {identifier, password}` | identifier = username, email or phone. Returns `access_token` (15 min) + `refresh_token`; also sets httpOnly cookie `ranu_refresh`. |
| `POST /auth/pin-login {username, pin}` | Counter quick login. |
| `POST /auth/register` | Customer self-registration. |
| `POST /auth/refresh` | Uses cookie or `{refresh_token}`. Rotates; reusing an old token revokes the session family (`REFRESH_REUSED`). |
| `GET /auth/me` | User, roles, flattened permissions, branch scope. |

Send `Authorization: Bearer <access_token>`. Permissions (e.g. `sessions.operate`) are checked per branch.

## Errors
```json
{"error": {"code": "BOOKING_CONFLICT", "message": "Sorry, this table was just booked…", "details": null, "request_id": "5f2c…"}}
```
Common codes: `VALIDATION_ERROR` 422, `UNAUTHORIZED`/`TOKEN_EXPIRED` 401, `FORBIDDEN` 403, `NOT_FOUND` 404,
`BOOKING_CONFLICT`, `SESSION_ALREADY_ACTIVE`, `TABLE_RESERVED`, `EXTENSION_UNAVAILABLE`, `INVALID_STATE_TRANSITION`,
`OUT_OF_STOCK`, `OVERPAYMENT` (409/422), `RATE_LIMITED` 429.

## Pagination
List endpoints accept `?page=1&size=25` (max 200) and return `{items, total, page, size}`. Filters are query params (`status=CONFIRMED,CHECKED_IN`, `from`, `to`, `q`).

## Idempotency
* `POST /invoices/{id}/pay` — send `Idempotency-Key: <uuid>`; replays do not double-charge.
* Device events — `event_id` unique per device.
* Payment webhooks — unique `(provider, event_id)`.

## Public (customer website)
```
GET  /public/branches · /public/game-types · /public/branches/{id}/tables · /public/membership-plans
GET  /public/availability?branch_id&start_at&duration_minutes&game_type_id
GET  /public/timeline?branch_id&day=YYYY-MM-DD[&game_type_id]
POST /public/bookings/hold   {branch_id, table_id, start_at, duration_minutes, customer:{name,phone,email}, coupon_code?}
POST /public/bookings/lookup {reference, phone}
GET  /public/qr/{token}      POST /public/qr/{token}/start {name?, phone?}
```
Hold response: `{booking, payment_id, checkout}` where `checkout` is what the provider widget needs
(`mode: razorpay|stripe|mock`, key, order id…). The booking becomes `CONFIRMED` only through the webhook.

## Payment webhooks
`POST /payments/webhooks/{provider}` — Razorpay (`X-Razorpay-Signature`), Stripe (`Stripe-Signature`), mock (`X-Mock-Signature`), all HMAC-SHA256 with `PAYMENT_WEBHOOK_SECRET`. Always returns 200 for processed/duplicate events.

## Staff operations (selection)
```
POST /sessions/start {table_id, customer_id?|customer?, booking_id?, planned_minutes?, override_reservation?}
POST /sessions/{id}/pause|resume|stop|cancel|extend|adjust     GET /sessions/{id}/live
POST /bookings (phone booking) · /bookings/{id}/check-in|no-show|cancel|reschedule
POST /invoices/{id}/pay {splits:[{method, amount, reference?}]} · /discount · /adjustments · /void
POST /sessions/{id}/order/items · /pos/sales · /order-items/{id}/cancel
POST /inventory/stock-in · /inventory/stock-out    GET /branches/{id}/inventory/ledger
POST /memberships · /memberships/{id}/renew|card|adjust-minutes|status
GET  /branches/{id}/dashboard · /board · /reports/{revenue|utilization|peak-hours|games|payments|customers|products}
```

## Device API (hardware)
Headers: `X-Device-Id: TABLE4_SENSOR`, `X-Device-Key: rdk_…` (issued at registration, stored hashed).
```http
POST /api/v1/devices/ingest/events
{"event_id":"b1f0…","event":"ACTIVITY_DETECTED","timestamp":"2026-09-23T18:02:15Z","table_id":4}
# or a batch: {"events":[ … up to 500 … ]}
→ {"results":[{"event_id":"b1f0…","outcome":"ACTIVITY_RECORDED","state":"ACTIVITY_DETECTED","score":0.35,"reason":"…"}]}

POST /api/v1/devices/ingest/heartbeat
{"firmware_version":"1.2.0","uptime_seconds":3600,"queue_depth":0}
```
Event names: `ACTIVITY_DETECTED, MOTION, PRESSURE, BEAM_BREAK, VIBRATION, BALL_STRIKE` (sensors) ·
`CARD_TAP{card_uid}` (RFID/NFC) · `GAME_ACTIVITY{confidence}`, `PEOPLE_DETECTED`, `NO_ACTIVITY` (camera) ·
`START_REQUEST`, `STOP_REQUEST` (table controller). Outcomes: `ACTIVITY_RECORDED, SESSION_STARTED, SESSION_ALREADY_ACTIVE,
AWAITING_STAFF_CONFIRMATION, GAME_ACTIVITY_CONFIRMED_AWAITING_STAFF, IGNORED_STALE, DUPLICATE, AUTO_START_BLOCKED`.

## WebSockets
* Staff: `wss://host/api/v1/ws/branches/{branch_id}?token=<access token>`
* Public (no customer data): `wss://host/api/v1/ws/public/branches/{branch_id}`

Messages: `{"type": "table.status" | "availability.changed" | "session.started" | "session.stopped" | "session.paused" |
"invoice.issued" | "invoice.paid" | "booking.confirmed" | "alert.created" | "device.status" | "detection.updated" | "approval.requested", "data": {…}}`.
Send `"ping"` every ~25 s (server answers `"pong"`). After reconnect, refetch — the stream is a change signal, the REST API is the source of truth.
