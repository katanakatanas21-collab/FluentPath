"""Preserve unknown historical course, class and lesson-completion times.

The reviewed source has 16 courses without either historical timestamp, one
class without creation time, and two lesson completions with only a shared
progress-update time (not individual completion times). No dates are invented.
Existing server defaults for new courses are retained; imports explicitly NULL.
"""
from alembic import op

revision = "0003_unknown_history_times"
down_revision = "0002_nullable_user_created_at"
branch_labels = None
depends_on = None

COLUMNS = (
    ("courses", "created_at"),
    ("courses", "updated_at"),
    ("classes", "created_at"),
    ("lesson_completions", "completed_at"),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(table, column, nullable=True)


def downgrade() -> None:
    # Lock before checking: concurrent writes cannot race the guard.
    op.execute("LOCK TABLE courses, classes, lesson_completions IN ACCESS EXCLUSIVE MODE")
    predicate = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE {column} IS NULL)"
        for table, column in COLUMNS
    )
    op.execute(
        "DO $$ BEGIN IF " + predicate + " THEN "
        "RAISE EXCEPTION 'Cannot restore NOT NULL while unknown historical timestamps exist'; "
        "END IF; END $$;"
    )
    for table, column in reversed(COLUMNS):
        op.alter_column(table, column, nullable=False)
