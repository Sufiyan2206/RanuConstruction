"""Database engine / session management.

The ORM layer is written against portable SQLAlchemy types so the same code
runs on PostgreSQL (primary), MySQL 8 / MariaDB (InnoDB) and SQLite (tests).
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING_CONVENTION


def build_engine(url: str) -> Engine:
    kwargs: dict = {"echo": settings.DB_ECHO, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW, pool_pre_ping=True)
    if url.startswith("mysql"):
        # Same visibility semantics as PostgreSQL's default so the lock-then-check
        # booking logic behaves identically on both engines.
        kwargs["pool_recycle"] = 1800
        kwargs["isolation_level"] = "READ COMMITTED"
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = build_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, rolled back on error."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Unit-of-work helper for workers/scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def for_update(stmt, db: Session):
    """Apply SELECT ... FOR UPDATE where the dialect supports it (PG/MySQL).

    SQLite serialises writers at the database level, so the lock clause is
    simply skipped there.
    """
    name = db.get_bind().dialect.name
    if name == "postgresql":
        # Lock only the primary entity's rows (PostgreSQL refuses FOR UPDATE on the
        # nullable side of the outer joins produced by eager-loaded relationships).
        entity = stmt.column_descriptions[0].get("entity")
        return stmt.with_for_update(of=entity) if entity is not None else stmt.with_for_update()
    if name in ("mysql", "mariadb"):
        return stmt.with_for_update()
    return stmt
