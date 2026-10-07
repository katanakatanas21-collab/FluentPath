"""Allow an unknown legacy user creation timestamp to remain unknown.

Revision ID: 0002_nullable_user_created_at
Revises: 0001_initial_schema
"""
from alembic import op

revision = "0002_nullable_user_created_at"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "created_at", nullable=True)


def downgrade() -> None:
    # Refuse to invent timestamps if an import has used the nullable exception.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE created_at IS NULL) THEN
                RAISE EXCEPTION 'Cannot restore NOT NULL while unknown legacy timestamps exist';
            END IF;
        END $$;"""
    )
    op.alter_column("users", "created_at", nullable=False)
