"""Small shared helpers used by several services."""
from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import for_update
from app.core.deps import Principal
from app.core.errors import Forbidden, NotFound
from app.core.timeutil import to_local, utcnow
from app.models import Branch, DocumentSequence
from app.schemas.settings import BranchSettings

_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I (legacy app convention)


def random_code(length: int = 6, prefix: str = "") -> str:
    return prefix + "".join(secrets.choice(_REF_ALPHABET) for _ in range(length))


def get_branch(db: Session, branch_id: uuid.UUID) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch or branch.deleted_at is not None:
        raise NotFound("Branch not found")
    return branch


def branch_settings(branch: Branch) -> BranchSettings:
    return BranchSettings.load(branch.settings)


def ensure_branch_access(actor: Principal, branch: Branch, perm: str) -> None:
    if branch.organization_id != actor.organization_id:
        raise Forbidden("Branch belongs to another organisation")
    actor.require(perm, branch.id)


def next_number(db: Session, branch: Branch, name: str, prefix: str) -> str:
    """Sequential document number per branch per local year, e.g. INV-MAIN-2026-000042.

    The sequence row is locked FOR UPDATE, so concurrent invoice generation
    never produces duplicates (the UNIQUE constraint on the number is the backstop).
    """
    period = str(to_local(utcnow(), branch.timezone).year)
    stmt = for_update(
        select(DocumentSequence).where(
            DocumentSequence.branch_id == branch.id, DocumentSequence.name == name, DocumentSequence.period == period
        ),
        db,
    )
    seq = db.scalar(stmt)
    if seq is None:
        seq = DocumentSequence(branch_id=branch.id, name=name, period=period, next_value=1)
        db.add(seq)
        db.flush()
    value = seq.next_value
    seq.next_value = value + 1
    return f"{prefix}-{branch.code}-{period}-{value:06d}"
