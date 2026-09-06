"""add lead matches

Revision ID: b6c1a4d92e30
Revises: 746f24b87002
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6c1a4d92e30"
down_revision: str | None = "746f24b87002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_match",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rationale", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("gaps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["job_lead.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lead_id", "profile_id", name="uq_lead_match_profile"),
    )
    op.create_index(op.f("ix_lead_match_lead_id"), "lead_match", ["lead_id"], unique=False)
    op.create_index(op.f("ix_lead_match_profile_id"), "lead_match", ["profile_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_lead_match_profile_id"), table_name="lead_match")
    op.drop_index(op.f("ix_lead_match_lead_id"), table_name="lead_match")
    op.drop_table("lead_match")
