"""Real concurrency tests (spec §9, §45). Run against PostgreSQL/MySQL; skipped on SQLite
because SQLite serialises all writers anyway."""
import threading
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal, engine
from app.core.errors import AppError
from app.models import Booking, GameSession
from app.models.enums import DetectionMethod
from app.services import booking_service, session_service
from tests.conftest import freeze_at, local_dt, table_id

pytestmark = pytest.mark.skipif(engine.dialect.name == "sqlite", reason="needs a server database with row locks")


def _race(n, fn):
    barrier = threading.Barrier(n)
    results = []

    def worker(i):
        db = SessionLocal()
        try:
            barrier.wait()
            fn(db, i)
            results.append("ok")
        except AppError as e:
            results.append(e.code)
        except Exception as e:  # pragma: no cover
            results.append(type(e).__name__)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_ten_customers_racing_for_same_slot_only_one_wins(db, branch_id):
    freeze_at(local_dt(1, 12))
    tid = uuid.UUID(table_id(db, 1))
    start = local_dt(1, 18)
    res = _race(10, lambda s, i: booking_service.create_hold(s, branch_id=uuid.UUID(branch_id), table_id=tid, start=start, duration=60,
                                                              customer={"name": f"C{i}", "phone": f"90000000{i:02d}"}))
    assert res.count("ok") == 1 and res.count("BOOKING_CONFLICT") == 9
    db.expire_all()
    assert db.scalar(select(func.count(Booking.id)).where(Booking.table_id == tid)) == 1


def test_receptionists_and_sensor_starting_same_table(db):
    freeze_at(local_dt(0, 19))
    tid = uuid.UUID(table_id(db, 5))
    methods = [DetectionMethod.MANUAL, DetectionMethod.MANUAL, DetectionMethod.SENSOR, DetectionMethod.RFID, DetectionMethod.QR]
    _race(len(methods), lambda s, i: session_service.start(s, None, tid, method=methods[i]))
    db.expire_all()
    assert db.scalar(select(func.count(GameSession.id)).where(GameSession.table_id == tid)) == 1
