Tables are created by **Alembic migrations**. You don't create them by hand. Point the backend at your PostgreSQL database with `DATABASE_URL`, run one command, and it creates all 55 tables, indexes and constraints.

Choose Option A or Option B below; you only need one.

## Option A — PostgreSQL installed on your Windows PC

**1. Create the database and user** (open *SQL Shell (psql)* as the `postgres` user):
```sql
CREATE USER ranu WITH PASSWORD 'StrongPass123';
CREATE DATABASE ranu OWNER ranu;
\c ranu
CREATE EXTENSION IF NOT EXISTS btree_gist;
```
The last line is needed by the migration that blocks double bookings. Only a superuser can create it, which is why it's done here as `postgres`.

**2. Point the backend at the database.** Create a file `ranu-snookers\backend\.env` containing:
```env
DATABASE_URL=postgresql+psycopg://ranu:StrongPass123@localhost:5432/ranu
JWT_SECRET=put-any-long-random-text-here-at-least-32-chars
RUN_EMBEDDED_WORKER=true
```
If your password contains `@ : / #` or `%`, URL-encode it. For example, `@` becomes `%40`.

**3. Install the backend and run the migrations.** In PowerShell:
```powershell
cd "D:\Checklist\Development\KMS Abdul\Projects\RANU Snooker Premium\ranu-snookers\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

alembic upgrade head          # creates all the tables
alembic current               # should print: 0002 (head)
```

**4. Load the starting data.** The empty tables need roles and permissions before anyone can log in. Choose one:
```powershell
python -m app.seed --demo     # testing: demo club, 14 tables, products, users (password Ranu@12345)
# or, for real use:
python -m app.seed
python -m app.create_admin --username owner --name "Club Owner" --branch-code MAIN --branch-name "RANU Snookers - Main"
```

**5. Start the API:**
```powershell
uvicorn app.main:app --port 8000
```
Open http://localhost:8000/ready. It should report `"database":"ok"`.

## Option B — Docker (Postgres runs inside a container)
From the `ranu-snookers` folder:
```powershell
copy .env.example .env        # then set POSTGRES_PASSWORD and JWT_SECRET in .env
docker compose up -d db redis
docker compose run --rm migrate       # runs "alembic upgrade head" + the reference data
docker compose up -d
```

## Checking the tables were created
In psql: `\c ranu` then `\dt`. You should see `bookings`, `game_sessions`, `invoices`, `tables` and the others, plus `alembic_version`.

## Later changes to the database
When the code changes the table structure, you never edit tables by hand:
- Whoever changes the code runs `alembic revision --autogenerate -m "describe change"` to create a new migration file.
- On every computer or server, run `alembic upgrade head` again. It applies only the new changes and keeps your data.

## If something fails
| Error | Fix |
|---|---|
| `permission denied to create extension "btree_gist"` | Run the `CREATE EXTENSION` line from step 1 as `postgres` |
| `password authentication failed` | Check the user and password in `DATABASE_URL` |
| `connection refused` | The PostgreSQL service isn't running, or it's on a different port (5432 is the default) |
| `JWT_SECRET must be set` | Add a JWT_SECRET of at least 32 characters to `.env` |

Once step 5 works, start the website with `npm install` then `npm run dev` inside the `frontend` folder, and open http://localhost:5173.