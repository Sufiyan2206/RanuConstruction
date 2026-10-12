"""Test fixtures.

By default tests run on a throw-away SQLite file. Set TEST_DATABASE_URL to run
the same suite against PostgreSQL or MySQL (CI does PostgreSQL):

    TEST_DATABASE_URL=postgresql+psycopg://ranu:ranu@localhost/ranu_test pytest
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ.pop("REDIS_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core import timeutil  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Branch, Table  # noqa: E402
from app.seed import DEMO_PASSWORD, ensure_org, seed_demo, seed_reference  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _reset_schema() -> None:
    if engine.dialect.name == "sqlite":
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            for t in reversed(Base.metadata.sorted_tables):
                cur.execute(f'DROP TABLE IF EXISTS "{t.name}"')
            raw.commit()
        finally:
            raw.close()
    elif engine.dialect.name == "postgresql":
        from sqlalchemy import text

        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    else:
        from sqlalchemy import text

        with engine.begin() as c:
            c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for t in reversed(Base.metadata.sorted_tables):
                c.execute(text(f"DROP TABLE IF EXISTS `{t.name}`"))
            c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    if os.environ.get("TEST_USE_MIGRATIONS") == "1":
        # Build the schema exactly as production does (incl. PostgreSQL-only constraints).
        from alembic import command
        from alembic.config import Config

        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
        command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)


@pytest.fixture()
def seeded():
    """Fresh schema + demo data for every test (tests are fully isolated)."""
    timeutil.freeze(None)
    _reset_schema()
    with SessionLocal() as db:
        org = ensure_org(db)
        seed_reference(db, org)
        info = seed_demo(db, org)
        db.commit()
    yield info
    timeutil.freeze(None)


@pytest.fixture()
def db(seeded):
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(seeded):
    with TestClient(app) as c:
        yield c


class Api:
    def __init__(self, client: TestClient, token: str | None = None):
        self.c = client
        self.token = token

    def _h(self, extra=None):
        h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        h.update(extra or {})
        return h

    def get(self, url, **kw):
        return self.c.get(f"/api/v1{url}", headers=self._h(kw.pop("headers", None)), **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(f"/api/v1{url}", json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(f"/api/v1{url}", json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(f"/api/v1{url}", json=json, headers=self._h(kw.pop("headers", None)), **kw)


def login(client: TestClient, username: str) -> Api:
    r = client.post("/api/v1/auth/login", json={"identifier": username, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return Api(client, r.json()["access_token"])


@pytest.fixture()
def admin(client):
    return login(client, "admin")


@pytest.fixture()
def reception(client):
    return login(client, "reception")


@pytest.fixture()
def staff(client):
    return login(client, "staff1")


@pytest.fixture()
def public(client):
    return Api(client)


@pytest.fixture()
def branch_id(db):
    return str(db.scalar(select(Branch.id)))


def table_id(db, number: int) -> str:
    return str(db.scalar(select(Table.id).where(Table.table_number == number)))


def local_dt(days_ahead: int, hour: int, minute: int = 0) -> datetime:
    base = datetime.now(IST).replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    return base


def freeze_at(dt: datetime) -> None:
    timeutil.freeze(dt)


def advance(minutes: float) -> None:
    timeutil.freeze(timeutil.utcnow() + timedelta(minutes=minutes))
