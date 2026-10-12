"""Create the first Super Admin on a fresh production database.

    python -m app.create_admin --username owner --name "Club Owner" --password '<strong password>'
    python -m app.create_admin ... --branch-code MAIN --branch-name "RANU Snookers – Main"   # also creates club + branch
"""
from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Branch, Club, Role, User, UserRole
from app.schemas.settings import BranchSettings
from app.seed import ensure_org, seed_reference


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--password")
    ap.add_argument("--pin")
    ap.add_argument("--branch-code")
    ap.add_argument("--branch-name")
    ap.add_argument("--timezone", default="Asia/Kolkata")
    a = ap.parse_args()
    password = a.password or getpass.getpass("Password: ")
    if len(password) < 10:
        raise SystemExit("Use at least 10 characters")
    with SessionLocal() as db:
        org = ensure_org(db)
        seed_reference(db, org)
        if a.branch_code and not db.scalar(select(Branch.id).where(Branch.code == a.branch_code.upper())):
            club = db.scalar(select(Club).where(Club.organization_id == org.id)) or Club(organization_id=org.id, name=org.name)
            db.add(club)
            db.flush()
            db.add(Branch(organization_id=org.id, club_id=club.id, code=a.branch_code.upper(), name=a.branch_name or a.branch_code,
                          timezone=a.timezone, settings=BranchSettings().model_dump(mode="json")))
        if db.scalar(select(User.id).where(User.username == a.username.lower())):
            raise SystemExit("Username already exists")
        u = User(organization_id=org.id, username=a.username.lower(), full_name=a.name, password_hash=hash_password(password),
                 pin_hash=hash_password(a.pin) if a.pin else None)
        db.add(u)
        db.flush()
        role = db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == "SUPER_ADMIN"))
        db.add(UserRole(user_id=u.id, role_id=role.id, branch_id=None))
        db.commit()
        print(f"Super Admin '{u.username}' created.")


if __name__ == "__main__":
    main()
