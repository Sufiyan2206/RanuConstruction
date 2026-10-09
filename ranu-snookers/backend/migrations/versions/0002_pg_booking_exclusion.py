"""PostgreSQL-only: database-level guarantee against overlapping bookings.

EXCLUDE USING gist (table_id WITH =, tstzrange(start_at, end_at) WITH &&)
for bookings that block the table. The application already prevents overlaps
with row locks (portable to MySQL); this is defence in depth.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT ex_bookings_no_overlap
        EXCLUDE USING gist (table_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
        WHERE (status IN ('CONFIRMED','CHECKED_IN','IN_PROGRESS'))
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ex_bookings_no_overlap")
