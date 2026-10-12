# Deployment Guide

## 1. Single server with Docker Compose (VPS, OCI, AWS EC2/Lightsail, Azure VM)

Minimum for one club: 2 vCPU, 4 GB RAM, 40 GB SSD, Ubuntu 22.04+ with Docker Engine + Compose plugin.

```bash
git clone <repo> ranu && cd ranu
cp .env.example .env
#   set: POSTGRES_PASSWORD, JWT_SECRET (48+ random chars), PUBLIC_BASE_URL, CORS_ORIGINS,
#        PAYMENT_PROVIDER + keys + PAYMENT_WEBHOOK_SECRET, WhatsApp/SMS/SMTP (optional)
docker compose up -d --build db redis
docker compose run --rm migrate                   # alembic upgrade head + reference data (roles/permissions)
docker compose run --rm api python -m app.seed --demo   # OPTIONAL demo data (skip in real production)
docker compose up -d                              # api, worker, web, nginx
curl -s localhost/ready                           # {"status":"ready",...}
```
Create your real owner account (and the first branch) on a fresh production database:
```bash
docker compose run --rm api python -m app.create_admin --username owner --name "Club Owner" \
    --branch-code MAIN --branch-name "RANU Snookers – Main"     # prompts for the password
```
Then sign in, add tables / game types / staff from the admin app. If you loaded demo data, disable the demo accounts.

Services: `nginx` (port 80) → `web` (React static) and `api` (FastAPI, 2 workers); `worker` (background jobs);
`db` (PostgreSQL 16, volume `pgdata`); `redis` (AOF). The API image never runs migrations on boot — the
deploy step does, so a bad migration cannot crash-loop the app.

### TLS / Cloudflare
* Easiest: put the domain behind **Cloudflare** (proxy on, SSL "Full (strict)") with an origin certificate on Nginx, and enable the `set_real_ip_from` lines in `infrastructure/nginx/nginx.conf`.
* Or terminate TLS on the host with Caddy/Certbot in front of port 80.
* Set `COOKIE_SECURE=true` and HTTPS `PUBLIC_BASE_URL`/`CORS_ORIGINS` in production.
* Cloudflare must allow WebSockets (enabled by default).

### Payment webhooks
Razorpay dashboard → Webhooks → URL `https://<domain>/api/v1/payments/webhooks/razorpay`, events
`payment.captured`, `payment.failed`, `order.paid`, secret = `PAYMENT_WEBHOOK_SECRET`.
Stripe → `…/webhooks/stripe`, events `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`.

## 2. Using MySQL instead of PostgreSQL
```bash
docker compose -f docker-compose.yml -f infrastructure/docker/docker-compose.mysql.yml up -d
```
The app sets READ COMMITTED isolation and uses row locks + unique keys, so behaviour matches PostgreSQL
(the full test-suite and concurrency tests pass on both). The PostgreSQL-only exclusion constraint is simply skipped.

## 3. Managed cloud services
| Cloud | App | Database | Redis | Object storage |
|-------|-----|----------|-------|----------------|
| OCI | Compute VM or OKE | OCI Database with PostgreSQL / MySQL HeatWave | OCI Cache | Object Storage (S3 API) |
| AWS | EC2 / ECS Fargate | RDS PostgreSQL / Aurora | ElastiCache | S3 |
| Azure | VM / Container Apps | Azure Database for PostgreSQL Flexible | Azure Cache for Redis | Blob (S3 gateway) |
Point `DATABASE_URL`/`REDIS_URL` at the managed services and remove `db`/`redis` from compose.
Nothing in the code is cloud-specific.

## 4. Scaling
* API is stateless: run several `api` replicas behind Nginx/LB. WebSocket fan-out works across replicas through Redis pub/sub; rate limits and job locks also use Redis.
* Keep **one or more** `worker` replicas — jobs take a Redis lock, so duplicates are safe.
* Kubernetes later: one Deployment per `api`, `worker`, `web`; a Job for migrations; readiness probe `/ready`, liveness `/health`.

## 5. Releases, migrations and rollback
* CI (`.github/workflows/ci.yml`): lint → type check → backend tests (SQLite, PostgreSQL via migrations, MySQL) → frontend tests → build → Docker build.
* CD (`deploy.yml`): after green CI on `main` → **scan migrations for DROP/DELETE** (requires manual approval environment) → build/push images → **pg_dump backup** → `migrate` → roll out → poll `/ready` → roll back app containers if unhealthy.
* Migrations are additive by policy (expand/contract). `alembic downgrade -1` exists for every revision but restoring the pre-deploy dump is the safe path for data changes.

## 6. Backups & maintenance
* Nightly: `docker compose exec -T db pg_dump -U ranu ranu | gzip > backups/ranu-$(date +%F).sql.gz` → copy to object storage; keep 30 days; test restore monthly.
* Redis holds no business data (safe to lose).
* Device heartbeats older than 7 days are pruned automatically.
* Monitor: `/ready`, `/metrics`, container restarts, disk, and the dashboard's device/alert tiles.

## 7. In-club hardware network
Put the Raspberry Pi gateway / ESP32s on a separate Wi-Fi SSID/VLAN. They only need outbound HTTPS to
your domain. The gateway queues events if the internet drops. Keep the counter tablet on a UPS.
